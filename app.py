#!/usr/bin/env python3
import argparse
import csv
from email.parser import BytesParser
from email.policy import default as email_policy
import html
import io
import json
import math
import os
import re
import shlex
import sys
import time
import uuid
import webbrowser
import zlib
from datetime import datetime, date
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from itertools import combinations
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
SAMPLES_DIR = ROOT / "samples"


DATE_KEYS = [
    "datum",
    "bokforingsdatum",
    "bokföringsdatum",
    "transaktionsdatum",
    "verdatum",
    "betalningsdatum",
    "date",
    "transaction date",
]
AMOUNT_KEYS = ["belopp", "amount", "summa", "saldoändring", "saldoandring", "transaktionsbelopp"]
DEBIT_KEYS = ["debet", "debit", "in", "insatt", "insättning", "insattning"]
CREDIT_KEYS = ["kredit", "credit", "ut", "uttag", "utbetalt"]
TEXT_KEYS = ["text", "beskrivning", "transaktion", "meddelande", "notering", "namn", "description", "memo"]
REFERENCE_KEYS = ["referens", "ref", "ocr", "fakturanr", "fakturanummer", "invoice", "reference"]
ACCOUNT_KEYS = ["konto", "kontonr", "account", "account no", "konto nr"]
VOUCHER_KEYS = ["verifikation", "vernr", "ver.nr", "verifikationsnr", "voucher", "voucher no"]


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def safe_name(value, fallback):
    value = (value or fallback).strip()
    value = re.sub(r"[^A-Za-z0-9ÅÄÖåäö._ -]+", "", value)
    value = re.sub(r"\s+", "_", value)
    return value[:80] or fallback


def decode_bytes(raw):
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("latin-1", errors="replace")


def normalize_key(key):
    key = (key or "").strip().lower()
    key = key.replace("\ufeff", "")
    key = re.sub(r"[\s_./:-]+", " ", key)
    return key.strip()


def find_col(headers, candidates):
    normalized = {normalize_key(header): header for header in headers}
    for candidate in candidates:
        target = normalize_key(candidate)
        if target in normalized:
            return normalized[target]
    for header in headers:
        normalized_header = normalize_key(header)
        if any(normalize_key(candidate) in normalized_header for candidate in candidates):
            return header
    return None


def parse_decimal(value):
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    text = text.replace("\xa0", " ").replace("SEK", "").replace("kr", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("() ")
    if text.endswith("-"):
        negative = True
        text = text[:-1]
    text = re.sub(r"\s+", "", text)
    text = text.replace("−", "-")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9+.-]", "", text)
    if text in ("", "-", "+"):
        return 0.0
    try:
        number = float(text)
    except ValueError:
        return 0.0
    return -abs(number) if negative else number


def parse_date(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.split(" ")[0]
    formats = ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def date_distance(a, b):
    try:
        da = datetime.strptime(a, "%Y-%m-%d").date()
        db = datetime.strptime(b, "%Y-%m-%d").date()
        return abs((da - db).days)
    except ValueError:
        return 9999


def money_equal(a, b, tolerance):
    return abs(round(a - b, 2)) <= tolerance


def normalize_reference(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9åäö]+", "", text)
    return text


def token_set(text):
    text = str(text or "").lower()
    tokens = re.findall(r"[a-zåäö0-9]{3,}", text)
    noisy = {"betalning", "bankgiro", "plusgiro", "överföring", "overforing", "faktura"}
    return {token for token in tokens if token not in noisy}


def text_similarity(a, b):
    left = token_set(a)
    right = token_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left | right), 1)


def parse_csv_transactions(raw, source, account_filter=""):
    text = decode_bytes(raw)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,	,")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []
    if not headers:
        return []

    date_col = find_col(headers, DATE_KEYS)
    amount_col = find_col(headers, AMOUNT_KEYS)
    debit_col = find_col(headers, DEBIT_KEYS)
    credit_col = find_col(headers, CREDIT_KEYS)
    text_col = find_col(headers, TEXT_KEYS)
    ref_col = find_col(headers, REFERENCE_KEYS)
    account_col = find_col(headers, ACCOUNT_KEYS)
    voucher_col = find_col(headers, VOUCHER_KEYS)

    rows = []
    for index, row in enumerate(reader, start=1):
        account = str(row.get(account_col, "") if account_col else "").strip()
        if account_filter and account and account != account_filter:
            continue

        if amount_col:
            amount = parse_decimal(row.get(amount_col))
        else:
            amount = parse_decimal(row.get(debit_col)) - parse_decimal(row.get(credit_col))

        if abs(amount) < 0.000001:
            continue

        description = str(row.get(text_col, "") if text_col else "").strip()
        reference = str(row.get(ref_col, "") if ref_col else "").strip()
        voucher = str(row.get(voucher_col, "") if voucher_col else "").strip()
        transaction = {
            "id": f"{source[:1].upper()}{index}",
            "source": source,
            "date": parse_date(row.get(date_col, "") if date_col else ""),
            "amount": round(amount, 2),
            "description": description,
            "reference": reference,
            "reference_key": normalize_reference(reference),
            "account": account,
            "voucher": voucher,
            "raw": row,
        }
        rows.append(transaction)
    return rows


