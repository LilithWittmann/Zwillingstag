/**
 * SimulatorDO – Durable Object managing real-time simulation state.
 *
 * Responsibilities:
 *  - Holds the current speech selection and reactions in storage
 *  - Manages WebSocket connections and broadcasts state changes
 *  - Provides an internal HTTP API used by the main Worker to trigger
 *    speech selection and refresh actions
 */

import { Env, Member, Reaction, SimulationState, Speech } from './types';
import { BundestagAPI } from './bundestag';
import { LLMService } from './llm';
import { getStaticMembers } from './members';
import { generateMockReactions } from './mock-data';

const KV_KEY_CURRENT_SPEECH = 'do:current_speech_id';
const KV_KEY_REACTIONS = (id: string) => `reactions:${id}`;

export class SimulatorDO implements DurableObject {
  private state: DurableObjectState;
  private env: Env;

  // In-memory caches (reset on DO restart)
  private members: Member[] = [];
  private speeches: Speech[] = [];
  private currentSpeech: Speech | null = null;
  private reactions: Reaction[] = [];
  private initialized = false;

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  // ─── fetch entry-point ────────────────────────────────────────────────────

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    // WebSocket upgrade
    if (request.headers.get('Upgrade') === 'websocket') {
      return this._handleWebSocket(request);
    }

    // Internal REST-like API used by the main Worker
    if (url.pathname === '/internal/state') {
      await this._ensureInitialized();
      return this._jsonResponse(await this._buildState());
    }

    if (url.pathname === '/internal/select-speech' && request.method === 'POST') {
      const { speech_id } = (await request.json()) as { speech_id: string };
      await this._ensureInitialized();
      await this._selectSpeech(speech_id);
      await this._broadcast();
      return this._jsonResponse({ ok: true });
    }

    if (url.pathname === '/internal/refresh' && request.method === 'POST') {
      await this._refresh();
      await this._broadcast();
      return this._jsonResponse({ ok: true });
    }

    return new Response('Not Found', { status: 404 });
  }

  // ─── WebSocket handler ────────────────────────────────────────────────────

  private async _handleWebSocket(_request: Request): Promise<Response> {
    const { 0: client, 1: server } = new WebSocketPair();

    // Use the hibernation API so idle connections don't keep the DO warm
    this.state.acceptWebSocket(server);

    await this._ensureInitialized();
    server.send(JSON.stringify(await this._buildState()));

    return new Response(null, { status: 101, webSocket: client });
  }

  // Hibernation API handlers
  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer): Promise<void> {
    try {
      const msg = JSON.parse(String(message)) as { action: string; speech_id?: string };
      if (msg.action === 'select_speech' && msg.speech_id) {
        await this._ensureInitialized();
        await this._selectSpeech(msg.speech_id);
        await this._broadcast();
      } else if (msg.action === 'refresh') {
        await this._refresh();
        await this._broadcast();
      }
    } catch (e) {
      console.error('WS message error:', e);
    }
  }

  async webSocketClose(ws: WebSocket, code: number, reason: string): Promise<void> {
    ws.close(code, reason);
  }

  async webSocketError(ws: WebSocket, error: unknown): Promise<void> {
    console.error('WebSocket error:', error);
    ws.close(1011, 'Internal error');
  }

  // ─── Initialization ───────────────────────────────────────────────────────

  private async _ensureInitialized(): Promise<void> {
    if (this.initialized) return;
    this.initialized = true;

    const bundestag = new BundestagAPI(this.env.BUNDESTAG_API_KEY, this.env.KV_CACHE);
    const llm = new LLMService(
      this.env.OPENAI_API_KEY,
      this.env.OPENAI_MODEL ?? 'gpt-4o-mini',
    );

    // Load members
    const kvMembers = await this.env.KV_CACHE.get('members', 'json') as Member[] | null;
    this.members = kvMembers ?? getStaticMembers();

    // Load speeches
    const kvSpeeches = await this.env.KV_CACHE.get('speeches', 'json') as Speech[] | null;
    if (kvSpeeches && kvSpeeches.length > 0) {
      this.speeches = kvSpeeches;
    } else {
      this.speeches = await bundestag.getRecentSpeeches(20);
      if (this.speeches.length > 0) {
        await this.env.KV_CACHE.put('speeches', JSON.stringify(this.speeches), {
          expirationTtl: 6 * 3600,
        });
      }
    }

    // Restore or pick current speech
    const savedSpeechId = await this.state.storage.get<string>(KV_KEY_CURRENT_SPEECH);
    const target =
      (savedSpeechId && this.speeches.find((s) => s.id === savedSpeechId)) ??
      this.speeches[0] ??
      null;

    if (target) {
      this.currentSpeech = target;
      const cached = await this.env.KV_CACHE.get(KV_KEY_REACTIONS(target.id), 'json') as Reaction[] | null;
      this.reactions = cached ?? (await llm.generateReactions(target, this.members));
      if (!cached) {
        await this.env.KV_CACHE.put(KV_KEY_REACTIONS(target.id), JSON.stringify(this.reactions));
      }
    }
  }

  // ─── Speech management ────────────────────────────────────────────────────

  private async _selectSpeech(speechId: string): Promise<void> {
    const speech = this.speeches.find((s) => s.id === speechId) ?? null;
    if (!speech) return;

    this.currentSpeech = speech;
    await this.state.storage.put(KV_KEY_CURRENT_SPEECH, speechId);

    // Try KV cache first for reactions
    const cached = await this.env.KV_CACHE.get(KV_KEY_REACTIONS(speechId), 'json') as Reaction[] | null;
    if (cached) {
      this.reactions = cached;
      return;
    }

    const llm = new LLMService(
      this.env.OPENAI_API_KEY,
      this.env.OPENAI_MODEL ?? 'gpt-4o-mini',
    );
    this.reactions = await llm.generateReactions(speech, this.members);
    await this.env.KV_CACHE.put(KV_KEY_REACTIONS(speechId), JSON.stringify(this.reactions));
  }

  private async _refresh(): Promise<void> {
    this.initialized = false;
    this.speeches = [];
    this.currentSpeech = null;
    this.reactions = [];
    await this.env.KV_CACHE.delete('speeches');
    await this._ensureInitialized();
  }

  // ─── State + broadcast ────────────────────────────────────────────────────

  private async _buildState(): Promise<SimulationState> {
    return {
      current_speech: this.currentSpeech,
      reactions: this.reactions,
      available_speeches: this.speeches,
      is_live: false,
    };
  }

  private async _broadcast(): Promise<void> {
    const state = await this._buildState();
    const json = JSON.stringify(state);
    for (const ws of this.state.getWebSockets()) {
      try {
        ws.send(json);
      } catch {
        // ignore – connection already closed
      }
    }
  }

  // ─── Helpers ──────────────────────────────────────────────────────────────

  private _jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
