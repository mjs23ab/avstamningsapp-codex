# Överlämning till nästa Codex-chatt

Det här projektet är en lokal offline-app för redovisningsavstämning mellan huvudbok och kontoutdrag. Appen är byggd för att vara tekniskt enkel, köras lokalt på datorn och inte skicka någon bokföringsdata till internet.

## Kort sammanfattning av användarens mål

Användaren vill bygga en så enkel offline-app som möjligt för att stämma av huvudbok mot kontoutdrag och andra redovisningskonton. Kontoutdraget ska betraktas som den verkliga källan. Avvikelser ska därför i första hand förstås som sådant som behöver speglas, utredas eller korrigeras i huvudboken.

Viktiga krav:

- Appen ska kunna köras offline på datorn.
- Ingen SQLite/databas i första versionen.
- Data ska sparas lokalt i filer och mappar.
- Import ska stödja CSV, SIE, TXT och textbaserade PDF-filer.
- Skannade PDF-filer ska inte antas fungera utan OCR.
- Appen ska matcha huvudbok och kontoutdrag.
- Appen ska visa matchningar, avvikelser, huvudbok och bank separat.
- Appen ska också ha en samlad vy över alla transaktioner.
- Rapport/export ska finnas både med företagsnamn och anonymiserad.
- Anonymiserad export ska behålla belopp, datum, konton, status, differenser och matchningsrelationer.
- Anonymiserad export ska maskera bolagsnamn, filnamn, verifikationer, referenser och transaktionstexter.
- Export ska kunna användas för fortsatt analys, till exempel med AI.

## Nuvarande tekniskt upplägg

Appen är medvetet enkel:

- `app.py`: lokal Python-server, importlogik, matchningsmotor, rapporter och exporter.
- `static/index.html`: enkel webbvy.
- `static/app.js`: frontendlogik, tabbar, resultatvisning och nedladdningslänkar.
- `static/styles.css`: styling.
- `samples/`: provfiler i CSV och TXT.
- `data/`: lokala körningar, importer, normaliserade filer, rapporter och exportfiler.
- `start_mac.command`: startfil för Mac.
- `start_windows.bat`: startfil för Windows.

Appen körs lokalt på:

```text
http://127.0.0.1:8765
```

Start:

```bash
python3 -B app.py
```

Eller på Mac:

```bash
./start_mac.command
```

## Viktiga implementationer hittills

### Import

Stödda format:

- CSV
- SIE (`.sie`, `.se`, `.si`)
- TXT
- textbaserad PDF

CSV läses med rubrikmappning för datum, belopp, debet/kredit, text, referens, konto och verifikation.

SIE läses förenklat från `#VER` och `#TRANS`.

TXT läses antingen som avgränsad tabell eller rad-för-rad där varje transaktionsrad måste innehålla datum och belopp.

PDF läses i två steg:

- Om `pypdf` eller `PyPDF2` råkar finnas installerat används det.
- Annars används en enkel inbyggd textbaserad PDF-läsare som klarar vissa PDF:er med textlager.

Skannade PDF:er utan textlager ger felmeddelande om att OCR behövs.

### Matchning

Matchningsmotorn är regelbaserad:

- exakt/nära belopp
- datum inom angivet spann
- referens/OCR/fakturanummer
- textlikhet
- många-till-en-matchningar, till exempel flera huvudboksposter mot en bankrad

Matchningar får status `suggested` och säkerhet `hog`, `medel` eller `lag`.

### Vyer i appen

Det finns fem filtreringar/tabbar:

1. `Alla transaktioner`
2. `Matchningar`
3. `Avvikelser`
4. `Huvudbok`
5. `Bank`

`Alla transaktioner` är standardvyn efter avstämning. Den utgår från kontoutdraget som verklighet och visar:

- `matchad`
- `godkänd`
- `saknas i huvudbok`
- `finns bara i huvudbok`

Sammanfattningsrutorna visar:

- Matchningar
- Godkända
- Finns bara i huvudbok
- Saknas i huvudbok
- Öppen differens

### Rapporter och export

Efter varje avstämning skapas bland annat:

- `rapport_foretag.html`: svensk rapport med bolagsnamn.
- `rapport_anonym.html`: svensk anonymiserad rapport.
- `ai_export_foretag.json`: strukturerad full export för analys.
- `ai_export_anonym.json`: strukturerad anonymiserad export.
- `alla_transaktioner.csv`: samlad CSV-export.
- `alla_transaktioner_anonym.csv`: anonymiserad samlad CSV-export.
- `matchningar.csv`
- `avvikelser.csv`
- `matchningar.json`

Anonymiseringen är konsekvent inom en export. Exempel:

- företag: `ANONYMISERAT_BOLAG`
- filnamn: `FIL_001`
- referenser: `REF_001`
- verifikationer: `VER_001`
- transaktionstexter: `TEXT_001`

Belopp, datum, konton, status, differenser och matchningsrelationer behålls.

## Viktiga designbeslut från chatten

Vi diskuterade först om appen borde vara molnbaserad, integrerad i bokföringsprogram eller lokal. Användaren ville ha den tekniskt enklaste möjliga lösningen som körs offline. Därför valdes:

- lokal Python-app
- webbläsargränssnitt
- ingen databas
- filbaserad lagring
- regelbaserad matchning
- rapporter/export som lokala filer

SQLite valdes bort i första versionen. Rekommendationen är att bara lägga till SQLite senare om historik, flera bolag eller sökning blir svårt att hantera med filer.

Kontoutdraget ska betraktas som verkligheten. Huvudboken ska spegla kontoutdraget.

## Viktigt att veta vid fortsatt utveckling

Appen är fortfarande en MVP. Den är användbar för test och vidareutveckling, men behöver anpassas mot riktiga exportformat från banker och bokföringsprogram.

Prioriterade nästa steg:

1. Testa med anonymiserade verkliga filer från användaren.
2. Förbättra TXT/PDF-parsern utifrån faktiska radformat.
3. Lägga till tydligare inställningar för tecken på belopp, till exempel om bank och huvudbok har omvända plus/minus.
4. Lägga till export av föreslagna bokföringsrättelser.
5. Lägga till manuell matchning/redigering i gränssnittet.
6. Lägga till låsning av avstämd period.
7. Lägga till bättre audit trail för manuella beslut.
8. Lägga till OCR-flöde senare om skannade PDF:er är vanligt.

## Flyttinstruktion

För fortsatt utveckling i Codex på en annan dator:

1. Packa upp `avstamningsapp_codex_full.zip` om du vill ha med körhistorik och exempeldata.
2. Packa upp `avstamningsapp_codex_source.zip` om du bara vill ha ren källkod och provfiler.
3. Öppna den uppackade mappen i Codex.
4. Be nästa Codex läsa den här filen först:

```text
HANDOFF_NASTA_CODEX.md
```

5. Starta appen med:

```bash
python3 -B app.py
```

6. Öppna:

```text
http://127.0.0.1:8765
```

## Rekommenderad prompt till nästa Codex

```text
Jag fortsätter utveckla en lokal offline-app för redovisningsavstämning. Läs HANDOFF_NASTA_CODEX.md först och sätt dig in i app.py, static/app.js, static/index.html och README.md. Appen ska vara enkel, filbaserad och offline. Kontoutdraget är källan till verkligheten och huvudboken ska spegla det. Jag vill fortsätta utveckla funktionaliteten utan att införa databas eller moln i första hand.
```

