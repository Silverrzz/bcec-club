export type Id = number

export interface Engine {
  id: Id
  engine_id: Id
  name: string
  author?: string
  version: string
  binary_filename: string
  binary_sha256: string
  binary_size: number
  storage_key?: string
  uci_options: Record<string, string | number | boolean>
  active: boolean
  version_active?: boolean
  engine_active?: boolean
  created_at?: string
  storage_status?: 'ready' | 'missing' | 'corrupt'
}

export interface EngineFamily {
  id: Id
  name: string
  author?: string
  active: boolean
  versions: Engine[]
}

export interface Category {
  id: Id
  name: string
  description?: string
  active?: boolean
  default_config?: Partial<CategorySettings>
  created_at?: string
}

export interface OpeningSuite {
  id: Id
  name: string
  description?: string
  created_at?: string
}

export type TournamentFormat = 'round_robin' | 'swiss' | 'knockout' | 'gauntlet'
export type TimeControlCategory = 'increment' | 'movetime' | 'movestogo' | 'movenodes'

export type FormatOptions =
  | { games_per_pairing: number }
  | { rounds: number }
  | { games_per_match: number; tiebreak: 'armageddon' | 'extra_pair' }
  | { hero_engine_id: number; games_per_opponent: number }

export type TimeControl =
  | { category: 'increment'; initial_ms: number; increment_ms: number }
  | { category: 'movetime'; move_time_ms: number }
  | { category: 'movestogo'; initial_ms: number; moves_to_go: number }
  | { category: 'movenodes'; nodes: number }

export interface TournamentSettings {
  format: TournamentFormat
  format_options: FormatOptions
  time_control: TimeControl
  concurrency: number
  opening_suite_id: number | null
  adjudication: {
    draw?: unknown | null
    resign?: unknown | null
    syzygy?: unknown | null
    max_moves: number | null
  }
  rated: boolean
  lag_compensation_ms: number
}

export interface CategorySettings extends TournamentSettings {
  engine_threads: number
  engine_hash_mb: number
}

export interface TournamentConfig extends TournamentSettings {
  category_id: number | null
  category_settings_linked: boolean
  participants: number[]
  engine_threads: number
  engine_hash_mb: number
  uci_options: Record<string, Record<string, string | number | boolean>>
}

export interface Tournament {
  id: Id
  name: string
  category_id: number | null
  settings_unlinked?: boolean
  config: TournamentConfig
  status: string
  current_round?: number
  created_at?: string
  started_at?: string | null
  finished_at?: string | null
}

export interface Game {
  id: Id
  tournament_id: Id
  round: number
  white_engine_id: Id
  black_engine_id: Id
  status: string
  result?: string | null
  termination?: string | null
  started_at?: string | null
  finished_at?: string | null
}

export interface Worker {
  id: Id
  label: string
  status: string
  token_expires_at?: string | null
  session_id?: string | null
  app_commit?: string | null
  protocol_version?: number | null
  machine_id?: string | null
  pool_id?: number | null
  assigned_threads: number
  assigned_hash_mb: number
  last_seen?: string | null
  hw?: {
    cpu_model: string
    physical_cores: number
    logical_cores: number
    ram_gb: number
    ram_mb?: number | null
    gpu?: string | null
    os?: string
    python?: string
    bench?: { nps_probe?: number | null }
  } | null
}

export interface WorkerRow {
  worker: Worker
  status: string
  machine?: { status: string; label: string; detail: string }
  session?: { status: string; label: string; detail: string }
  token?: { status: string; label: string; detail: string }
  work?: { summary: string; detail?: string; meta?: string; href?: string | null }
}

export interface FormSeed {
  config?: TournamentConfig
  form_values?: Record<string, unknown>
  form_name?: string
  form_participants?: number[]
  form_category_id?: number | null
  form_linked?: boolean
  categories: Category[]
  category_defaults?: Record<string, Record<string, unknown>>
  engine_options: Engine[]
  opening_suites: OpeningSuite[]
  editing?: Tournament | boolean | null
}
