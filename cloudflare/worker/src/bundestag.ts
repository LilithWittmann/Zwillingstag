/**
 * Bundestag DIP API + Plenarprotokoll XML integration for Cloudflare Workers.
 *
 * Uses Workers KV for caching (6 h for protocols, 24 h for member data).
 * Falls back to mock data when BUNDESTAG_API_KEY is not configured.
 */

import { Member, Speech } from './types';
import { MOCK_SPEECHES, MOCK_SESSIONS } from './mock-data';
import { assignSeats } from './members';

const DIP_API_BASE = 'https://search.dip.bundestag.de/api/v1';
const MDB_INDEX_URL = 'https://www.bundestag.de/xml/v2/mdb/index.xml';

const CACHE_TTL_SPEECHES = 6 * 3600;   // 6 hours
const CACHE_TTL_MEMBERS = 24 * 3600;   // 24 hours
const PROTOCOLS_TO_LOAD = 3;
const TOPIC_MIN_LEN = 10;
const TOPIC_MAX_LEN = 120;

// ─── XML parsing helpers ──────────────────────────────────────────────────────

/**
 * Remove all XML/HTML markup from a string.
 * Passes the input through the tag-stripping regex repeatedly until no tags
 * remain, preventing incomplete removal of edge-case patterns.
 */
function stripAllTags(s: string): string {
  let result = s;
  let prev = '';
  while (result !== prev) {
    prev = result;
    result = result.replace(/<[^>]*>/g, ' ');
  }
  return result.replace(/&[a-z#0-9]+;/gi, ' ').replace(/\s+/g, ' ').trim();
}

function xmlText(tag: string, xml: string): string {
  const m = xml.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i'));
  return m ? stripAllTags(m[1]) : '';
}

function stripHtml(s: string): string {
  return stripAllTags(s);
}

function normalizeDate(dateStr: string): string {
  if (!dateStr) return new Date().toISOString().slice(0, 10);
  // DD.MM.YYYY → YYYY-MM-DD
  const m = dateStr.match(/^(\d{2})\.(\d{2})\.(\d{4})/);
  if (m) return `${m[3]}-${m[2]}-${m[1]}`;
  return dateStr.slice(0, 10);
}

function nameToId(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue')
    .replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '');
}

// ─── Plenarprotokoll XML parser ───────────────────────────────────────────────

interface RedeBlock {
  id: string;
  speaker_name: string;
  speaker_party: string;
  text: string;
  topic: string;
}

/**
 * Parse a Bundestag Plenarprotokoll XML string and return speech blocks.
 * The XML structure: <dbtplenarprotokoll><sitzungsverlauf><tagesordnungspunkt ...>
 *   <rede id="..."><p klasse="redner"><redner>...</redner></p><p>text</p></rede>
 * </tagesordnungspunkt></sitzungsverlauf></dbtplenarprotokoll>
 */
function parsePlenarprotokoll(xml: string): RedeBlock[] {
  const speeches: RedeBlock[] = [];

  // Extract sitzungsverlauf block
  const svMatch = xml.match(/<sitzungsverlauf>([\s\S]*?)<\/sitzungsverlauf>/i);
  if (!svMatch) return speeches;
  const sv = svMatch[1];

  // Split into Tagesordnungspunkte
  const tops = sv.split(/<tagesordnungspunkt /i);
  for (const topChunk of tops.slice(1)) {
    // Extract topic title
    let topic = '';
    const boldMatch = topChunk.match(/<p klasse="T_fett"[^>]*>([\s\S]*?)<\/p>/i);
    if (boldMatch) {
      topic = stripAllTags(boldMatch[1]).replace(/\s+/g, ' ');
      if (topic.length < TOPIC_MIN_LEN) topic = '';
      else if (topic.length > TOPIC_MAX_LEN) topic = topic.slice(0, TOPIC_MAX_LEN);
    }
    if (!topic) {
      const nasMatch = topChunk.match(/<p klasse="T_NaS"[^>]*>([\s\S]*?)<\/p>/i);
      if (nasMatch) {
        topic = stripAllTags(nasMatch[1]);
        if (topic.length < TOPIC_MIN_LEN) topic = '';
      }
    }
    if (!topic) {
      const topId = topChunk.match(/top-id="([^"]+)"/i);
      topic = topId ? topId[1] : '';
    }

    // Extract Reden within this TOP
    const redeBlocks = topChunk.split(/<rede /i);
    for (const redeChunk of redeBlocks.slice(1)) {
      const redeIdMatch = redeChunk.match(/^id="([^"]+)"/i);
      if (!redeIdMatch) continue;
      const redeId = redeIdMatch[1];

      // Speaker info from <redner>
      let speakerName = 'Unbekannt';
      let speakerParty = '';
      const rednerMatch = redeChunk.match(/<redner>([\s\S]*?)<\/redner>/i);
      if (rednerMatch) {
        const vorname = xmlText('vorname', rednerMatch[1]);
        const nachname = xmlText('nachname', rednerMatch[1]);
        const fraktion = xmlText('fraktion', rednerMatch[1]);
        speakerName = `${vorname} ${nachname}`.trim() || 'Unbekannt';
        speakerParty = fraktion;
      }

      // Speech text: all <p> blocks except klasse="redner"
      const textParts: string[] = [];
      const pMatches = redeChunk.matchAll(/<p(?:\s+[^>]*)?>[\s\S]*?<\/p>/gi);
      for (const pm of pMatches) {
        const pTag = pm[0];
        if (/klasse="redner"/i.test(pTag)) continue;
        const inner = stripAllTags(pTag);
        if (inner) textParts.push(inner);
      }
      const fullText = textParts.join(' ');
      if (!fullText) continue;

      speeches.push({
        id: redeId,
        speaker_name: speakerName,
        speaker_party: speakerParty,
        text: fullText,
        topic,
      });
    }
  }
  return speeches;
}

