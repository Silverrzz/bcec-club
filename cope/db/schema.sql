CREATE TABLE IF NOT EXISTS schema_metadata (
  key TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'engines' AND column_name = 'git_url') THEN
    RAISE EXCEPTION 'legacy source-built engine schema is unsupported; create a fresh database for schema 4';
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS engines (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  author TEXT NOT NULL DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS engine_versions (
  id BIGSERIAL PRIMARY KEY,
  engine_id BIGINT NOT NULL REFERENCES engines(id) ON DELETE CASCADE,
  version TEXT NOT NULL,
  binary_filename TEXT NOT NULL,
  binary_sha256 TEXT NOT NULL CHECK (binary_sha256 ~ '^[0-9a-f]{64}$'),
  binary_size BIGINT NOT NULL CHECK (binary_size > 0),
  storage_key TEXT NOT NULL CHECK (storage_key ~ '^[0-9a-f]{64}$'),
  uci_options TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  created_at TEXT NOT NULL,
  UNIQUE (engine_id, version)
);

CREATE TABLE IF NOT EXISTS categories (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  default_config TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  created_at TEXT NOT NULL
);

INSERT INTO categories (name, description, default_config, created_at)
VALUES (
  'Default',
  'General rating list and tournament defaults.',
  '{}',
  '1970-01-01T00:00:00+00:00'
) ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS tournaments (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  category_id BIGINT REFERENCES categories(id),
  settings_unlinked INTEGER NOT NULL DEFAULT 0 CHECK (settings_unlinked IN (0, 1)),
  config TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'scheduled', 'running', 'paused', 'finished', 'aborted')),
  current_round INTEGER NOT NULL DEFAULT 0,
  worker_profile TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS participants (
  tournament_id BIGINT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
  engine_id BIGINT NOT NULL REFERENCES engine_versions(id),
  seed INTEGER NOT NULL,
  PRIMARY KEY (tournament_id, engine_id),
  UNIQUE (tournament_id, seed)
);

CREATE TABLE IF NOT EXISTS tournament_matches (
  id BIGSERIAL PRIMARY KEY,
  tournament_id BIGINT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
  round INTEGER NOT NULL,
  match_index INTEGER NOT NULL,
  engine1_id BIGINT NOT NULL REFERENCES engine_versions(id),
  engine2_id BIGINT REFERENCES engine_versions(id),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'finished', 'bye')),
  winner_engine_id BIGINT REFERENCES engine_versions(id),
  UNIQUE (tournament_id, round, match_index)
);

CREATE TABLE IF NOT EXISTS games (
  id BIGSERIAL PRIMARY KEY,
  tournament_id BIGINT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
  round INTEGER NOT NULL,
  pair_index INTEGER NOT NULL,
  white_engine_id BIGINT NOT NULL REFERENCES engine_versions(id),
  black_engine_id BIGINT NOT NULL REFERENCES engine_versions(id),
  match_id BIGINT REFERENCES tournament_matches(id) ON DELETE SET NULL,
  game_number INTEGER NOT NULL DEFAULT 1,
  tiebreak_kind TEXT CHECK (tiebreak_kind IS NULL OR tiebreak_kind IN ('extra_pair', 'armageddon')),
  opening_id BIGINT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'assigned', 'live', 'finished', 'abandoned')),
  result TEXT CHECK (result IS NULL OR result IN ('1-0', '0-1', '1/2-1/2')),
  termination TEXT,
  pgn TEXT,
  white_hw TEXT,
  black_hw TEXT,
  started_at TEXT,
  finished_at TEXT,
  UNIQUE (tournament_id, round, pair_index, white_engine_id, black_engine_id)
);

CREATE TABLE IF NOT EXISTS worker_pools (
  id BIGSERIAL PRIMARY KEY,
  label TEXT NOT NULL,
  enrollment_token_hash TEXT,
  enrollment_expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'enrolled', 'revoked')),
  machine_id TEXT,
  slot_count INTEGER NOT NULL CHECK (slot_count > 0),
  assigned_threads INTEGER NOT NULL CHECK (assigned_threads > 0),
  assigned_hash_mb INTEGER NOT NULL CHECK (assigned_hash_mb > 0),
  created_at TEXT NOT NULL,
  enrolled_at TEXT
);

CREATE TABLE IF NOT EXISTS workers (
  id BIGSERIAL PRIMARY KEY,
  label TEXT NOT NULL,
  token_hash TEXT,
  token_expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'minted'
    CHECK (status IN ('minted', 'connected', 'downloading', 'ready', 'busy', 'offline', 'revoked')),
  session_id TEXT,
  app_commit TEXT,
  protocol_version INTEGER,
  machine_id TEXT,
  pool_id BIGINT REFERENCES worker_pools(id) ON DELETE SET NULL,
  pool_slot_token_hash TEXT,
  assigned_threads INTEGER NOT NULL DEFAULT 1 CHECK (assigned_threads > 0),
  assigned_hash_mb INTEGER NOT NULL DEFAULT 32 CHECK (assigned_hash_mb > 0),
  hw TEXT,
  last_seen TEXT
);