def parse_sie_transactions(raw, source, account_filter=""):
    text = decode_bytes(raw)
    rows = []
    current = {"series": "", "number": "", "date": "", "text": ""}
    index = 1

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#FLAGGA"):
            continue
        if stripped.startswith("#VER"):
            try:
                parts = shlex.split(stripped, posix=False)
            except ValueError:
                parts = stripped.split()
            if len(parts) >= 4:
                current = {
                    "series": parts[1].strip('"'),
                    "number": parts[2].strip('"'),
                    "date": parse_date(parts[3].strip('"')),
                    "text": " ".join(part.strip('"') for part in parts[4:]),
                }
            continue
        if not stripped.startswith("#TRANS"):
            continue

        match = re.match(
            r'#TRANS\s+("?[^"\s]+"?|\S+)\s+\{[^}]*\}\s+([+-]?[0-9][0-9\s.,-]*)\s*([0-9]{8})?\s*(.*)$',
            stripped,
        )
        if not match:
            continue
        account = match.group(1).strip('"')
        if account_filter and account != account_filter:
            continue
        amount = parse_decimal(match.group(2))
        if abs(amount) < 0.000001:
            continue
        transaction_date = parse_date(match.group(3) or current["date"])
        description = (match.group(4) or current["text"]).strip().strip('"')
        voucher = f'{current["series"]}{current["number"]}'.strip()
        rows.append(
            {
                "id": f"{source[:1].upper()}{index}",
                "source": source,
                "date": transaction_date,
                "amount": round(amount, 2),
                "description": description or current["text"],
                "reference": "",
                "reference_key": "",
                "account": account,
                "voucher": voucher,
                "raw": {"sie_line": stripped},
            }
        )
        index += 1
    return rows


def extract_pdf_text_with_library(raw):
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
            reader = module.PdfReader(io.BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            continue
    return ""


def read_pdf_literal(content, start):
    depth = 1
    index = start + 1
    output = bytearray()
    while index < len(content):
        char = content[index]
        if char == 92 and index + 1 < len(content):
            next_char = content[index + 1]
            escapes = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12, 40: 40, 41: 41, 92: 92}
            if next_char in escapes:
                output.append(escapes[next_char])
                index += 2
                continue
            if 48 <= next_char <= 55:
                octal = bytes(content[index + 1 : index + 4])
                octal = re.match(rb"[0-7]{1,3}", octal).group(0)
                output.append(int(octal, 8))
                index += 1 + len(octal)
                continue
            output.append(next_char)
            index += 2
            continue
        if char == 40:
            depth += 1
            output.append(char)
        elif char == 41:
            depth -= 1
            if depth == 0:
                return bytes(output), index + 1
            output.append(char)
        else:
            output.append(char)
        index += 1
    return bytes(output), index


def decode_pdf_string(value):
    if value.startswith(b"\xfe\xff"):
        return value[2:].decode("utf-16-be", errors="replace")
    if value.startswith(b"\xff\xfe"):
        return value[2:].decode("utf-16-le", errors="replace")
    return value.decode("cp1252", errors="replace")


def extract_text_from_pdf_stream(content):
    chunks = []
    index = 0
    while index < len(content):
        char = content[index]
        if char == 40:
            value, index = read_pdf_literal(content, index)
            text = decode_pdf_string(value).strip()
            if text:
                chunks.append(text)
            continue
        if char == 60 and index + 1 < len(content) and content[index + 1] != 60:
            end = content.find(b">", index + 1)
            if end != -1:
                hex_value = re.sub(rb"\s+", b"", content[index + 1 : end])
                if len(hex_value) % 2 == 0 and re.fullmatch(rb"[0-9A-Fa-f]+", hex_value or b""):
                    try:
                        text = decode_pdf_string(bytes.fromhex(hex_value.decode("ascii"))).strip()
                        if text and re.search(r"[A-Za-zÅÄÖåäö0-9]", text):
                            chunks.append(text)
                    except ValueError:
                        pass
                index = end + 1
                continue
        index += 1
    return "\n".join(chunks)


def extract_pdf_text_basic(raw):
    texts = []
    stream_pattern = re.compile(rb"(<<.*?>>)\s*stream\r?\n?(.*?)\r?\n?endstream", re.S)
    for match in stream_pattern.finditer(raw):
        dictionary = match.group(1)
        content = match.group(2).strip(b"\r\n")
        if b"/FlateDecode" in dictionary:
            try:
                content = zlib.decompress(content)
            except zlib.error:
                continue
        stream_text = extract_text_from_pdf_stream(content)
        if stream_text:
            texts.append(stream_text)
    return "\n".join(texts)


def extract_pdf_text(raw):
    text = extract_pdf_text_with_library(raw) or extract_pdf_text_basic(raw)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 20:
        raise ValueError(
            "PDF-filen verkar sakna läsbart textlager. Om den är skannad behövs OCR innan appen kan läsa den."
        )
    return text


def has_delimited_header(text):
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    header = lines[0].lower()
    return any(separator in header for separator in (";", "\t", ",")) and any(key in header for key in DATE_KEYS)


def find_date_in_text(line):
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{8}\b",
        r"\b\d{4}/\d{2}/\d{2}\b",
        r"\b\d{2}[./-]\d{2}[./-]\d{4}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, line)
        if match:
            return match.group(0), match.span()
    return "", None


def find_amount_in_text(line):
    amount_pattern = re.compile(r"(?<![A-Za-z0-9])[+-]?(?:\d{1,3}(?:[ .]\d{3})+|\d+)[,.]\d{2}-?(?![A-Za-z0-9])")
    matches = list(amount_pattern.finditer(line))
    if not matches:
        return "", None
    match = matches[-1]
    return match.group(0), match.span()


