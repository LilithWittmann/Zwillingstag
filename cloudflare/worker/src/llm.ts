/**
 * LLM service – generates CDU/CSU reactions via OpenAI.
 * Uses native fetch (no SDK) for compatibility with Cloudflare Workers.
 * Falls back to deterministic mock reactions when no API key is provided.
 */

import { Member, Reaction, ReactionType, Speech } from './types';
import { generateMockReactions } from './mock-data';

const OPENAI_CHAT_URL = 'https://api.openai.com/v1/chat/completions';

function buildPrompt(speech: Speech, members: Member[]): string {
  const memberLines = members
    .map((m) => {
      const role = m.role ? ` | Funktion: ${m.role}` : '';
      const style = m.political_style ? ` | Stil: ${m.political_style.slice(0, 100)}` : '';
      return `- ID:${m.id} | ${m.name} (${m.party}, ${m.state})${role}${style}`;
    })
    .join('\n');

  return `Du simulierst CDU/CSU-Abgeordnete des deutschen Bundestags, die auf eine Rede reagieren.

REDE:
Redner: ${speech.speaker_name} (${speech.speaker_party ?? 'unbekannte Partei'})
Thema: ${speech.topic ?? 'allgemein'}
Text: ${speech.text.slice(0, 1500)}

CDU/CSU-ABGEORDNETE:
${memberLines}

Aufgabe: Generiere für JEDEN Abgeordneten eine realistische, charaktergerechte Reaktion.
Mögliche Reaktionstypen:
- "clap": Applaus (intensity 1-5, 5=stehend)
- "remark": Kurzer Zwischenruf / Bemerkung (max 80 Zeichen, auf Deutsch)
- "question": Zwischenfrage oder kritische Nachfrage (max 100 Zeichen, auf Deutsch)
- "silent": Keine sichtbare Reaktion

Berücksichtige: CDU/CSU ist Opposition – bei Regierungsreden eher kritisch/still/Zwischenrufe.

Gib NUR valides JSON zurück (kein Markdown), exakt dieses Format:
{"reactions": [{"member_id": "...", "reaction_type": "clap|remark|question|silent", "intensity": 1, "text": null}]}
`;
}

export class LLMService {
  constructor(
    private readonly apiKey: string | undefined,
    private readonly model: string,
  ) {}

  async generateReactions(speech: Speech, members: Member[]): Promise<Reaction[]> {
    if (!this.apiKey) {
      return generateMockReactions(members, speech);
    }

    try {
      const resp = await fetch(OPENAI_CHAT_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.apiKey}`,
        },
        body: JSON.stringify({
          model: this.model,
          messages: [
            {
              role: 'system',
              content:
                'Du bist ein präziser politischer Simulator. ' +
                'Antworte ausschließlich mit validem JSON, ohne Markdown-Formatierung.',
            },
            { role: 'user', content: buildPrompt(speech, members) },
          ],
          temperature: 0.8,
          max_tokens: 4000,
          response_format: { type: 'json_object' },
        }),
      });

      if (!resp.ok) {
        throw new Error(`OpenAI API error: ${resp.status} ${await resp.text()}`);
      }

      const data = (await resp.json()) as { choices: { message: { content: string } }[] };
      const raw = data.choices[0]?.message?.content ?? '{}';
      const parsed = JSON.parse(raw) as { reactions?: Record<string, unknown>[] };

      const memberIds = new Set(members.map((m) => m.id));
      const reactions: Reaction[] = [];
      for (const item of parsed.reactions ?? []) {
        const mid = item.member_id as string;
        if (!memberIds.has(mid)) continue;
        let rType: ReactionType;
        const rt = item.reaction_type as string;
        if (['clap', 'remark', 'question', 'silent'].includes(rt)) {
          rType = rt as ReactionType;
        } else {
          rType = 'silent';
        }
        reactions.push({
          member_id: mid,
          reaction_type: rType,
          intensity: Math.max(1, Math.min(5, Number(item.intensity ?? 1))),
          text: (item.text as string) ?? null,
        });
      }

      // Fill in silent for any missing members
      const reacted = new Set(reactions.map((r) => r.member_id));
      for (const m of members) {
        if (!reacted.has(m.id)) {
          reactions.push({ member_id: m.id, reaction_type: 'silent', intensity: 1, text: null });
        }
      }
      return reactions;
    } catch (e) {
      console.error('LLM call failed:', e);
      return generateMockReactions(members, speech);
    }
  }
}