CREATE TABLE IF NOT EXISTS game_assignments (
  id BIGSERIAL PRIMARY KEY,
  game_id BIGINT NOT NULL UNIQUE REFERENCES games(id) ON DELETE CASCADE,
  assignment_key TEXT NOT NULL UNIQUE,
  worker_id BIGINT REFERENCES workers(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'assigned'
    CHECK (status IN ('assigned', 'acked', 'live', 'finished', 'abandoned', 'expired')),
  sent_at TEXT,
  acked_at TEXT,
  finished_at TEXT,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS worker_failures (
  id BIGSERIAL PRIMARY KEY,
  worker_id BIGINT REFERENCES workers(id) ON DELETE SET NULL,
  worker_label TEXT NOT NULL,
  pool_id BIGINT REFERENCES worker_pools(id) ON DELETE SET NULL,
  machine_id TEXT,
  assignment_id BIGINT REFERENCES game_assignments(id) ON DELETE SET NULL,
  game_id BIGINT REFERENCES games(id) ON DELETE SET NULL,
  engine_id BIGINT REFERENCES engine_versions(id) ON DELETE SET NULL,
  engine_name TEXT NOT NULL,
  stage TEXT NOT NULL
    CHECK (stage IN ('cache', 'download', 'verify', 'start', 'runtime')),
  error TEXT NOT NULL,
  occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_worker_failures_worker_time
  ON worker_failures(worker_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_worker_failures_machine_time
  ON worker_failures(machine_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS moves (
  game_id BIGINT NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  ply INTEGER NOT NULL,
  uci TEXT NOT NULL,
  san TEXT NOT NULL,
  is_book INTEGER NOT NULL DEFAULT 0 CHECK (is_book IN (0, 1)),
  eval_cp INTEGER,
  eval_mate INTEGER,
  depth INTEGER,
  nodes INTEGER,
  nps INTEGER,
  pv TEXT,
  info_line TEXT,
  time_ms INTEGER NOT NULL DEFAULT 0,
  clock_after_ms INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (game_id, ply)
);

CREATE TABLE IF NOT EXISTS ratings (
  engine_id BIGINT NOT NULL REFERENCES engine_versions(id),
  category_id BIGINT NOT NULL REFERENCES categories(id),
  elo REAL NOT NULL DEFAULT 1500,
  games_played INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (engine_id, category_id)
);

CREATE TABLE IF NOT EXISTS rating_history (
  id BIGSERIAL PRIMARY KEY,
  engine_id BIGINT NOT NULL REFERENCES engine_versions(id),
  category_id BIGINT NOT NULL REFERENCES categories(id),
  tournament_id BIGINT NOT NULL REFERENCES tournaments(id),
  opponent_engine_id BIGINT NOT NULL REFERENCES engine_versions(id),
  elo_before REAL NOT NULL,
  elo REAL NOT NULL,
  elo_change REAL NOT NULL,
  score REAL NOT NULL CHECK (score IN (0, 0.5, 1)),
  game_id BIGINT NOT NULL REFERENCES games(id),
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tournament_rating_commits (
  tournament_id BIGINT PRIMARY KEY REFERENCES tournaments(id) ON DELETE CASCADE,
  category_id BIGINT NOT NULL REFERENCES categories(id),
  command_id BIGINT,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'claimed', 'applied', 'failed')),
  requested_at TEXT NOT NULL,
  applied_at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS service_endpoints (
  service TEXT PRIMARY KEY,
  host TEXT NOT NULL,
  port INTEGER NOT NULL CHECK (port > 0 AND port <= 65535),
  path TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS service_heartbeats (
  service TEXT PRIMARY KEY,
  app_commit TEXT NOT NULL,
  last_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS opening_suites (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS openings (
  id BIGSERIAL PRIMARY KEY,
  suite_id BIGINT NOT NULL REFERENCES opening_suites(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  fen TEXT NOT NULL,
  UNIQUE (suite_id, position)
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGSERIAL PRIMARY KEY,
  tournament_id BIGINT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL,
  text TEXT NOT NULL,
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS system_chat_events (
  tournament_id BIGINT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
  event_key TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message_id BIGINT NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
  metadata TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (tournament_id, event_key)
);

CREATE TABLE IF NOT EXISTS chat_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT INTO chat_settings (key, value) VALUES
  ('enabled', 'true'),
  ('slowmode_seconds', '0'),
  ('max_message_length', '300'),
  ('allow_anonymous_names', 'true'),
  ('retention_days', '30')
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS runner_commands (
  id BIGSERIAL PRIMARY KEY,
  command TEXT NOT NULL,
  payload TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'claimed', 'applied', 'failed')),
  created_at TEXT NOT NULL,
  claimed_at TEXT,
  finished_at TEXT,
  error TEXT
);

CREATE INDEX IF NOT EXISTS idx_games_tournament_status ON games(tournament_id, status);
CREATE INDEX IF NOT EXISTS idx_games_round_pair ON games(tournament_id, round, pair_index);
CREATE INDEX IF NOT EXISTS idx_tournament_matches_round ON tournament_matches(tournament_id, round, match_index);
CREATE INDEX IF NOT EXISTS idx_rating_history_engine_category_at ON rating_history(engine_id, category_id, at);

INSERT INTO schema_metadata (key, value) VALUES ('schema_version', 4)
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
CREATE INDEX IF NOT EXISTS idx_runner_commands_status_created ON runner_commands(status, created_at);
CREATE INDEX IF NOT EXISTS idx_workers_status ON workers(status);
CREATE INDEX IF NOT EXISTS idx_workers_machine_active ON workers(machine_id, status);
CREATE INDEX IF NOT EXISTS idx_game_assignments_worker_active ON game_assignments(worker_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_token_hash ON workers(token_hash) WHERE token_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_session_id ON workers(session_id) WHERE session_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_worker_pools_enrollment_token_hash ON worker_pools(enrollment_token_hash) WHERE enrollment_token_hash IS NOT NULL;
