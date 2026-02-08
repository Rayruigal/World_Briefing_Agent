# world_brief – Daily World Briefing Agent

A minimal, production-ready Python agent that ingests news from RSS feeds and YouTube channels, classifies and summarises them with an LLM, and emails you a daily briefing.

---

## Architecture

![world_brief architecture](docs/architecture.png)

---

## API Keys & Accounts You Need

| API | Required? | Free Tier? | What It's Used For | How to Get It |
|---|---|---|---|---|
| **OpenAI-compatible LLM** | **Yes** | Varies | Classifying and summarising news items | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) — or any OpenAI-compatible provider (Ollama, Together, Groq, etc.) by setting `LLM_BASE_URL` |
| **YouTube Data API v3** | No (optional) | Yes (10,000 units/day) | Fetching recent uploads from YouTube channels | [console.cloud.google.com](https://console.cloud.google.com/) → APIs & Services → Enable "YouTube Data API v3" → Create an API key |
| **SMTP credentials** | No (use `DRY_RUN=1` without) | Yes (Gmail, etc.) | Sending the daily briefing email | Gmail: enable 2FA → create an [App Password](https://myaccount.google.com/apppasswords). Or use any SMTP provider. |

**For a quick test you only need `LLM_API_KEY`** — RSS feeds are public (no key), YouTube is optional, and `DRY_RUN=1` prints the email to your terminal.

---

## Features

| Capability | Detail |
|---|---|
| **Ingestion** | RSS feeds + YouTube Data API v3 |
| **Deduplication** | By URL and content hash (SHA-256) |
| **Classification** | LLM-based, strict JSON output with retries |
| **Summarisation** | LLM-generated plaintext briefing (500–900 words) |
| **Delivery** | SMTP email (with `DRY_RUN` print mode) |
| **Storage** | SQLite (file-based) – swap to Postgres via `DATABASE_URL` |
| **Scheduling** | External cron *or* built-in APScheduler |

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- An OpenAI-compatible LLM API key
- (Optional) YouTube Data API key
- (Optional) SMTP credentials for email delivery

### 2. Install

```bash
cd world_brief
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment

Edit the `.env` file in the project root (auto-loaded at startup, git-ignored).
Pick **one** LLM provider:

**Option A – Standard OpenAI (or any compatible API):**
```bash
LLM_API_KEY=sk-...
# LLM_BASE_URL=https://api.openai.com/v1   # optional; default = OpenAI
# LLM_MODEL=gpt-4o-mini                    # optional; default = gpt-4o-mini
```

**Option B – Azure OpenAI:**
```bash
AZURE_OPENAI_API_KEY=your-azure-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-12-01-preview
LLM_MODEL=your-deployment-name              # the deployment, not the model family
```

The provider is auto-detected: if `AZURE_OPENAI_ENDPOINT` is set, Azure is used; otherwise standard OpenAI.

Other variables:
```bash
# ── YouTube (optional – skipped if unset) ────────
# YOUTUBE_API_KEY=AIza...

# ── Email (required unless DRY_RUN=1) ────────────
# SMTP_HOST=smtp.gmail.com
# SMTP_PORT=587
# SMTP_USER=you@gmail.com
# SMTP_PASSWORD=app-password
# EMAIL_FROM=you@gmail.com
# EMAIL_TO=recipient@example.com

# ── Misc ─────────────────────────────────────────
DRY_RUN=1                        # print email instead of sending
# export LOG_LEVEL="DEBUG"        # default: INFO
# export SQLITE_PATH="world_brief.db"
# export DATABASE_URL="postgresql+psycopg2://user:pass@host/db"  # overrides SQLite
```

### 4. Edit Sources & Categories

- `config/sources.yaml` – add/remove RSS feeds and YouTube channels
- `config/categories.yaml` – change the allowed classification categories

### 5. Run Once (Dry Run)

```bash
DRY_RUN=1 python main.py
```

### 6. Run Once (Send Email)

```bash
python main.py
```

---

## Scheduling

### Option A: Cron (recommended for production)

```bash
# crontab -e
# 07:30 Europe/Zurich ≈ 06:30 UTC (winter) / 05:30 UTC (summer)
# Use a wrapper that sets TZ, or compute the UTC offset:

# Winter (CET = UTC+1):
30 6 * * * cd /path/to/world_brief && /path/to/.venv/bin/python main.py >> /var/log/world_brief.log 2>&1

# Summer (CEST = UTC+2):
30 5 * * * cd /path/to/world_brief && /path/to/.venv/bin/python main.py >> /var/log/world_brief.log 2>&1

# Or use a timezone-aware cron wrapper (systemd timer, cronie with CRON_TZ):
# CRON_TZ=Europe/Zurich
# 30 7 * * * cd /path/to/world_brief && /path/to/.venv/bin/python main.py
```

### Option B: Built-in Scheduler

```bash
python main.py --schedule
# Runs as a long-lived process; triggers at 07:30 Europe/Zurich daily.
```

---

## Switching to Postgres

1. Install the driver:
   ```bash
   pip install psycopg2-binary
   ```
2. Set the env var:
   ```bash
   export DATABASE_URL="postgresql+psycopg2://user:pass@localhost:5432/world_brief"
   ```
3. Run normally – tables are auto-created on first run.

---

## Extending Sources

### Adding a new RSS feed

Edit `config/sources.yaml`:

```yaml
rss_feeds:
  - name: "My New Feed"
    url: "https://example.com/rss.xml"
```

### Adding X (Twitter) / Bluesky / Other APIs

1. Create a new module, e.g. `ingest/x.py`.
2. Implement a function with the signature:
   ```python
   def ingest_all(config: list[dict], since: datetime) -> list[NormalizedItem]:
       ...
   ```
3. Wire it into `main.py`'s `run_pipeline()` alongside the RSS and YouTube calls.
4. Add any new config keys to `sources.yaml`.

The `NormalizedItem` dataclass and the rest of the pipeline (dedup → classify → summarise → email) remain unchanged.

---

## Project Structure

```
world_brief/
├── main.py                # CLI + orchestration
├── config/
│   ├── sources.yaml       # RSS feeds & YouTube channels
│   └── categories.yaml    # Allowed classification categories
├── ingest/
│   ├── http.py            # Shared HTTP client (retries + rate limit)
│   ├── rss.py             # RSS feed ingestion
│   └── youtube.py         # YouTube Data API ingestion
├── process/
│   ├── dedupe.py          # Deduplication (URL + content hash)
│   ├── classify.py        # LLM-based classification
│   └── summarize.py       # LLM-based summarisation
├── storage/
│   ├── models.py          # SQLAlchemy models + NormalizedItem dataclass
│   └── db.py              # DB engine, session, persistence helpers
├── emailer/
│   └── send.py            # SMTP email dispatch (+ DRY_RUN)
├── prompts/
│   ├── classify.txt       # Classification prompt template
│   └── summarize.txt      # Summarisation prompt template
├── requirements.txt
└── README.md
```

---

## Environment Variables Reference

**LLM – Standard OpenAI (or compatible):**

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_API_KEY` | Yes* | — | OpenAI-compatible API key |
| `LLM_BASE_URL` | No | OpenAI default | Custom LLM endpoint |
| `LLM_MODEL` | No | `gpt-4o-mini` | Model / deployment name |

**LLM – Azure OpenAI:**

| Variable | Required | Default | Description |
|---|---|---|---|
| `AZURE_OPENAI_API_KEY` | Yes* | — | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | Yes* | — | e.g. `https://my-resource.openai.azure.com` |
| `AZURE_OPENAI_API_VERSION` | No | `2024-12-01-preview` | Azure API version |
| `LLM_MODEL` | Yes* | — | Your Azure deployment name |

*\* Pick one provider. If `AZURE_OPENAI_ENDPOINT` is set, Azure is used automatically.*

**Other:**

| Variable | Required | Default | Description |
|---|---|---|---|
| `YOUTUBE_API_KEY` | No | — | YouTube Data API key (skipped if unset) |
| `SMTP_HOST` | If sending | — | SMTP server hostname |
| `SMTP_PORT` | If sending | `587` | SMTP port |
| `SMTP_USER` | If sending | — | SMTP login username |
| `SMTP_PASSWORD` | If sending | — | SMTP login password |
| `SMTP_USE_TLS` | No | `true` | Use STARTTLS |
| `EMAIL_FROM` | If sending | — | Sender address |
| `EMAIL_TO` | If sending | — | Recipient address |
| `DRY_RUN` | No | `false` | Print email instead of sending |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `SQLITE_PATH` | No | `world_brief.db` | SQLite file path |
| `DATABASE_URL` | No | — | Full DB URL (overrides SQLite) |

---

## License

MIT
