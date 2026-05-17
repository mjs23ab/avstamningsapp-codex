let currentResult = null;
let currentView = "all";

const form = document.querySelector("#reconcileForm");
const runButton = document.querySelector("#runButton");
const demoButton = document.querySelector("#demoButton");
const statusText = document.querySelector("#statusText");
const approveButton = document.querySelector("#approveButton");
const approveStatus = document.querySelector("#approveStatus");
const results = document.querySelector("#results");
const summaryGrid = document.querySelector("#summaryGrid");
const resultTable = document.querySelector("#resultTable");
const downloadLinks = document.querySelector("#downloadLinks");

function money(value) {
  return new Intl.NumberFormat("sv-SE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0);
}

function confidenceLabel(value) {
  return { hog: "hög", medel: "medel", lag: "låg" }[value] || value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setBusy(isBusy, text) {
  runButton.disabled = isBusy;
  demoButton.disabled = isBusy;
  statusText.textContent = text || "";
}

function renderSummary(summary) {
  const metrics = [
    ["Matchningar", summary.match_count, "good"],
    ["Godkända", summary.approved_count, "good"],
    ["Finns bara i huvudbok", summary.unmatched_ledger_count, summary.unmatched_ledger_count ? "warn" : "good"],
    ["Saknas i huvudbok", summary.unmatched_bank_count, summary.unmatched_bank_count ? "warn" : "good"],
    ["Öppen differens", money(summary.open_difference), summary.open_difference ? "bad" : "good"],
  ];
  summaryGrid.innerHTML = metrics
    .map(([label, value, tone]) => `<div class="metric ${tone}"><strong>${escapeHtml(value)}</strong><span>${label}</span></div>`)
    .join("");
}

function renderDownloads(downloads) {
  downloadLinks.innerHTML = `
    <a href="${downloads.report_full_html}" target="_blank">Rapport med bolag</a>
    <a href="${downloads.report_anonymized_html}" target="_blank">Anonym rapport</a>
    <a href="${downloads.ai_export_full_json}" target="_blank">AI-export JSON</a>
    <a href="${downloads.ai_export_anonymized_json}" target="_blank">Anonym AI-export</a>
    <a href="${downloads.all_transactions_csv}" target="_blank">Alla transaktioner CSV</a>
    <a href="${downloads.all_transactions_anonymized_csv}" target="_blank">Anonym CSV</a>
    <a href="${downloads.matches_csv}" target="_blank">Matchningar CSV</a>
    <a href="${downloads.deviations_csv}" target="_blank">Avvikelser CSV</a>
  `;
}

function rowById(rows) {
  return Object.fromEntries(rows.map((row) => [row.id, row]));
}

function transactionLine(row) {
  if (!row) return "";
  return escapeHtml([row.date, row.voucher || row.reference || row.id, row.description].filter(Boolean).join(" "));
}

function renderAllTransactions() {
  const ledgerMap = rowById(currentResult.ledger);
  const bankMap = rowById(currentResult.bank);
  const rows = [];

  currentResult.matches.forEach((match) => {
    const ledgerRows = match.ledger_ids.map((id) => ledgerMap[id]).filter(Boolean);
    const bankRows = match.bank_ids.map((id) => bankMap[id]).filter(Boolean);
    bankRows.forEach((bankRow) => {
      rows.push({
        date: bankRow.date,
        status: match.status === "approved" ? "godkänd" : "matchad",
        statusClass: match.status === "approved" ? "approved" : match.confidence,
        bankText: transactionLine(bankRow),
        ledgerText: ledgerRows.map(transactionLine).join("<br>"),
        bankAmount: bankRow.amount,
        ledgerAmount: match.ledger_amount,
        difference: match.difference,
        note: match.reason,
      });
    });
  });

  currentResult.unmatched_bank.forEach((bankRow) => {
    rows.push({
      date: bankRow.date,
      status: "saknas i huvudbok",
      statusClass: "lag",
      bankText: transactionLine(bankRow),
      ledgerText: "Ingen huvudbokspost",
      bankAmount: bankRow.amount,
      ledgerAmount: 0,
      difference: roundMoney(0 - bankRow.amount),
      note: "Kontoutdraget har en transaktion som inte syns i huvudboken.",
    });
  });

  currentResult.unmatched_ledger.forEach((ledgerRow) => {
    rows.push({
      date: ledgerRow.date,
      status: "finns bara i huvudbok",
      statusClass: "lag",
      bankText: "Saknas på kontoutdrag",
      ledgerText: transactionLine(ledgerRow),
      bankAmount: 0,
      ledgerAmount: ledgerRow.amount,
      difference: roundMoney(ledgerRow.amount),
      note: "Huvudboken har en post som inte finns på kontoutdraget.",
    });
  });

  rows.sort((a, b) => String(a.date).localeCompare(String(b.date)) || String(a.status).localeCompare(String(b.status)));

  if (!rows.length) {
    resultTable.innerHTML = `<tbody><tr><td class="empty">Inga transaktioner att visa.</td></tr></tbody>`;
    return;
  }

  resultTable.innerHTML = `
    <thead>
      <tr>
        <th>Status</th>
        <th>Datum</th>
        <th>Kontoutdrag</th>
        <th>Huvudbok</th>
        <th>Belopp bank</th>
        <th>Belopp HB</th>
        <th>Diff mot HB</th>
        <th>Kommentar</th>
      </tr>
    </thead>
    <tbody>
      ${rows
        .map(
          (row) => `
            <tr>
              <td><span class="status ${row.statusClass}">${escapeHtml(row.status)}</span></td>
              <td>${escapeHtml(row.date)}</td>
              <td>${row.bankText}</td>
              <td>${row.ledgerText}</td>
              <td class="amount">${money(row.bankAmount)}</td>
              <td class="amount">${money(row.ledgerAmount)}</td>
              <td class="amount">${money(row.difference)}</td>
              <td>${escapeHtml(row.note)}</td>
            </tr>
          `,
        )
        .join("")}
    </tbody>
  `;
}

function renderMatches() {
  const ledgerMap = rowById(currentResult.ledger);
  const bankMap = rowById(currentResult.bank);
  if (!currentResult.matches.length) {
    resultTable.innerHTML = `<tbody><tr><td class="empty">Inga matchningar hittades.</td></tr></tbody>`;
    return;
  }

  resultTable.innerHTML = `
    <thead>
      <tr>
        <th>Val</th>
        <th>Status</th>
        <th>Säkerhet</th>
        <th>Huvudbok</th>
        <th>Bank</th>
        <th>Belopp HB</th>
        <th>Belopp Bank</th>
        <th>Diff</th>
        <th>Grund</th>
      </tr>
    </thead>
    <tbody>
      ${currentResult.matches
        .map((match) => {
          const ledgerText = match.ledger_ids
            .map((id) => {
              const row = ledgerMap[id];
              return row ? `${row.date} ${row.voucher || row.id} ${row.description}` : id;
            })
            .join("<br>");
          const bankText = match.bank_ids
            .map((id) => {
              const row = bankMap[id];
              return row ? `${row.date} ${row.reference || row.id} ${row.description}` : id;
            })
            .join("<br>");
          const checked = match.status === "approved" ? "checked disabled" : "";
          const statusClass = match.status === "approved" ? "approved" : match.confidence;
          return `
            <tr>
              <td><input type="checkbox" class="match-check" value="${match.id}" ${checked}></td>
              <td><span class="status ${statusClass}">${match.status === "approved" ? "godkänd" : "förslag"}</span></td>
              <td><span class="status ${match.confidence}">${confidenceLabel(match.confidence)}</span></td>
              <td>${ledgerText}</td>
              <td>${bankText}</td>
              <td class="amount">${money(match.ledger_amount)}</td>
              <td class="amount">${money(match.bank_amount)}</td>
              <td class="amount">${money(match.difference)}</td>
              <td>${escapeHtml(match.reason)}</td>
            </tr>
          `;
        })
        .join("")}
    </tbody>
  `;
}

function renderDeviations() {
  const rows = [
    ...currentResult.unmatched_ledger.map((row) => ({ ...row, sourceLabel: "Huvudbok" })),
    ...currentResult.unmatched_bank.map((row) => ({ ...row, sourceLabel: "Bank" })),
  ];
  if (!rows.length) {
    resultTable.innerHTML = `<tbody><tr><td class="empty">Inga avvikelser kvar.</td></tr></tbody>`;
    return;
  }
  resultTable.innerHTML = `
    <thead>
      <tr>
        <th>Källa</th>
        <th>Datum</th>
        <th>Konto</th>
        <th>Referens</th>
        <th>Text</th>
        <th>Belopp</th>
      </tr>
    </thead>
    <tbody>
      ${rows
        .map(
          (row) => `
            <tr>
              <td>${row.sourceLabel}</td>
              <td>${escapeHtml(row.date)}</td>
              <td>${escapeHtml(row.account)}</td>
              <td>${escapeHtml(row.reference)}</td>
              <td>${escapeHtml(row.description)}</td>
              <td class="amount">${money(row.amount)}</td>
            </tr>
          `,
        )
        .join("")}
    </tbody>
  `;
}

function renderTransactions(rows, sourceLabel) {
  if (!rows.length) {
    resultTable.innerHTML = `<tbody><tr><td class="empty">Inga poster importerades från ${sourceLabel}.</td></tr></tbody>`;
    return;
  }
  resultTable.innerHTML = `
    <thead>
      <tr>
        <th>ID</th>
        <th>Datum</th>
        <th>Konto</th>
        <th>Ver</th>
        <th>Referens</th>
        <th>Text</th>
        <th>Belopp</th>
      </tr>
    </thead>
    <tbody>
      ${rows
        .map(
          (row) => `
            <tr>
              <td>${escapeHtml(row.id)}</td>
              <td>${escapeHtml(row.date)}</td>
              <td>${escapeHtml(row.account)}</td>
              <td>${escapeHtml(row.voucher)}</td>
              <td>${escapeHtml(row.reference)}</td>
              <td>${escapeHtml(row.description)}</td>
              <td class="amount">${money(row.amount)}</td>
            </tr>
          `,
        )
        .join("")}
    </tbody>
  `;
}

function renderTable() {
  if (!currentResult) return;
  approveButton.style.display = currentView === "matches" ? "" : "none";
  if (currentView === "all") renderAllTransactions();
  if (currentView === "matches") renderMatches();
  if (currentView === "deviations") renderDeviations();
  if (currentView === "ledger") renderTransactions(currentResult.ledger, "huvudbok");
  if (currentView === "bank") renderTransactions(currentResult.bank, "bank");
}

function roundMoney(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function setActiveView(view) {
  currentView = view;
  document.querySelectorAll(".tab").forEach((item) => {
    item.classList.toggle("is-active", item.dataset.view === view);
  });
}

function showResult(payload, view = "all") {
  currentResult = payload;
  results.classList.remove("is-hidden");
  setActiveView(view);
  renderSummary(payload.summary);
  renderDownloads(payload.downloads);
  renderTable();
}

async function postForm() {
  setBusy(true, "Stämmer av...");
  approveStatus.textContent = "";
  try {
    const response = await fetch("/api/reconcile", { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "Avstämningen misslyckades");
    showResult(payload);
    statusText.textContent = `Klar. ${payload.summary.match_count} matchningar hittades.`;
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    setBusy(false, statusText.textContent);
  }
}

async function runDemo() {
  setBusy(true, "Kör provdata...");
  approveStatus.textContent = "";
  try {
    const response = await fetch("/api/demo");
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "Provdata misslyckades");
    showResult(payload);
    statusText.textContent = `Klar. ${payload.summary.match_count} matchningar hittades.`;
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    setBusy(false, statusText.textContent);
  }
}

async function approveSelected() {
  if (!currentResult) return;
  const matchIds = [...document.querySelectorAll(".match-check:checked:not(:disabled)")].map((input) => input.value);
  if (!matchIds.length) {
    approveStatus.textContent = "Markera minst en matchning.";
    return;
  }
  approveButton.disabled = true;
    approveStatus.textContent = "Sparar godkännande...";
  try {
    const response = await fetch("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: currentResult.project_id, match_ids: matchIds }),
    });
    const payload = await response.json();
    if (!response.ok || payload.error) throw new Error(payload.error || "Godkännandet misslyckades");
    showResult(payload, currentView);
    approveStatus.textContent = `${matchIds.length} matchningar godkända.`;
  } catch (error) {
    approveStatus.textContent = error.message;
  } finally {
    approveButton.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  postForm();
});

demoButton.addEventListener("click", runDemo);
approveButton.addEventListener("click", approveSelected);

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    setActiveView(button.dataset.view);
    approveStatus.textContent = "";
    renderTable();
  });
});
