# GitHub-flytt

Projektet är förberett för GitHub. Koden kan läggas i ett nytt repo utan att lokala testkörningar och importerade bokföringsfiler följer med.

## Rekommenderat repo-namn

```text
avstamningsapp
```

## Vad som ska versionshanteras

Följande ska ingå i GitHub-repot:

```text
app.py
README.md
HANDOFF_NASTA_CODEX.md
GITHUB_SETUP.md
.gitignore
start_mac.command
start_windows.bat
static/
samples/
```

Följande ska inte ingå:

```text
data/
*.zip
.DS_Store
__pycache__/
```

## Om du skapar repo manuellt på GitHub

1. Gå till GitHub och skapa ett nytt repo, till exempel `avstamningsapp`.
2. Skapa det helst tomt, utan README, eftersom projektet redan har en README.
3. Kopiera repo-länken.
4. I den här mappen kan du sedan köra:

```bash
git remote add origin https://github.com/DITT-NAMN/avstamningsapp.git
git branch -M main
git push -u origin main
```

Om du använder GitHub Desktop kan du i stället välja den här mappen och klicka `Publish repository`.

## Prompt till nästa Codex efter GitHub-flytten

```text
Jag fortsätter utveckla en lokal offline-app för redovisningsavstämning. Läs HANDOFF_NASTA_CODEX.md först och sätt dig in i app.py, static/app.js, static/index.html och README.md. Appen ska vara enkel, filbaserad och offline. Kontoutdraget är källan till verkligheten och huvudboken ska spegla det. Jag vill fortsätta utveckla funktionaliteten utan att införa databas eller moln i första hand.
```

