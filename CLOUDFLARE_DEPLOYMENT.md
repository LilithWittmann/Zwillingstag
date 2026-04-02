# Cloudflare Deployment Guide

This guide explains how to deploy Zwillingstag to **Cloudflare Workers** (backend) and **Cloudflare Pages** (frontend) with **Workers KV** for data persistence.

The backend runs directly as a **Python Worker** using the existing FastAPI code – no rewrite required.

---

## Architecture

```
┌─────────────────────────────────┐     ┌────────────────────────────────────┐
│  Cloudflare Pages               │     │  Cloudflare Worker (Python)        │
│  (zwillingstag.pages.dev)       │────▶│  (zwillingstag-api.*.workers.dev)  │
│  Static React frontend          │ WS  │  FastAPI REST API + WebSocket      │
└─────────────────────────────────┘     │  Workers KV (permanent caching)    │
                                        └────────────────────────────────────┘
```

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Cloudflare Pages | Built with Vite, deployed as static assets |
| Backend API | Cloudflare Python Worker | FastAPI, REST + WebSocket |
| Caching | Workers KV | Members, speeches, reactions – stored permanently (no TTL) |

### Why no TTL on KV entries?

Bundestag speech data never changes once published.  Storing entries permanently avoids unnecessary re-fetching and reduces DIP API and OpenAI usage.  To force a refresh of a specific key, delete it manually (see the KV section below).

---

## Prerequisites

1. A [Cloudflare account](https://dash.cloudflare.com/sign-up) (free plan is sufficient for REST endpoints; WebSocket connections work on the free plan for a single Worker instance, but real-time broadcasting to multiple simultaneous clients requires a [Durable Object](https://developers.cloudflare.com/durable-objects/) on the Workers Paid plan)
2. [`uv`](https://docs.astral.sh/uv/) installed locally (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
3. Node.js 20+ (for Wrangler and the frontend build)

---

## One-time Setup

### 1 · Install Wrangler and authenticate

```bash
npm install -g wrangler
wrangler login          # opens browser for authentication
```

### 2 · Create the Workers KV namespace

```bash
cd cloudflare/worker
npm install             # installs Wrangler locally

npx wrangler kv namespace create KV_CACHE
# ↳ copy the id printed (e.g. abc123...)
```

Edit `cloudflare/worker/wrangler.jsonc` and replace the placeholder ID:

```jsonc
"kv_namespaces": [
  {
    "binding": "KV_CACHE",
    "id": "abc123..."    // ← paste your namespace ID here
  }
]
```

### 3 · Deploy the Worker

```bash
cd cloudflare/worker
uv run pywrangler deploy
```

The Worker URL will be printed (e.g. `https://zwillingstag-api.<account>.workers.dev`).

### 4 · Set Worker secrets

```bash
cd cloudflare/worker

# Optional – enables LLM-generated reactions via OpenAI
npx wrangler secret put OPENAI_API_KEY

# Optional – enables live Bundestag speech data from the DIP API
npx wrangler secret put BUNDESTAG_API_KEY
```

> **Without secrets** the Worker serves built-in mock speeches and deterministic reactions so the app works out of the box.

### 5 · Deploy the frontend

#### Option A – Wrangler CLI

```bash
cd frontend
npm install
VITE_API_URL=https://zwillingstag-api.<account>.workers.dev \
VITE_WS_URL=wss://zwillingstag-api.<account>.workers.dev/ws \
npm run build

npx wrangler pages deploy dist --project-name zwillingstag
```

#### Option B – Cloudflare Dashboard (no CLI needed)

Connect your GitHub repository in the Cloudflare Dashboard → **Workers & Pages → Create → Pages → Connect to Git**.

Build settings:

| Setting | Value |
|---|---|
| Build command | `npm run build` |
| Build output directory | `dist` |
| Root directory | `frontend` |
| `VITE_API_URL` | `https://zwillingstag-api.<account>.workers.dev` |
| `VITE_WS_URL` | `wss://zwillingstag-api.<account>.workers.dev/ws` |

---

## Local development

```bash
# Start the Python Worker locally
cd cloudflare/worker
uv run pywrangler dev

# In a separate terminal, start the React dev server
cd frontend
VITE_API_URL=http://localhost:8787 VITE_WS_URL=ws://localhost:8787/ws npm run dev
```

The local Worker is accessible at `http://localhost:8787`.

---

## Workers KV – what's cached

All entries are stored **permanently** (no TTL).  Speech data is immutable once published, so there is no reason to expire it.

| KV key | Content |
|---|---|
| `members` | CDU/CSU member list with seat positions |
| `speeches` | Available Bundestag speeches index |
| `proto:<session_id>` | Speeches parsed from one protocol XML |
| `speech:<id>` | Individual speech detail |
| `reactions:<speech_id>` | LLM-generated reactions (reused across sessions) |
| `current_speech_id` | ID of the currently selected speech |

### Clearing cached data

```bash
# List all keys
npx wrangler kv key list --namespace-id=<your-namespace-id>

# Force-refresh speeches (deletes the index; next request re-fetches)
npx wrangler kv key delete --namespace-id=<your-namespace-id> speeches

# Force-refresh a specific protocol
npx wrangler kv key delete --namespace-id=<your-namespace-id> "proto:<session_id>"

# Force-refresh members
npx wrangler kv key delete --namespace-id=<your-namespace-id> members
```

---

## Environment variables reference

### Worker secrets (`wrangler secret put`)

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key for LLM reactions (mock reactions when absent) |
| `BUNDESTAG_API_KEY` | [Bundestag DIP API key](https://dip.bundestag.de/api/v1/) (mock data when absent) |

### Worker vars (`wrangler.jsonc`)

| Variable | Default | Description |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model to use for reactions |

### Frontend build (`VITE_*`)

| Variable | Description |
|---|---|
| `VITE_API_URL` | Base URL of the Worker API (e.g. `https://zwillingstag-api.abc.workers.dev`) |
| `VITE_WS_URL` | WebSocket URL (e.g. `wss://zwillingstag-api.abc.workers.dev/ws`) |

Leave both unset for local development (Vite proxy handles routing automatically).

---

## Custom domain setup (optional)

To serve the frontend and API from the same domain (e.g. `zwillingstag.example.com/api`):

1. Add your domain to Cloudflare
2. In **Workers & Pages → zwillingstag-api → Settings → Domains & Routes**, add `api.example.com`
3. In **Pages → zwillingstag → Custom domains**, add `zwillingstag.example.com`
4. Update `VITE_API_URL=https://api.example.com` in your Pages build settings

With a shared apex domain you can also use a **Cloudflare Transform Rule** to route `/api/*` and `/ws` traffic from `zwillingstag.example.com` to the Worker, which means no `VITE_API_URL` env var is needed at all.