// ─── MdB XML index parser ─────────────────────────────────────────────────────

interface BasicMdb {
  mdb_id: string;
  name: string;
  state: string;
  photo_url: string;
  info_xml_url: string;
  party: string;
}

function parseMdbIndex(xml: string): BasicMdb[] {
  const members: BasicMdb[] = [];
  const mdbMatches = xml.matchAll(/<mdb(?:\s[^>]*)?>([\s\S]*?)<\/mdb>/gi);
  for (const mm of mdbMatches) {
    const block = mm[1];
    const fraktion = (mm[0].match(/fraktion="([^"]+)"/i)?.[1] ?? '').toUpperCase();
    if (!fraktion.includes('CDU') && !fraktion.includes('CSU')) continue;

    const mdbIdEl = block.match(/<mdbID[^>]*status="([^"]*)"[^>]*>(.*?)<\/mdbID>/i);
    if (!mdbIdEl || mdbIdEl[1] !== 'Aktiv') continue;
    const mdbId = mdbIdEl[2].trim();

    // Name: "LastName, FirstName"
    const rawName = xmlText('mdbName', block);
    const parts = rawName.split(', ');
    const fullName = parts.length === 2 ? `${parts[1]} ${parts[0]}`.trim() : rawName;

    const photoGross = xmlText('mdbFotoGrossURL', block);
    const photo = xmlText('mdbFotoURL', block);
    const infoUrl = xmlText('mdbInfoXMLURL', block);
    const land = xmlText('mdbLand', block);

    members.push({
      mdb_id: mdbId,
      name: fullName,
      state: land,
      photo_url: photoGross || photo,
      info_xml_url: infoUrl,
      party: fraktion.includes('CSU') ? 'CSU' : 'CDU',
    });
  }
  return members;
}

// ─── BundestagAPI ─────────────────────────────────────────────────────────────

export class BundestagAPI {
  constructor(
    private readonly apiKey: string | undefined,
    private readonly kv: KVNamespace,
  ) {}

  // ── Public interface ──────────────────────────────────────────────────────

  async getRecentSpeeches(limit = 20): Promise<Speech[]> {
    if (!this.apiKey) return MOCK_SPEECHES;
    try {
      return (await this._loadRecentSpeeches(limit)).slice(0, limit);
    } catch (e) {
      console.error('getRecentSpeeches error:', e);
      return MOCK_SPEECHES;
    }
  }

  async getSpeech(speechId: string): Promise<Speech | null> {
    if (!this.apiKey) {
      return MOCK_SPEECHES.find((s) => s.id === speechId) ?? null;
    }
    const cached = await this.kv.get(`speech:${speechId}`, 'json') as Speech | null;
    if (cached) return cached;
    // Attempt to populate index by loading recent speeches
    await this._loadRecentSpeeches();
    return (await this.kv.get(`speech:${speechId}`, 'json')) as Speech | null;
  }

  async getRecentSessions(limit = 10): Promise<unknown[]> {
    if (!this.apiKey) return MOCK_SESSIONS;
    try {
      const protocols = await this._fetchProtocolList(limit);
      return protocols.map((p) => ({
        id: String(p.id),
        title: p.titel,
        date: p.datum,
        session_number: p.dokumentnummer ?? '',
      }));
    } catch (e) {
      console.error('getRecentSessions error:', e);
      return MOCK_SESSIONS;
    }
  }