def parse_text_transactions(text, source, account_filter=""):
    rows = []
    index = 1
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line.replace("\xa0", " ")).strip()
        if not line:
            continue
        date_text, date_span = find_date_in_text(line)
        amount_text, amount_span = find_amount_in_text(line)
        if not date_text or not amount_text:
            continue

        account = ""
        account_match = None
        for candidate in re.finditer(r"\b\d{4}\b", line):
            if candidate.group(0) != date_text[:4]:
                account = candidate.group(0)
                account_match = candidate
                break
        if account_filter and account and account != account_filter:
            continue

        amount = parse_decimal(amount_text)
        if abs(amount) < 0.000001:
            continue

        cleanup_parts = [date_span, amount_span]
        if account_match is not None:
            cleanup_parts.append(account_match.span())
        description = line
        for start, end in sorted(cleanup_parts, reverse=True):
            description = description[:start] + " " + description[end:]
        description = re.sub(r"\s+", " ", description).strip(" -;|")

        reference = ""
        ref_match = re.search(r"\b(?:ocr|ref|fakt(?:ura)?nr?)[: ]*([A-Za-z0-9-]{2,})", line, re.I)
        if ref_match:
            reference = ref_match.group(1)
        else:
            candidates = [
                item
                for item in re.findall(r"\b[A-Za-z]?\d{3,}[A-Za-z]?\b", line)
                if item not in (date_text, date_text[:4], account)
            ]
            if candidates:
                reference = candidates[0]

        rows.append(
            {
                "id": f"{source[:1].upper()}{index}",
                "source": source,
                "date": parse_date(date_text),
                "amount": round(amount, 2),
                "description": description,
                "reference": reference,
                "reference_key": normalize_reference(reference),
                "account": account,
                "voucher": "",
                "raw": {"text_line": raw_line},
            }
        )
        index += 1
    return rows


def parse_transactions(filename, raw, source, account_filter=""):
    suffix = Path(filename or "").suffix.lower()
    if suffix in (".se", ".sie", ".si"):
        return parse_sie_transactions(raw, source, account_filter)
    if suffix == ".pdf":
        rows = parse_text_transactions(extract_pdf_text(raw), source, account_filter)
        if not rows:
            raise ValueError("PDF-filen kunde läsas som text, men inga transaktionsrader hittades.")
        return rows
    if suffix == ".txt":
        text = decode_bytes(raw)
        if has_delimited_header(text):
            rows = parse_csv_transactions(raw, source, account_filter)
            if rows:
                return rows
        rows = parse_text_transactions(text, source, account_filter)
        if not rows:
            raise ValueError("TXT-filen kunde inte tolkas. Den behöver innehålla datum och belopp per rad.")
        return rows
    return parse_csv_transactions(raw, source, account_filter)



def score_pair(ledger, bank, tolerance, max_days):
    if not money_equal(ledger["amount"], bank["amount"], tolerance):
        return 0, []
    days = date_distance(ledger["date"], bank["date"])
    if days > max_days:
        return 0, []

    score = 55
    reasons = ["belopp"]
    if days == 0:
        score += 20
        reasons.append("samma datum")
    else:
        score += max(0, 18 - days * 3)
        reasons.append(f"datum +/- {days} dagar")

    left_ref = ledger.get("reference_key")
    right_ref = bank.get("reference_key")
    if left_ref and right_ref and left_ref == right_ref:
        score += 25
        reasons.append("referens")

    similarity = text_similarity(
        " ".join([ledger.get("description", ""), ledger.get("reference", ""), ledger.get("voucher", "")]),
        " ".join([bank.get("description", ""), bank.get("reference", "")]),
    )
    if similarity > 0:
        score += min(15, int(similarity * 20))
        reasons.append("text")

    return score, reasons


def confidence_from_score(score, match_type):
    if match_type == "many_to_one":
        if score >= 92:
            return "hog"
        if score >= 78:
            return "medel"
        return "lag"
    if score >= 92:
        return "hog"
    if score >= 78:
        return "medel"
    return "lag"


