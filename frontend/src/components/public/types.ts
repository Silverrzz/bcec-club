export type Identifier = number | string

export interface TournamentConfig {
  participants?: Identifier[]
  format?: string | { value?: string }
  time_control?: Record<string, unknown>
  [key: string]: unknown
}

export interface TournamentRecord {
  id: Identifier
  name: string
  category_id?: Identifier | null
  status: string
  current_round?: number
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
  config?: TournamentConfig
}

export interface GameRecord {
  id: Identifier
  tournament_id: Identifier
  round?: number
  pair_index?: number
  white_engine_id: Identifier
  black_engine_id: Identifier
  white_name?: string
  black_name?: string
  status: string
  result?: string | null
  termination?: string | null
  pgn?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface MoveRecord {
  game_id?: Identifier
  ply: number
  uci: string
  san?: string
  is_book?: boolean
  eval_cp?: number | null
  eval_mate?: number | null
  depth?: number | null
  nodes?: number | null
  nps?: number | null
  pv?: string | null
  info_line?: string | null
  time_ms?: number | null
  clock_after_ms?: number | null
}

export interface OpeningRecord {
  name: string
  fen: string
}

export interface EngineRecord {
  id?: Identifier
  engine_id?: Identifier
  name: string
  author?: string | null
  version?: string | null
  git_url?: string | null
  branch?: string | null
  commit?: string | null
  build_cmd?: string | null
  binary_path?: string | null
  uci_options?: Record<string, unknown>
  active?: boolean
}

export interface GameSummary {
  total: number
  pending?: number
  assigned?: number
  live?: number
  finished?: number
  abandoned?: number
}

export interface TournamentSummary {
  record: TournamentRecord
  summary: GameSummary
  participant_names?: string[]
  participant_preview?: string[]
  participant_overflow?: number
  participant_count?: number
  progress_percent?: number
  time_control?: string
  format?: string
}

export interface StandingRecord {
  engine_id: Identifier
  name: string
  points: number
  played: number
  buchholz?: number
  bye_points?: number
  stage?: number
}

export interface EngineAnalysis {
  depth?: string | number | null
  nodes?: string | number | null
  nps?: string | number | null
  eval?: string | number | null
  info?: string | null
  pv?: string | null
  root_fen?: string | null
}

export interface ClockState {
  game_id?: Identifier
  active_side?: 'white' | 'black' | null
  running?: boolean
  clocks_ms?: Partial<Record<'white' | 'black', number | null>>
  sent_at?: string
  observed_at?: string | null
}

export interface ChatMessage {
  id?: Identifier
  tournament_id?: Identifier
  display_name: string
  text: string
  at?: string
}

export interface ChatSettings {
  enabled?: boolean
  slowmode_seconds?: number
  max_message_length?: number
  allow_anonymous_names?: boolean
}

export interface HardwareRecord {
  engine_id: Identifier
  name: string
  hash?: string
  threads?: string
  hardware?: string
}

export interface TournamentDetailResponse {
  tournament: TournamentRecord
  games: GameRecord[]
  engines: Record<string, string>
  viewer_game: GameRecord | null
  viewer_moves: MoveRecord[]
  viewer_locked?: boolean
  engine_data?: Partial<Record<'white' | 'black', EngineAnalysis>>
  clocks?: Partial<Record<'white' | 'black', string>>
  clock_state?: ClockState | null
  standings?: StandingRecord[]
  settings?: Array<{ label: string; value: string } | [string, string]>
  engine_hardware?: HardwareRecord[]
  chat_messages?: ChatMessage[]
  chat_settings?: ChatSettings
  opening?: OpeningRecord | null
}

export interface LiveSnapshot {
  tournament?: Partial<TournamentRecord>
  game?: GameRecord | null
  opening?: OpeningRecord | null
  moves?: MoveRecord[]
  engine_data?: Partial<Record<'white' | 'black', EngineAnalysis>>
  clocks?: Partial<Record<'white' | 'black', string>>
  clock_state?: ClockState | null
  standings?: StandingRecord[]
  games?: GameRecord[]
}

export interface StreamEnvelope<T = Record<string, unknown>> {
  type: string
  sent_at?: string
  data: T
}
