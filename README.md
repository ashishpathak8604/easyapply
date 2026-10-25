# AI Job Application Assistant

A free, local, semi-automatic job search assistant. Phase 1 turns a resume PDF
into a reviewed `profile.json` and collects jobs from free, public sources into
SQLite with deduplication.

## Phase status

- **Phase 1: complete in code.** Profile builder, LLM wrapper, four collectors,
  SQLite storage, CLI and automated tests are implemented.
- **Phase 2 onward: not started.** Matching, tailoring, browser form filling and
  the dashboard are planned next.

Phase 1 is only fully done for your own data after you (1) place your resume at
`data/resume.pdf`, (2) run `build-profile` and review `data/profile.json`, and
(3) run a real collection and confirm a second run inserts no duplicates.

## Requirements

- Python 3.11 or newer
- A resume PDF with selectable text (not a scanned image)
- Optional: Ollama, or free Gemini/Groq API keys for AI-assisted extraction
- Optional: a free Adzuna API key if you enable the Adzuna source

Everything runs locally. No job source or AI provider is contacted unless you
explicitly enable it.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Then:

1. Put your resume at `data/resume.pdf` (or pass `--resume <path>`).
2. Fill in `config.yaml`: target roles, preferred locations, contact details,
   and the sources you want to enable.
3. Add secrets to `.env` only if you use Adzuna or a cloud AI provider. `.env`
   is ignored by git.

## Usage

Build the profile from your resume:

```powershell
python -m src.cli build-profile
```

This uses conservative local extraction by default and prints a summary for
review. Edit `data/profile.json` by hand if needed; later runs preserve your
edits unless you pass `--force` (which creates a timestamped backup first).

Preview the parse without writing anything:

```powershell
python -m src.cli build-profile --dry-run --force
```

Try the collectors offline with the saved fixtures:

```powershell
python -m src.cli collect --fixtures tests/fixtures/collectors
python -m src.cli list-jobs --limit 20
python -m src.cli list-jobs --limit 20 --json
```

The fixture run enables whichever sources you enabled in `config.yaml`. Enable
Greenhouse/Lever and add company slugs, or use the fixture data for testing
without touching the network.

Live collection is opt-in and requires both `enabled: true` in `config.yaml` and
the explicit flag:

```powershell
python -m src.cli collect --allow-network
```

Re-running collection is safe: jobs are deduplicated by `(source, id)` and by a
normalized hash of company + title + location.

### Sources

| Source | Configuration |
| --- | --- |
| Greenhouse | `sources.greenhouse.company_slugs` (public board slugs) |
| Lever | `sources.lever.company_slugs` (public board slugs) |
| Adzuna | `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env` |
| RemoteOK | `sources.remoteok.enabled: true` |

Only public, documented endpoints are used. LinkedIn, Indeed and Naukri are
deliberately not automated.

### Optional AI extraction

AI extraction is off by default because it sends resume text to a provider. To
use it, set `ai.resume_data_transfer_approved: true` and configure a provider in
`config.yaml`, then run:

```powershell
python -m src.cli build-profile --use-ai --force
```

Ollama keeps the data local. Gemini and Groq use their free tiers. The provider
is behind one wrapper (`src/llm/`) and can be swapped by changing `config.yaml`.

## Tests

```powershell
python -m pytest -q
```

The suite covers profile parsing and schema validation, manual-edit
preservation, database deduplication, all four collectors, fixture offline mode,
the network guard and rerun deduplication.

## Project layout

```text
config.yaml                 # preferences, limits, sources, AI settings
.env.example                # secret template (copy to .env)
src/
  cli.py                    # build-profile, collect, list-jobs
  config.py                 # config loading and validation
  models.py                 # Job model and dedupe hash
  collectors/               # greenhouse, lever, adzuna, remoteok, orchestration
  db/                       # SQLite schema and repository
  llm/                      # provider wrapper (Gemini, Groq, Ollama)
  profile/                  # PDF extraction, local parser, schema, builder
tests/
  fixtures/collectors/      # saved JSON responses for offline tests
data/                       # resume, profile and database (git-ignored)
```

## Troubleshooting

- **`resume PDF not found`**: place the file at `data/resume.pdf` or pass
  `--resume`.
- **`could not read usable text`**: the PDF is probably a scan. Export a
  text-based PDF or keep a plain-text copy.
- **`No job sources are enabled`**: set `sources.<name>.enabled: true` in
  `config.yaml`.
- **`Live network collection is blocked`**: this is intentional. Use
  `--fixtures` for offline mode or `--allow-network` after you approve access.
- **Adzuna credential error**: set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env`.
- **PyMuPDF install issue**: the pinned version is `1.28.2`. If your Python
  version has no wheel, `pdfplumber` alone still handles most text PDFs.

## Safety rules

- Never submit an application without human approval (applies to later phases).
- The AI may only use facts from `profile.json` and `config.yaml`.
- Secrets stay in `.env`; personal data and the database are git-ignored.
- Network access is off by default and must be explicitly allowed.