def reconcile(ledger, bank, tolerance=0.01, max_days=3):
    matches = []
    used_ledger = set()
    used_bank = set()

    candidates = []
    for ledger_row in ledger:
        for bank_row in bank:
            score, reasons = score_pair(ledger_row, bank_row, tolerance, max_days)
            if score:
                candidates.append((score, ledger_row["id"], bank_row["id"], reasons))

    candidates.sort(reverse=True, key=lambda item: item[0])
    ledger_by_id = {row["id"]: row for row in ledger}
    bank_by_id = {row["id"]: row for row in bank}

    for score, ledger_id, bank_id, reasons in candidates:
        if ledger_id in used_ledger or bank_id in used_bank:
            continue
        used_ledger.add(ledger_id)
        used_bank.add(bank_id)
        matches.append(
            {
                "id": f"M{len(matches) + 1}",
                "type": "one_to_one",
                "status": "suggested",
                "confidence": confidence_from_score(score, "one_to_one"),
                "score": score,
                "reason": ", ".join(reasons),
                "ledger_ids": [ledger_id],
                "bank_ids": [bank_id],
                "ledger_amount": ledger_by_id[ledger_id]["amount"],
                "bank_amount": bank_by_id[bank_id]["amount"],
                "difference": round(ledger_by_id[ledger_id]["amount"] - bank_by_id[bank_id]["amount"], 2),
            }
        )

    remaining_ledger = [row for row in ledger if row["id"] not in used_ledger]
    remaining_bank = [row for row in bank if row["id"] not in used_bank]

    for bank_row in remaining_bank:
        nearby = [
            row
            for row in remaining_ledger
            if row["id"] not in used_ledger
            and date_distance(row["date"], bank_row["date"]) <= max(max_days, 5)
            and (row["amount"] == 0 or math.copysign(1, row["amount"]) == math.copysign(1, bank_row["amount"]))
            and abs(row["amount"]) <= abs(bank_row["amount"]) + tolerance
        ][:14]
        found = None
        for size in range(2, min(5, len(nearby) + 1)):
            for combo in combinations(nearby, size):
                amount_sum = round(sum(row["amount"] for row in combo), 2)
                if money_equal(amount_sum, bank_row["amount"], tolerance):
                    date_score = sum(max(0, 10 - date_distance(row["date"], bank_row["date"])) for row in combo)
                    text_score = max(
                        text_similarity(row.get("description", ""), bank_row.get("description", "")) for row in combo
                    )
                    found = (combo, 76 + min(16, date_score) + int(text_score * 10))
                    break
            if found:
                break
        if found:
            combo, score = found
            ledger_ids = [row["id"] for row in combo]
            for ledger_id in ledger_ids:
                used_ledger.add(ledger_id)
            used_bank.add(bank_row["id"])
            matches.append(
                {
                    "id": f"M{len(matches) + 1}",
                    "type": "many_to_one",
                    "status": "suggested",
                    "confidence": confidence_from_score(score, "many_to_one"),
                    "score": score,
                    "reason": "summering av flera huvudboksposter",
                    "ledger_ids": ledger_ids,
                    "bank_ids": [bank_row["id"]],
                    "ledger_amount": round(sum(row["amount"] for row in combo), 2),
                    "bank_amount": bank_row["amount"],
                    "difference": round(sum(row["amount"] for row in combo) - bank_row["amount"], 2),
                }
            )

    unmatched_ledger = [row for row in ledger if row["id"] not in used_ledger]
    unmatched_bank = [row for row in bank if row["id"] not in used_bank]
    total_ledger = round(sum(row["amount"] for row in ledger), 2)
    total_bank = round(sum(row["amount"] for row in bank), 2)
    matched_ledger = round(sum(match["ledger_amount"] for match in matches), 2)
    matched_bank = round(sum(match["bank_amount"] for match in matches), 2)

    return {
        "matches": matches,
        "unmatched_ledger": unmatched_ledger,
        "unmatched_bank": unmatched_bank,
        "summary": {
            "ledger_count": len(ledger),
            "bank_count": len(bank),
            "match_count": len(matches),
            "approved_count": 0,
            "unmatched_ledger_count": len(unmatched_ledger),
            "unmatched_bank_count": len(unmatched_bank),
            "total_ledger": total_ledger,
            "total_bank": total_bank,
            "matched_ledger": matched_ledger,
            "matched_bank": matched_bank,
            "open_difference": round(total_ledger - total_bank, 2),
        },
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def parse_multipart_form(headers, body):
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("Formuläret måste skickas som multipart/form-data")

    header_blob = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = BytesParser(policy=email_policy).parsebytes(header_blob + body)
    if not message.is_multipart():
        raise ValueError("Kunde inte läsa uppladdade filer")

    fields = {}
    files = {}
    for part in message.iter_parts():
        if "form-data" not in str(part.get("Content-Disposition", "")):
            continue
        params = dict(part.get_params(header="content-disposition", unquote=True) or [])
        name = params.get("name")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        filename = params.get("filename")
        if filename is not None:
            files[name] = {"filename": filename, "content": payload}
        else:
            charset = part.get_content_charset() or "utf-8"
            fields[name] = payload.decode(charset, errors="replace")
    return fields, files


def append_audit(project_dir, event, details):
    path = project_dir / "audit_log.json"
    log = read_json(path, [])
    log.append({"time": now_iso(), "event": event, "details": details})
    write_json(path, log)


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


SUMMARY_LABELS = {
    "ledger_count": "Antal huvudboksposter",
    "bank_count": "Antal banktransaktioner",
    "match_count": "Antal matchningar",
    "approved_count": "Godkända matchningar",
    "unmatched_ledger_count": "Finns bara i huvudbok",
    "unmatched_bank_count": "Saknas i huvudbok",
    "total_ledger": "Summa huvudbok",
    "total_bank": "Summa kontoutdrag",
    "matched_ledger": "Matchad summa huvudbok",
    "matched_bank": "Matchad summa kontoutdrag",
    "open_difference": "Öppen differens",
}

ALL_TRANSACTION_FIELDS = [
    "status",
    "datum",
    "bank_id",
    "bank_referens",
    "bank_text",
    "bank_belopp",
    "huvudbok_id",
    "huvudbok_konto",
    "huvudbok_verifikation",
    "huvudbok_referens",
    "huvudbok_text",
    "huvudbok_belopp",
    "differens_mot_huvudbok",
    "match_id",
    "match_typ",
    "sakerhet",
    "kommentar",
]


class Anonymizer:
    def __init__(self):
        self.values = {}
        self.counts = {}

    def token(self, value, prefix):
        text = str(value or "").strip()
        if not text:
            return ""
        key = (prefix, text)
        if key not in self.values:
            self.counts[prefix] = self.counts.get(prefix, 0) + 1
            self.values[key] = f"{prefix}_{self.counts[prefix]:03d}"
        return self.values[key]


def get_report_metadata(project_dir, metadata=None):
    if metadata is None:
        metadata = read_json(project_dir / "metadata.json", {})
    try:
        parts = project_dir.relative_to(DATA_DIR).parts
    except ValueError:
        parts = ()
    return {
        "company": metadata.get("company") or (parts[0] if len(parts) > 0 else "Bolag"),
        "period": metadata.get("period") or (parts[1] if len(parts) > 1 else ""),
        "run_id": metadata.get("run_id") or (parts[2] if len(parts) > 2 else ""),
        "created_at": metadata.get("created_at") or now_iso(),
        "account_filter": metadata.get("account_filter", ""),
        "ledger_file": metadata.get("ledger_file", ""),
        "bank_file": metadata.get("bank_file", ""),
        "tolerance": metadata.get("tolerance", ""),
        "max_days": metadata.get("max_days", ""),
    }


def clean_transaction(row):
    return {
        "id": row.get("id", ""),
        "source": row.get("source", ""),
        "date": row.get("date", ""),
        "amount": row.get("amount", 0),
        "account": row.get("account", ""),
        "voucher": row.get("voucher", ""),
        "reference": row.get("reference", ""),
        "description": row.get("description", ""),
    }


def anonymize_transaction(row, anonymizer):
    cleaned = clean_transaction(row)
    cleaned["voucher"] = anonymizer.token(cleaned["voucher"], "VER")
    cleaned["reference"] = anonymizer.token(cleaned["reference"], "REF")
    cleaned["description"] = anonymizer.token(cleaned["description"], "TEXT")
    return cleaned


def transaction_text(row):
    return " ".join(
        str(item)
        for item in [row.get("date"), row.get("voucher") or row.get("reference") or row.get("id"), row.get("description")]
        if item
    )


def join_values(rows, key):
    values = [str(row.get(key, "")).strip() for row in rows if str(row.get(key, "")).strip()]
    return " | ".join(values)


def build_all_transaction_rows(result, ledger, bank):
    ledger_by_id = {row["id"]: row for row in ledger}
    bank_by_id = {row["id"]: row for row in bank}
    rows = []

    for match in result["matches"]:
        ledger_rows = [ledger_by_id[item] for item in match["ledger_ids"] if item in ledger_by_id]
        bank_rows = [bank_by_id[item] for item in match["bank_ids"] if item in bank_by_id]
        ledger_amount = round(sum(row.get("amount", 0) for row in ledger_rows), 2)
        ledger_text = " | ".join(transaction_text(row) for row in ledger_rows)
        for bank_row in bank_rows:
            status = "godkänd" if match["status"] == "approved" else "matchad"
            rows.append(
                {
                    "status": status,
                    "datum": bank_row.get("date", ""),
                    "bank_id": bank_row.get("id", ""),
                    "bank_referens": bank_row.get("reference", ""),
                    "bank_text": transaction_text(bank_row),
                    "bank_belopp": bank_row.get("amount", 0),
                    "huvudbok_id": join_values(ledger_rows, "id"),
                    "huvudbok_konto": join_values(ledger_rows, "account"),
                    "huvudbok_verifikation": join_values(ledger_rows, "voucher"),
                    "huvudbok_referens": join_values(ledger_rows, "reference"),
                    "huvudbok_text": ledger_text,
                    "huvudbok_belopp": ledger_amount,
                    "differens_mot_huvudbok": round(ledger_amount - bank_row.get("amount", 0), 2),
                    "match_id": match["id"],
                    "match_typ": match["type"],
                    "sakerhet": match["confidence"],
                    "kommentar": match["reason"],
                }
            )

    for bank_row in result["unmatched_bank"]:
        rows.append(
            {
                "status": "saknas i huvudbok",
                "datum": bank_row.get("date", ""),
                "bank_id": bank_row.get("id", ""),
                "bank_referens": bank_row.get("reference", ""),
                "bank_text": transaction_text(bank_row),
                "bank_belopp": bank_row.get("amount", 0),
                "huvudbok_id": "",
                "huvudbok_konto": "",
                "huvudbok_verifikation": "",
                "huvudbok_referens": "",
                "huvudbok_text": "",
                "huvudbok_belopp": 0,
                "differens_mot_huvudbok": round(0 - bank_row.get("amount", 0), 2),
                "match_id": "",
                "match_typ": "",
                "sakerhet": "",
                "kommentar": "Kontoutdraget har en transaktion som inte syns i huvudboken.",
            }
        )

    for ledger_row in result["unmatched_ledger"]:
        rows.append(
            {
                "status": "finns bara i huvudbok",
                "datum": ledger_row.get("date", ""),
                "bank_id": "",
                "bank_referens": "",
                "bank_text": "",
                "bank_belopp": 0,
                "huvudbok_id": ledger_row.get("id", ""),
                "huvudbok_konto": ledger_row.get("account", ""),
                "huvudbok_verifikation": ledger_row.get("voucher", ""),
                "huvudbok_referens": ledger_row.get("reference", ""),
                "huvudbok_text": transaction_text(ledger_row),
                "huvudbok_belopp": ledger_row.get("amount", 0),
                "differens_mot_huvudbok": ledger_row.get("amount", 0),
                "match_id": "",
                "match_typ": "",
                "sakerhet": "",
                "kommentar": "Huvudboken har en post som inte finns på kontoutdraget.",
            }
        )

    return sorted(rows, key=lambda row: (str(row.get("datum", "")), str(row.get("status", "")), str(row.get("bank_id", ""))))


def anonymize_export_data(metadata, result, ledger, bank):
    anonymizer = Anonymizer()
    anon_ledger = [anonymize_transaction(row, anonymizer) for row in ledger]
    anon_bank = [anonymize_transaction(row, anonymizer) for row in bank]
    ledger_by_id = {row["id"]: row for row in anon_ledger}
    bank_by_id = {row["id"]: row for row in anon_bank}
    anon_result = {
        "matches": [dict(match) for match in result["matches"]],
        "unmatched_ledger": [ledger_by_id[row["id"]] for row in result["unmatched_ledger"] if row["id"] in ledger_by_id],
        "unmatched_bank": [bank_by_id[row["id"]] for row in result["unmatched_bank"] if row["id"] in bank_by_id],
        "summary": dict(result["summary"]),
    }
    anon_metadata = dict(metadata)
    anon_metadata["company"] = "ANONYMISERAT_BOLAG"
    anon_metadata["ledger_file"] = anonymizer.token(metadata.get("ledger_file", ""), "FIL")
    anon_metadata["bank_file"] = anonymizer.token(metadata.get("bank_file", ""), "FIL")
    return anon_metadata, anon_result, anon_ledger, anon_bank


def build_export_payload(project_dir, result, ledger, bank, metadata, anonymized=False):
    if anonymized:
        metadata, result, ledger, bank = anonymize_export_data(metadata, result, ledger, bank)
    payload = {
        "schema_version": 1,
        "exported_at": now_iso(),
        "anonymized": anonymized,
        "anonymization_note": (
            "Belopp, datum, konton, status och matchningsrelationer är intakta. "
            "Bolagsnamn, filnamn, verifikationer, referenser och transaktionstexter är ersatta med stabila koder."
            if anonymized
            else ""
        ),
        "metadata": metadata,
        "summary": result["summary"],
        "summary_sv": {SUMMARY_LABELS.get(key, key): value for key, value in result["summary"].items()},
        "all_transactions": build_all_transaction_rows(result, ledger, bank),
        "matches": [dict(match) for match in result["matches"]],
        "unmatched_bank_missing_in_ledger": [clean_transaction(row) for row in result["unmatched_bank"]],
        "unmatched_ledger_only": [clean_transaction(row) for row in result["unmatched_ledger"]],
        "ledger_transactions": [clean_transaction(row) for row in ledger],
        "bank_transactions": [clean_transaction(row) for row in bank],
    }
    return payload


def html_table(rows, fields, empty_text):
    if not rows:
        return f"<p>{html.escape(empty_text)}</p>"
    headers = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(field, '')))}</td>" for field in fields)
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{headers}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def report_interpretation(summary):
    if summary["unmatched_bank_count"] == 0 and summary["unmatched_ledger_count"] == 0 and summary["open_difference"] == 0:
        return "Avstämningen saknar öppna avvikelser. Kontoutdrag och huvudbok stämmer för importerade poster."
    parts = []
    if summary["unmatched_bank_count"]:
        parts.append(
            f"{summary['unmatched_bank_count']} banktransaktioner saknas i huvudboken och bör bokföras eller utredas."
        )
    if summary["unmatched_ledger_count"]:
        parts.append(
            f"{summary['unmatched_ledger_count']} huvudboksposter saknas på kontoutdraget och bör kontrolleras."
        )
    if summary["open_difference"]:
        parts.append(f"Öppen differens är {summary['open_difference']}.")
    return " ".join(parts)


