/**
 * Zwillingstag – Cloudflare Worker entry point.
 *
 * Routes:
 *   GET  /api/health              – health check
 *   GET  /api/members             – CDU/CSU members (KV-cached)
 *   GET  /api/sessions            – recent Bundestag sessions
 *   GET  /api/speeches            – available speeches (KV-cached)
 *   GET  /api/speeches/:id        – single speech by ID
 *   GET  /api/reactions/:id       – reactions for a speech (KV-cached, LLM-generated)
 *   GET  /api/state               – full simulation state (via Durable Object)
 *   WS   /ws                      – real-time WebSocket (via Durable Object)
 */

import { Env, Member, Reaction, Speech } from './types';
import { BundestagAPI } from './bundestag';
import { LLMService } from './llm';
import { getStaticMembers } from './members';

// Re-export the Durable Object so wrangler can pick it up
export { SimulatorDO } from './simulator-do';

// ─── CORS headers ─────────────────────────────────────────────────────────────

function corsHeaders(): HeadersInit {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders() },
  });
}

// ─── Singleton Durable Object stub ───────────────────────────────────────────

function getSimulator(env: Env) {
  const id = env.SIMULATOR.idFromName('global');
  return env.SIMULATOR.get(id);
}

// ─── Main fetch handler ───────────────────────────────────────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;

    // Preflight CORS
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    // ── WebSocket ──────────────────────────────────────────────────────────
    if (path === '/ws') {
      const upgradeHeader = request.headers.get('Upgrade');
      if (!upgradeHeader || upgradeHeader.toLowerCase() !== 'websocket') {
        return new Response('Expected WebSocket upgrade', { status: 426 });
      }
      return getSimulator(env).fetch(request);
    }

    // ── REST API ───────────────────────────────────────────────────────────
    if (path === '/api/health') {
      return jsonResponse({ status: 'ok' });
    }

    if (path === '/api/members') {
      const members = await getMembers(env);
      return jsonResponse(members);
    }

    if (path === '/api/sessions') {
      const bundestag = new BundestagAPI(env.BUNDESTAG_API_KEY, env.KV_CACHE);
      const sessions = await bundestag.getRecentSessions(10);
      return jsonResponse(sessions);
    }

    if (path === '/api/speeches') {
      const speeches = await getSpeeches(env);
      return jsonResponse(speeches);
    }

    const speechMatch = path.match(/^\/api\/speeches\/(.+)$/);
    if (speechMatch) {
      const speechId = decodeURIComponent(speechMatch[1]);
      const bundestag = new BundestagAPI(env.BUNDESTAG_API_KEY, env.KV_CACHE);
      const speech = await bundestag.getSpeech(speechId);
      if (!speech) return jsonResponse({ detail: 'Speech not found' }, 404);
      return jsonResponse(speech);
    }

    const reactionsMatch = path.match(/^\/api\/reactions\/(.+)$/);
    if (reactionsMatch) {
      const speechId = decodeURIComponent(reactionsMatch[1]);
      const reactions = await getReactions(speechId, env);
      return jsonResponse(reactions);
    }

    if (path === '/api/state') {
      // Delegate to the Durable Object for consistent state
      const doResp = await getSimulator(env).fetch(
        new Request('http://internal/internal/state', { method: 'GET' }),
      );
      const state = await doResp.json();
      return jsonResponse(state);
    }

    return jsonResponse({ detail: 'Not found' }, 404);
  },
};

// ─── Helper functions ─────────────────────────────────────────────────────────

async function getMembers(env: Env): Promise<Member[]> {
  const cached = (await env.KV_CACHE.get('members', 'json')) as Member[] | null;
  if (cached && cached.length > 0) return cached;

  const bundestag = new BundestagAPI(env.BUNDESTAG_API_KEY, env.KV_CACHE);
  if (env.BUNDESTAG_API_KEY) {
    const live = await bundestag.getMembers();
    if (live.length > 0) return live;
  }
  return getStaticMembers();
}

async function getSpeeches(env: Env): Promise<Speech[]> {
  const cached = (await env.KV_CACHE.get('speeches', 'json')) as Speech[] | null;
  if (cached && cached.length > 0) return cached;

  const bundestag = new BundestagAPI(env.BUNDESTAG_API_KEY, env.KV_CACHE);
  const speeches = await bundestag.getRecentSpeeches(20);
  if (speeches.length > 0) {
    await env.KV_CACHE.put('speeches', JSON.stringify(speeches), { expirationTtl: 6 * 3600 });
  }
  return speeches;
}

async function getReactions(speechId: string, env: Env): Promise<Reaction[]> {
  const cacheKey = `reactions:${speechId}`;

  // Check KV cache
  const cached = (await env.KV_CACHE.get(cacheKey, 'json')) as Reaction[] | null;
  if (cached) return cached;

  // Find speech
  const bundestag = new BundestagAPI(env.BUNDESTAG_API_KEY, env.KV_CACHE);
  const speech = await bundestag.getSpeech(speechId);
  if (!speech) return [];

  // Get members
  const members = await getMembers(env);

  // Generate reactions
  const llm = new LLMService(env.OPENAI_API_KEY, env.OPENAI_MODEL ?? 'gpt-4o-mini');
  const reactions = await llm.generateReactions(speech, members);

  // Cache in KV (no TTL – reactions are deterministic per speech)
  await env.KV_CACHE.put(cacheKey, JSON.stringify(reactions));

  return reactions;
}
