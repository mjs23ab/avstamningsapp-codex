# Lokal avstämningsapp

En enkel offline-app för avstämning mellan huvudbok och kontoutdrag. Appen kör lokalt på datorn, sparar data i mappar och använder ingen databas.

## Starta

Mac:

```bash
./start_mac.command
```

Windows:

```bat
start_windows.bat
```

Alternativt kan appen alltid startas direkt med Python:

```bash
python3 app.py
```

Öppna sedan:

```text
http://127.0.0.1:8765
```

## Flytta till en annan dator

Kopiera hela mappen som innehåller appen. Minsta uppsättning är:

```text
app.py
README.md
static/
samples/
start_mac.command
start_windows.bat
```

Om du även vill flytta tidigare avstämningar, kopiera också:

```text
data/
```

På den andra datorn behöver Python vara installerat. Appen använder bara standarddelar i Python och kräver inga extra paket.

## Vad första versionen gör

- Importerar huvudbok och kontoutdrag som CSV.
- Importerar enklare SIE-transaktioner från huvudbok.
- Importerar TXT-filer där varje transaktionsrad innehåller datum och belopp.
- Importerar textbaserade PDF-filer. Skannade PDF:er behöver OCR först.
- Matchar poster på belopp, datum, referens och text.
- Försöker hitta många-till-en-matchningar, till exempel flera huvudboksposter mot en bankrad.
- Visar alla banktransaktioner först, med status för vad som redan finns eller saknas i huvudboken.
- Visar omatchade poster och differenser.
- Skapar svensk avstämningsrapport med bolagsnamn.
- Skapar anonymiserad rapport där belopp, datum, konto, status och matchningsrelationer är intakta.
- Exporterar AI-vänliga JSON-filer och CSV-filer för fortsatt analys.
- Lagrar importer, normaliserade filer, matchningar, rapport och audit log lokalt.
- Leter inte upp eller skickar data till internet.

## Lokal filstruktur

Avstämningar sparas i:

```text
data/
  Bolag/
    Period/
      imports/
      normalized/
      results/
      audit_log.json
```

## Bra att skicka in senare

För att anpassa appen till verkliga filer behövs helst:

- En anonymiserad huvudboksexport.
- Ett anonymiserat kontoutdrag.
- Vilka huvudbokskonton som ska stämmas av, till exempel 1930, 2440 eller 1510.
- Om bankbelopp i huvudboken brukar vara positivt/negativt på samma sätt som banken.
# avstamningsapp-codex
Lokal offline-app för avstämning mellan huvudbok och kontoutdrag.