def write_report_html(path, payload):
    metadata = payload["metadata"]
    title = "Anonymiserad avstämningsrapport" if payload["anonymized"] else "Avstämningsrapport"
    summary_rows = [
        {"Nyckeltal": SUMMARY_LABELS.get(key, key), "Värde": value} for key, value in payload["summary"].items()
    ]
    all_rows = payload["all_transactions"]
    deviation_rows = [
        row for row in all_rows if row["status"] in ("saknas i huvudbok", "finns bara i huvudbok")
    ]
    match_rows = [
        {
            "match_id": match["id"],
            "status": match["status"],
            "säkerhet": match["confidence"],
            "typ": match["type"],
            "huvudbok_id": ", ".join(match["ledger_ids"]),
            "bank_id": ", ".join(match["bank_ids"]),
            "belopp_huvudbok": match["ledger_amount"],
            "belopp_bank": match["bank_amount"],
            "differens": match["difference"],
            "grund": match["reason"],
        }
        for match in payload["matches"]
    ]
    anonymized_note = (
        "<p><strong>Anonymisering:</strong> Belopp, datum, konton, status och matchningsrelationer är intakta. "
        "Bolagsnamn, filnamn, verifikationer, referenser och transaktionstexter är ersatta med stabila koder.</p>"
        if payload["anonymized"]
        else ""
    )
    document = f"""<!doctype html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 32px; color: #17212b; }}
    h1 {{ font-size: 26px; margin-bottom: 6px; }}
    h2 {{ font-size: 18px; margin-top: 28px; }}
    p {{ max-width: 920px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 13px; }}
    th, td {{ border: 1px solid #d8dee4; padding: 7px; text-align: left; vertical-align: top; }}
    th {{ background: #edf2f4; }}
    .meta {{ color: #53606b; }}
    .section {{ overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="meta">Bolag: {html.escape(str(metadata.get('company', '')))} | Period: {html.escape(str(metadata.get('period', '')))} | Skapad: {html.escape(str(payload['exported_at']))}</p>
  <p class="meta">Huvudbok: {html.escape(str(metadata.get('ledger_file', '')))} | Kontoutdrag: {html.escape(str(metadata.get('bank_file', '')))} | Konto: {html.escape(str(metadata.get('account_filter', '')))}</p>
  {anonymized_note}
  <h2>Sammanfattning</h2>
  <div class="section">{html_table(summary_rows, ['Nyckeltal', 'Värde'], 'Ingen sammanfattning finns.')}</div>
  <h2>Tolkning</h2>
  <p>{html.escape(report_interpretation(payload['summary']))}</p>
  <h2>Alla transaktioner</h2>
  <p>Kontoutdraget används som utgångspunkt. Avvikelser visar vad som saknas i huvudboken eller finns endast i huvudboken.</p>
  <div class="section">{html_table(all_rows, ALL_TRANSACTION_FIELDS, 'Inga transaktioner finns.')}</div>
  <h2>Avvikelser att utreda</h2>
  <div class="section">{html_table(deviation_rows, ALL_TRANSACTION_FIELDS, 'Inga avvikelser finns.')}</div>
  <h2>Matchningar</h2>
  <div class="section">{html_table(match_rows, ['match_id', 'status', 'säkerhet', 'typ', 'huvudbok_id', 'bank_id', 'belopp_huvudbok', 'belopp_bank', 'differens', 'grund'], 'Inga matchningar finns.')}</div>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8")


def create_reports(project_dir, result, ledger, bank, metadata=None):
    results_dir = project_dir / "results"
    metadata = get_report_metadata(project_dir, metadata)
    matches = result["matches"]
    ledger_by_id = {row["id"]: row for row in ledger}
    bank_by_id = {row["id"]: row for row in bank}

    match_rows = []
    for match in matches:
        ledger_rows = [ledger_by_id[item] for item in match["ledger_ids"] if item in ledger_by_id]
        bank_rows = [bank_by_id[item] for item in match["bank_ids"] if item in bank_by_id]
        match_rows.append(
            {
                "match_id": match["id"],
                "status": match["status"],
                "confidence": match["confidence"],
                "type": match["type"],
                "ledger_ids": ", ".join(match["ledger_ids"]),
                "bank_ids": ", ".join(match["bank_ids"]),
                "ledger_amount": match["ledger_amount"],
                "bank_amount": match["bank_amount"],
                "difference": match["difference"],
                "reason": match["reason"],
                "ledger_text": " | ".join(row.get("description", "") for row in ledger_rows),
                "bank_text": " | ".join(row.get("description", "") for row in bank_rows),
            }
        )
    write_csv(
        results_dir / "matchningar.csv",
        match_rows,
        [
            "match_id",
            "status",
            "confidence",
            "type",
            "ledger_ids",
            "bank_ids",
            "ledger_amount",
            "bank_amount",
            "difference",
            "reason",
            "ledger_text",
            "bank_text",
        ],
    )

    deviation_rows = []
    for row in result["unmatched_ledger"]:
        deviation_rows.append(
            {
                "source": "huvudbok",
                "id": row["id"],
                "date": row["date"],
                "amount": row["amount"],
                "account": row.get("account", ""),
                "reference": row.get("reference", ""),
                "description": row.get("description", ""),
            }
        )
    for row in result["unmatched_bank"]:
        deviation_rows.append(
            {
                "source": "bank",
                "id": row["id"],
                "date": row["date"],
                "amount": row["amount"],
                "account": row.get("account", ""),
                "reference": row.get("reference", ""),
                "description": row.get("description", ""),
            }
        )
    write_csv(
        results_dir / "avvikelser.csv",
        deviation_rows,
        ["source", "id", "date", "amount", "account", "reference", "description"],
    )

    full_payload = build_export_payload(project_dir, result, ledger, bank, metadata, anonymized=False)
    anonymized_payload = build_export_payload(project_dir, result, ledger, bank, metadata, anonymized=True)
    write_json(results_dir / "ai_export_foretag.json", full_payload)
    write_json(results_dir / "ai_export_anonym.json", anonymized_payload)
    write_csv(results_dir / "alla_transaktioner.csv", full_payload["all_transactions"], ALL_TRANSACTION_FIELDS)
    write_csv(
        results_dir / "alla_transaktioner_anonym.csv",
        anonymized_payload["all_transactions"],
        ALL_TRANSACTION_FIELDS,
    )
    write_report_html(results_dir / "rapport_foretag.html", full_payload)
    write_report_html(results_dir / "rapport_anonym.html", anonymized_payload)


def project_url_path(project_dir, filename):
    return "/files/" + "/".join(project_dir.relative_to(DATA_DIR).parts) + "/results/" + filename


def build_response(project_dir, result, ledger, bank):
    payload = dict(result)
    payload["project_id"] = "/".join(project_dir.relative_to(DATA_DIR).parts)
    payload["ledger"] = ledger
    payload["bank"] = bank
    payload["downloads"] = {
        "report_full_html": project_url_path(project_dir, "rapport_foretag.html"),
        "report_anonymized_html": project_url_path(project_dir, "rapport_anonym.html"),
        "ai_export_full_json": project_url_path(project_dir, "ai_export_foretag.json"),
        "ai_export_anonymized_json": project_url_path(project_dir, "ai_export_anonym.json"),
        "all_transactions_csv": project_url_path(project_dir, "alla_transaktioner.csv"),
        "all_transactions_anonymized_csv": project_url_path(project_dir, "alla_transaktioner_anonym.csv"),
        "matches_csv": project_url_path(project_dir, "matchningar.csv"),
        "deviations_csv": project_url_path(project_dir, "avvikelser.csv"),
    }
    return payload


def run_reconciliation(company, period, ledger_file, ledger_bytes, bank_file, bank_bytes, account_filter, tolerance, max_days):
    company_name = safe_name(company, "Bolag")
    period_name = safe_name(period, datetime.now().strftime("%Y-%m"))
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    metadata = {
        "company": company,
        "period": period,
        "run_id": run_id,
        "created_at": now_iso(),
        "account_filter": account_filter,
        "ledger_file": ledger_file,
        "bank_file": bank_file,
        "tolerance": tolerance,
        "max_days": max_days,
    }
    project_dir = DATA_DIR / company_name / period_name / run_id
    imports_dir = project_dir / "imports"
    normalized_dir = project_dir / "normalized"
    results_dir = project_dir / "results"
    imports_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    ledger_path = imports_dir / safe_name(ledger_file, "huvudbok.csv")
    bank_path = imports_dir / safe_name(bank_file, "kontoutdrag.csv")
    ledger_path.write_bytes(ledger_bytes)
    bank_path.write_bytes(bank_bytes)

    ledger = parse_transactions(ledger_file, ledger_bytes, "ledger", account_filter)
    bank = parse_transactions(bank_file, bank_bytes, "bank", "")
    result = reconcile(ledger, bank, tolerance=tolerance, max_days=max_days)

    write_json(normalized_dir / "huvudbok.json", ledger)
    write_json(normalized_dir / "bank.json", bank)
    write_json(results_dir / "matchningar.json", result)
    write_json(project_dir / "metadata.json", metadata)
    append_audit(
        project_dir,
        "reconciliation_created",
        {
            "company": company,
            "period": period,
            "ledger_file": ledger_file,
            "bank_file": bank_file,
            "account_filter": account_filter,
            "tolerance": tolerance,
            "max_days": max_days,
        },
    )
    create_reports(project_dir, result, ledger, bank, metadata)
    return build_response(project_dir, result, ledger, bank)


def ensure_samples():
    SAMPLES_DIR.mkdir(exist_ok=True)
    ledger = SAMPLES_DIR / "huvudbok_demo.csv"
    bank = SAMPLES_DIR / "kontoutdrag_demo.csv"
    if not ledger.exists():
        ledger.write_text(
            """datum;konto;verifikation;referens;text;belopp
