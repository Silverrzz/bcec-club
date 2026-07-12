import type {
  FormSeed,
  CategorySettings,
  TimeControl,
  TournamentConfig,
  TournamentFormat,
  TournamentSettings,
} from './types'

export function cloneData<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

export function humanize(value: string | null | undefined): string {
  if (!value) return 'Unknown'
  return value.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return 'Never'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function formatNumber(value: number | null | undefined): string {
  return new Intl.NumberFormat().format(value ?? 0)
}

export function formatTimeControl(control: TimeControl | undefined): string {
  if (!control) return 'Not set'
  if (control.category === 'increment') {
    return `${formatSeconds(control.initial_ms)} + ${formatSeconds(control.increment_ms)}`
  }
  if (control.category === 'movetime') return `${formatSeconds(control.move_time_ms)} per move`
  if (control.category === 'movestogo') {
    return `${formatSeconds(control.initial_ms)} / ${control.moves_to_go} moves`
  }
  return `${formatNumber(control.nodes)} nodes per move`
}

function formatSeconds(milliseconds: number): string {
  const seconds = milliseconds / 1000
  if (seconds >= 60 && seconds % 60 === 0) return `${seconds / 60} min`
  return `${seconds.toLocaleString()} sec`
}

export function defaultSettings(): TournamentSettings {
  return {
    format: 'round_robin',
    format_options: { games_per_pairing: 2 },
    time_control: { category: 'increment', initial_ms: 60_000, increment_ms: 1_000 },
    concurrency: 1,
    opening_suite_id: null,
    adjudication: { max_moves: null },
    rated: true,
    lag_compensation_ms: 50,
  }
}

export function defaultCategorySettings(): CategorySettings {
  return {
    ...defaultSettings(),
    engine_threads: 1,
    engine_hash_mb: 16,
  }
}

function positiveInt(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

function nonNegativeNumber(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback
}

function nonNegativeInt(value: unknown, fallback: number): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : fallback
}

function bool(value: unknown, fallback: boolean): boolean {
  if (typeof value === 'boolean') return value
  if (value === 'true' || value === 'on' || value === '1') return true
  if (value === 'false' || value === '0' || value === '') return false
  return fallback
}

export function settingsFromFlat(values: Record<string, unknown> = {}): TournamentSettings {
  const settings = defaultSettings()
  const format = (values.format as TournamentFormat | undefined) ?? settings.format
  settings.format = format

  if (format === 'swiss') {
    settings.format_options = { rounds: positiveInt(values.swiss_rounds, 7) }
  } else if (format === 'knockout') {
    settings.format_options = {
      games_per_match: positiveInt(values.knockout_games_per_match, 2),
      tiebreak: values.knockout_tiebreak === 'extra_pair' ? 'extra_pair' : 'armageddon',
    }
  } else if (format === 'gauntlet') {
    settings.format_options = {
      hero_engine_id: positiveInt(values.gauntlet_hero_engine_id, 0),
      games_per_opponent: positiveInt(values.gauntlet_games_per_opponent, 2),
    }
  } else {
    settings.format_options = { games_per_pairing: positiveInt(values.round_robin_games_per_pairing, 2) }
  }

  const category = values.tc_type ?? values.time_control_category ?? 'increment'
  if (category === 'movetime') {
    settings.time_control = {
      category: 'movetime',
      move_time_ms: Math.round(nonNegativeNumber(values.tc_move_time_s, 1) * 1000),
    }
  } else if (category === 'movestogo') {
    settings.time_control = {
      category: 'movestogo',
      initial_ms: Math.round(nonNegativeNumber(values.tc_initial_s, 60) * 1000),
      moves_to_go: positiveInt(values.tc_moves_to_go, 40),
    }
  } else if (category === 'movenodes') {
    settings.time_control = {
      category: 'movenodes',
      nodes: positiveInt(values.tc_nodes, 100_000),
    }
  } else {
    settings.time_control = {
      category: 'increment',
      initial_ms: Math.round(nonNegativeNumber(values.tc_initial_s, 60) * 1000),
      increment_ms: Math.round(nonNegativeNumber(values.tc_increment_s, 1) * 1000),
    }
  }

  settings.opening_suite_id = positiveInt(values.opening_suite_id, 0) || null
  settings.concurrency = positiveInt(values.concurrency, 1)
  settings.rated = bool(values.rated, true)
  settings.lag_compensation_ms = nonNegativeNumber(values.lag_compensation_ms, 50)
  settings.adjudication = {
    draw: bool(values.adjudication_draw, false)
      ? {
          min_fullmove: positiveInt(values.draw_min_fullmove, 40),
          max_abs_cp: nonNegativeInt(values.draw_max_abs_cp, 10),
          consecutive_plies: positiveInt(values.draw_plies, 8),
        }
      : null,
    resign: bool(values.adjudication_resign, false)
      ? {
          min_abs_cp: positiveInt(values.resign_min_abs_cp, 800),
          consecutive_plies: positiveInt(values.resign_plies, 6),
        }
      : null,
    syzygy: bool(values.adjudication_syzygy, false)
      ? { max_pieces: positiveInt(values.syzygy_max_pieces, 6) }
      : null,
    max_moves: positiveInt(values.adjudication_max_moves, 0) || null,
  }
  return settings
}

export function normalizeSettings(value: Partial<TournamentSettings> | undefined): TournamentSettings {
  const defaults = defaultSettings()
  if (!value || !value.format || !value.time_control) return defaults
  return {
    ...defaults,
    ...cloneData(value),
    adjudication: {
      ...cloneData(value.adjudication ?? {}),
      max_moves: value.adjudication?.max_moves ?? null,
    },
    lag_compensation_ms: value.lag_compensation_ms ?? 50,
  } as TournamentSettings
}

export function normalizeCategorySettings(value: Partial<CategorySettings> | undefined): CategorySettings {
  const settings = normalizeSettings(value)
  return {
    ...settings,
    engine_threads: positiveInt(value?.engine_threads, 1),
    engine_hash_mb: positiveInt(value?.engine_hash_mb, 16),
  }
}

export function configFromSeed(seed: FormSeed): TournamentConfig {
  if (seed.config) return normalizeConfig(seed.config)
  const editing = typeof seed.editing === 'object' && seed.editing ? seed.editing : null
  if (editing?.config) return normalizeConfig(editing.config)

  const categoryId = seed.form_category_id !== undefined
    ? seed.form_category_id
    : seed.categories[0]?.id ?? null
  return {
    ...settingsFromFlat(seed.form_values),
    category_id: categoryId,
    category_settings_linked: seed.form_linked ?? seed.categories.length > 0,
    participants: [...(seed.form_participants ?? [])],
    engine_threads: 1,
    engine_hash_mb: 16,
    uci_options: {},
  }
}

function normalizeConfig(config: Partial<TournamentConfig>): TournamentConfig {
  return {
    ...config,
    engine_threads: positiveInt(config.engine_threads, 1),
    engine_hash_mb: positiveInt(config.engine_hash_mb, 16),
    uci_options: config.uci_options ?? {},
  } as TournamentConfig
}

export function estimateGames(format: TournamentFormat, options: TournamentSettings['format_options'], players: number): number {
  if (players < 2) return 0
  if (format === 'round_robin') {
    const pairs = (players * (players - 1)) / 2
    return pairs * ('games_per_pairing' in options ? options.games_per_pairing : 0)
  }
  if (format === 'swiss') {
    return Math.floor(players / 2) * ('rounds' in options ? options.rounds : 0)
  }
  if (format === 'knockout') {
    return (players - 1) * ('games_per_match' in options ? options.games_per_match : 0)
  }
  return (players - 1) * ('games_per_opponent' in options ? options.games_per_opponent : 0)
}

export function errorText(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  if (error && typeof error === 'object' && 'detail' in error) {
    const detail = (error as { detail: unknown }).detail
    return Array.isArray(detail) ? detail.join(' ') : String(detail)
  }
  return 'Something went wrong. Please try again.'
}
