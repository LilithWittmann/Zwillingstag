# Cloudflare Deployment Guide

This guide explains how to deploy Zwillingstag to **Cloudflare Workers** (backend) and **Cloudflare Pages** (frontend) with **Workers KV** for data persistence.

---

## Architecture

```
┌─────────────────────────────────┐     ┌────────────────────────────────────┐
│  Cloudflare Pages               │     │  Cloudflare Worker                 │
│  (zwillingstag.pages.dev)       │────▶│  (zwillingstag-api.*.workers.dev)  │
│  Static React frontend          │ WS  │  REST API + WebSocket               │
└─────────────────────────────────┘     │  Durable Objects (real-time state)  │
                                        │  Workers KV (caching)               │
                                        └────────────────────────────────────┘
```

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Cloudflare Pages | Built with Vite, deployed as static assets |
| Backend API | Cloudflare Worker | TypeScript, REST + WebSocket |
| Real-time state | Durable Objects | Single global instance, WebSocket hub |
| Caching | Workers KV | Members (24 h), speeches (6 h), reactions (permanent) |

---

## Prerequisites

1. A [Cloudflare account](https://dash.cloudflare.com/sign-up) (free plan works for basic usage; **Durable Objects require the Workers Paid plan – $5/month**)
2. [Node.js 20+](https://nodejs.org/) and npm installed locally
3. Cloudflare API Token with **Edit Workers** and **Edit Pages** permissions

---

## One-time Setup

### 1 · Install Wrangler

```bash
npm install -g wrangler
wrangler login          # opens browser for authentication
```

### 2 · Create the Workers KV namespace

```bash
cd cloudflare/worker
npm install

# Create the production namespace
npx wrangler kv:namespace create KV_CACHE
# ↳ copy the id printed (e.g. abc123...)

# Create the preview namespace (used by `wrangler dev`)
npx wrangler kv:namespace create KV_CACHE --preview
# ↳ copy the preview_id printed
```

Edit `cloudflare/worker/wrangler.toml` and replace the placeholder IDs:

```toml
[[kv_namespaces]]
binding = "KV_CACHE"
id = "abc123..."           # ← paste production ID here
preview_id = "def456..."   # ← paste preview ID here
```

### 3 · Deploy the Worker for the first time

```bash
cd cloudflare/worker
npx wrangler deploy
```

This also creates the Durable Object migration (`v1`).

### 4 · Set Worker secrets

```bash
cd cloudflare/worker

# Optional – enables LLM-generated reactions via OpenAI
npx wrangler secret put OPENAI_API_KEY

# Optional – enables live Bundestag speech data from the DIP API
npx wrangler secret put BUNDESTAG_API_KEY
```

> **Without secrets** the Worker uses built-in mock speeches and deterministic reactions so the app is fully functional out of the box.

### 5 · Create the Cloudflare Pages project

```bash
cd frontend
npm install
npm run build           # output → frontend/dist

# Deploy and create the project in one step
npx wrangler pages deploy frontend/dist --project-name zwillingstag
```

Or connect your GitHub repository in the Cloudflare Dashboard → **Pages → Create a project → Connect to Git**.
Build settings:
| Setting | Value |
|---|---|
| Build command | `npm run build` |
| Build output directory | `frontend/dist` |
| Root directory | `frontend` |
| Environment variable `VITE_API_URL` | `https://zwillingstag-api.<account>.workers.dev` |
| Environment variable `VITE_WS_URL` | `wss://zwillingstag-api.<account>.workers.dev/ws` |

---

## GitHub Actions CI/CD (automated deployments)

The workflow `.github/workflows/deploy-cloudflare.yml` automatically deploys on every push to `main`.

### Required GitHub Secrets

Go to **Repository → Settings → Secrets and variables → Actions** and add:

| Secret | Description |
|---|---|
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token with *Edit Workers* + *Edit Pages* permissions |
| `CLOUDFLARE_ACCOUNT_ID` | Your Cloudflare Account ID (found in the dashboard right sidebar) |

### Optional GitHub Variables (override auto-detected Worker URL)

| Variable | Example |
|---|---|
| `WORKER_URL` | `https://zwillingstag-api.abc123.workers.dev` |
| `WORKER_WS_URL` | `wss://zwillingstag-api.abc123.workers.dev/ws` |

### Creating the Cloudflare API Token

1. Go to **Cloudflare Dashboard → Profile → API Tokens → Create Token**
2. Use the **Edit Cloudflare Workers** template
3. Add the **Cloudflare Pages** permission: `Account → Cloudflare Pages → Edit`
4. Copy the token and add it as the `CLOUDFLARE_API_TOKEN` secret in GitHub

---

## Local development with Wrangler

```bash
# Start the Worker locally (uses KV preview namespace)
cd cloudflare/worker
npx wrangler dev

# In a separate terminal, start the React dev server
cd frontend
VITE_API_URL=http://localhost:8787 VITE_WS_URL=ws://localhost:8787/ws npm run dev
```

The local Worker is accessible at `http://localhost:8787`.

---

## Workers KV – what's cached

| KV key pattern | Content | TTL |
|---|---|---|
| `members` | CDU/CSU member list with seat positions | 24 hours |
| `speeches` | Available Bundestag speeches | 6 hours |
| `speech:<id>` | Individual speech details | 6 hours |
| `protocol:<session_id>` | Parsed protocol speeches | 6 hours |
| `reactions:<speech_id>` | LLM-generated reactions (reused across sessions) | no expiry |

To clear all cached data:
```bash
# List keys
npx wrangler kv:key list --namespace-id=<id>
# Delete a key
npx wrangler kv:key delete --namespace-id=<id> members
```

---

## Durable Objects (WebSocket state)

The `SimulatorDO` Durable Object:
- Acts as a single global "debate room" (`idFromName("global")`)
- Manages all WebSocket client connections
- Persists the selected speech ID in Durable Object storage
- Generates and caches reactions via Workers KV
- Broadcasts state changes to all connected clients in real-time

> **Note:** Durable Objects require the **Workers Paid plan** ($5/month). Without the paid plan, the REST API endpoints still work correctly; only real-time WebSocket push will be unavailable.

---

## Environment variables reference

### Worker (`cloudflare/worker/wrangler.toml` / secrets)

| Variable | Type | Description |
|---|---|---|
| `OPENAI_API_KEY` | Secret | OpenAI API key for LLM reactions |
| `OPENAI_MODEL` | Var | Model to use (default: `gpt-4o-mini`) |
| `BUNDESTAG_API_KEY` | Secret | [Bundestag DIP API key](https://dip.bundestag.de/api/v1/) |

### Frontend build (`VITE_*`)

| Variable | Description |
|---|---|
| `VITE_API_URL` | Base URL of the Worker API (e.g. `https://zwillingstag-api.abc.workers.dev`) |
| `VITE_WS_URL` | WebSocket URL of the Worker (e.g. `wss://zwillingstag-api.abc.workers.dev/ws`) |

Leave both unset for local development (Vite proxy handles routing automatically).

---

## Custom domain setup (optional)

To serve both the frontend and API from the same domain (e.g. `zwillingstag.example.com`):

1. Add your domain to Cloudflare
2. In **Workers & Pages → zwillingstag-api → Triggers → Custom Domains**, add `api.example.com`
3. In **Pages → zwillingstag → Custom domains**, add `zwillingstag.example.com`
4. Update `VITE_API_URL=https://api.example.com` and `VITE_WS_URL=wss://api.example.com/ws`

With a shared apex domain you can also use a **Cloudflare Transform Rule** to route `/api/*` and `/ws` traffic from `zwillingstag.example.com` to the Worker, eliminating the need for `VITE_API_URL` entirely.