2026-01-03;1930;A1;1001;Kundbetalning faktura 1001;12500,00
2026-01-05;1930;A2;BG556;Leverantör X faktura 556;-4200,00
2026-01-07;1930;A3;1002;Kundbetalning faktura 1002;7800,00
2026-01-07;1930;A4;1003;Kundbetalning faktura 1003;2200,00
2026-01-09;1930;A5;BANKAVG;Bankavgift januari;-49,00
2026-01-12;1930;A6;OKLAR;Manuell post som saknas i bank;199,00
""",
            encoding="utf-8",
        )
    if not bank.exists():
        bank.write_text(
            """datum;referens;beskrivning;belopp
2026-01-03;1001;Inbetalning faktura 1001;12500,00
2026-01-06;BG556;Betalning leverantör X;-4200,00
2026-01-07;BUNT;Inbetalning fakturor 1002 och 1003;10000,00
2026-01-09;BANKAVG;Bankavgift;-49,00
2026-01-14;NY;Bankpost utan bokföring;-350,00
""",
            encoding="utf-8",
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "AvstamningLocal/0.1"

    def log_message(self, format, *args):
        sys.stdout.write("[%s] %s\n" % (now_iso(), format % args))

    def send_json(self, payload, status=HTTPStatus.OK):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_text(self, text, status=HTTPStatus.OK):
        raw = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = unquote(self.path.split("?", 1)[0])
        if path == "/":
            return self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            target = STATIC_DIR / path.removeprefix("/static/")
            return self.serve_file(target)
        if path == "/api/demo":
            ensure_samples()
            try:
                response = run_reconciliation(
                    "Demo_Bolag",
                    "2026-01",
                    "huvudbok_demo.csv",
                    (SAMPLES_DIR / "huvudbok_demo.csv").read_bytes(),
                    "kontoutdrag_demo.csv",
                    (SAMPLES_DIR / "kontoutdrag_demo.csv").read_bytes(),
                    "1930",
                    0.01,
                    3,
                )
                return self.send_json(response)
            except Exception as exc:
                return self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        if path.startswith("/files/"):
            relative = Path(path.removeprefix("/files/"))
            if any(part in ("..", "") for part in relative.parts):
                return self.send_text("Invalid path", HTTPStatus.BAD_REQUEST)
            target = DATA_DIR / relative
            return self.serve_file(target)
        return self.send_text("Not found", HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/reconcile":
            return self.handle_reconcile()
        if path == "/api/approve":
            return self.handle_approve()
        return self.send_text("Not found", HTTPStatus.NOT_FOUND)

    def handle_reconcile(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            fields, files = parse_multipart_form(self.headers, self.rfile.read(length))
            ledger_item = files.get("ledger_file")
            bank_item = files.get("bank_file")
            if not ledger_item or not bank_item:
                raise ValueError("Välj både huvudbok och kontoutdrag")

            company = fields.get("company", "Bolag")
            period = fields.get("period", datetime.now().strftime("%Y-%m"))
            account_filter = fields.get("account_filter", "").strip()
            tolerance = parse_decimal(fields.get("tolerance", "0.01")) or 0.01
            max_days = int(parse_decimal(fields.get("max_days", "3")) or 3)
            response = run_reconciliation(
                company,
                period,
                ledger_item["filename"] or "huvudbok.csv",
                ledger_item["content"],
                bank_item["filename"] or "kontoutdrag.csv",
                bank_item["content"],
                account_filter,
                tolerance,
                max_days,
            )
            self.send_json(response)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def handle_approve(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            project_id = payload.get("project_id", "")
            match_ids = set(payload.get("match_ids", []))
            project_dir = DATA_DIR / Path(project_id)
            if any(part in ("..", "") for part in Path(project_id).parts):
                raise ValueError("Ogiltigt projekt-id")
            result_path = project_dir / "results" / "matchningar.json"
            result = read_json(result_path, None)
            if result is None:
                raise ValueError("Avstämningen hittades inte")
            approved = 0
            for match in result["matches"]:
                if match["id"] in match_ids:
                    match["status"] = "approved"
                    approved += 1
            result["summary"]["approved_count"] = sum(1 for match in result["matches"] if match["status"] == "approved")
            write_json(result_path, result)
            ledger = read_json(project_dir / "normalized" / "huvudbok.json", [])
            bank = read_json(project_dir / "normalized" / "bank.json", [])
            append_audit(project_dir, "matches_approved", {"match_ids": sorted(match_ids), "count": approved})
            create_reports(project_dir, result, ledger, bank)
            self.send_json(build_response(project_dir, result, ledger, bank))
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def serve_file(self, path, content_type=None):
        try:
            path = path.resolve()
            allowed_roots = [STATIC_DIR.resolve(), DATA_DIR.resolve()]
            if path.name in ("app.py",) or not any(str(path).startswith(str(root)) for root in allowed_roots):
                return self.send_text("Forbidden", HTTPStatus.FORBIDDEN)
            if not path.exists() or not path.is_file():
                return self.send_text("Not found", HTTPStatus.NOT_FOUND)
            if content_type is None:
                suffix = path.suffix.lower()
                content_type = {
                    ".html": "text/html; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".js": "application/javascript; charset=utf-8",
                    ".json": "application/json; charset=utf-8",
                    ".csv": "text/csv; charset=utf-8",
                }.get(suffix, "application/octet-stream")
            raw = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main():
    parser = argparse.ArgumentParser(description="Lokal avstämningsapp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    ensure_samples()
    DATA_DIR.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Avstämningsappen kör på {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStänger av.")


if __name__ == "__main__":
    main()