  async getMembers(): Promise<Member[]> {
    // Try KV cache first
    const cached = await this.kv.get('members', 'json') as Member[] | null;
    if (cached && cached.length > 0) return cached;

    try {
      const resp = await fetch(MDB_INDEX_URL, {
        headers: { 'User-Agent': 'Zwillingstag/1.0 (research project)' },
      });
      if (!resp.ok) throw new Error(`MdB index fetch failed: ${resp.status}`);
      const xml = await resp.text();
      const basic = parseMdbIndex(xml);
      const members = assignSeats(
        basic.map((b) => ({
          id: nameToId(b.name),
          mdb_id: b.mdb_id,
          name: b.name,
          party: b.party as 'CDU' | 'CSU',
          state: b.state,
          role: null,
          focus_areas: [],
          political_style: `${b.party}-Mitglied, ${b.party === 'CSU' ? 'konservativ-bayerisch' : 'christdemokratisch-konservativ'}`,
          photo_url: b.photo_url || null,
          bio: null,
        })),
      );
      // Cache for 24 h
      await this.kv.put('members', JSON.stringify(members), { expirationTtl: CACHE_TTL_MEMBERS });
      return members;
    } catch (e) {
      console.error('getMembers error:', e);
      return [];
    }
  }

  // ── Internal ──────────────────────────────────────────────────────────────

  private async _fetchProtocolList(limit = 10): Promise<Record<string, unknown>[]> {
    const url = new URL(`${DIP_API_BASE}/plenarprotokoll/`);
    url.searchParams.set('apikey', this.apiKey!);
    url.searchParams.set('format', 'json');
    url.searchParams.set('f.herausgeber', 'BT');
    url.searchParams.set('num', String(limit * 2));

    const resp = await fetch(url.toString(), {
      headers: { 'User-Agent': 'Zwillingstag/1.0 (research project)' },
    });
    if (!resp.ok) throw new Error(`DIP API error: ${resp.status}`);
    const data = await resp.json() as { documents?: Record<string, unknown>[] };

    const result: Record<string, unknown>[] = [];
    for (const doc of data.documents ?? []) {
      if (doc.herausgeber !== 'BT') continue;
      const xmlUrl = (doc.fundstelle as Record<string, unknown>)?.xml_url;
      if (xmlUrl) result.push(doc);
      if (result.length >= limit) break;
    }
    return result;
  }

  private async _loadRecentSpeeches(limit = 40): Promise<Speech[]> {
    const protocols = await this._fetchProtocolList(PROTOCOLS_TO_LOAD);
    const all: Speech[] = [];

    for (const proto of protocols) {
      const fundstelle = proto.fundstelle as Record<string, unknown>;
      const xmlUrl = fundstelle.xml_url as string;
      const sessionId = String(proto.id);
      const sessionTitle = proto.titel as string;
      const dateStr = proto.datum as string;

      const speeches = await this._getOrParseProtocol(xmlUrl, sessionId, sessionTitle, dateStr);
      for (const s of speeches) {
        all.push(s);
        // Store individual speech in KV for fast lookup by ID
        await this.kv.put(`speech:${s.id}`, JSON.stringify(s), { expirationTtl: CACHE_TTL_SPEECHES });
      }
    }
    return all;
  }

  private async _getOrParseProtocol(
    xmlUrl: string,
    sessionId: string,
    sessionTitle: string,
    dateStr: string,
  ): Promise<Speech[]> {
    const cacheKey = `protocol:${sessionId}`;
    const cached = await this.kv.get(cacheKey, 'json') as Speech[] | null;
    if (cached) return cached;

    try {
      const resp = await fetch(xmlUrl, {
        headers: { 'User-Agent': 'Zwillingstag/1.0 (research project)' },
      });
      if (!resp.ok) throw new Error(`Protocol fetch failed: ${resp.status}`);
      const xml = await resp.text();
      const reden = parsePlenarprotokoll(xml);
      const speeches: Speech[] = reden.map((r) => ({
        id: `${sessionId}:${r.id}`,
        speaker_name: r.speaker_name,
        speaker_party: r.speaker_party || null,
        text: r.text,
        date: normalizeDate(dateStr),
        session_id: sessionId,
        session_title: sessionTitle,
        topic: r.topic || null,
      }));

      await this.kv.put(cacheKey, JSON.stringify(speeches), { expirationTtl: CACHE_TTL_SPEECHES });
      return speeches;
    } catch (e) {
      console.error(`Failed to fetch/parse protocol ${xmlUrl}:`, e);
      return [];
    }
  }
}
