# Zwillingstag Backend

## Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and fill in values:

```
BUNDESTAG_API_KEY=   # optional – get from https://dip.bundestag.de/api/v1/
OPENAI_API_KEY=      # required for LLM reactions
OPENAI_MODEL=gpt-4o-mini
POLL_INTERVAL_SECONDS=120
```

Without API keys the backend uses mock data (bundestag) and mock reactions (LLM).

## Run

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API docs available at http://localhost:8000/docs
