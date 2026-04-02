export interface Member {
  id: string;
  name: string;
  party: 'CDU' | 'CSU';
  state: string;
  role?: string | null;
  focus_areas: string[];
  political_style: string;
  seat_row: number;
  seat_col: number;
  mdb_id?: string | null;
  photo_url?: string | null;
  bio?: string | null;
}

export type ReactionType = 'clap' | 'remark' | 'question' | 'silent';

export interface Reaction {
  member_id: string;
  reaction_type: ReactionType;
  intensity: number;
  text?: string | null;
}

export interface Speech {
  id: string;
  speaker_name: string;
  speaker_party?: string | null;
  text: string;
  date: string;
  session_id?: string | null;
  session_title?: string | null;
  topic?: string | null;
}

export interface SimulationState {
  current_speech: Speech | null;
  reactions: Reaction[];
  available_speeches: Speech[];
  is_live: boolean;
}

export interface Env {
  KV_CACHE: KVNamespace;
  SIMULATOR: DurableObjectNamespace;
  OPENAI_API_KEY?: string;
  OPENAI_MODEL?: string;
  BUNDESTAG_API_KEY?: string;
}
