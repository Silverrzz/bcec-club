PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS engines (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  author TEXT NOT NULL DEFAULT '',
  version TEXT NOT NULL DEFAULT '',
  git_url TEXT NOT NULL,
  branch TEXT NOT NULL DEFAULT '',
  commit_hash TEXT NOT NULL,
  build_cmd TEXT NOT NULL,
  binary_path TEXT NOT NULL,
  uci_options TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  default_config TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  created_at TEXT NOT NULL
);

INSERT OR IGNORE INTO categories (id, name, description, default_config, created_at)
VALUES (
  1,
  'Default',
  'General rating list and tournament defaults.',
  '{}',
  '1970-01-01T00:00:00+00:00'
);

CREATE TABLE IF NOT EXISTS tournaments (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category_id INTEGER NOT NULL DEFAULT 1 REFERENCES categories(id),
  settings_unlinked INTEGER NOT NULL DEFAULT 0 CHECK (settings_unlinked IN (0, 1)),
  config TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'scheduled', 'running', 'paused', 'finished', 'aborted')),
  current_round INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS participants (
  tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
  engine_id INTEGER NOT NULL REFERENCES engines(id),
  seed INTEGER NOT NULL,
  PRIMARY KEY (tournament_id, engine_id),
  UNIQUE (tournament_id, seed)
);

CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY,
  tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
  round INTEGER NOT NULL,
  pair_index INTEGER NOT NULL,
  white_engine_id INTEGER NOT NULL REFERENCES engines(id),
  black_engine_id INTEGER NOT NULL REFERENCES engines(id),
  opening_id INTEGER,
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

CREATE TABLE IF NOT EXISTS game_assignments (
  id INTEGER PRIMARY KEY,
  game_id INTEGER NOT NULL UNIQUE REFERENCES games(id) ON DELETE CASCADE,
  assignment_key TEXT NOT NULL UNIQUE,
  hardware_mode TEXT NOT NULL CHECK (hardware_mode IN ('shared', 'paired')),
  white_worker_id INTEGER REFERENCES workers(id) ON DELETE SET NULL,
  black_worker_id INTEGER REFERENCES workers(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'assigned'
    CHECK (status IN ('assigned', 'acked', 'live', 'finished', 'abandoned', 'expired')),
  sent_at TEXT,
  acked_at TEXT,
  finished_at TEXT,
  last_error TEXT
);

CREATE TABLE IF NOT EXISTS moves (
  game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  ply INTEGER NOT NULL,
  uci TEXT NOT NULL,
  san TEXT NOT NULL,
  is_book INTEGER NOT NULL DEFAULT 0 CHECK (is_book IN (0, 1)),
  eval_cp INTEGER,
  eval_mate INTEGER,
  depth INTEGER,
  nodes INTEGER,
  time_ms INTEGER NOT NULL DEFAULT 0,
  clock_after_ms INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (game_id, ply)
);

CREATE TABLE IF NOT EXISTS ratings (
  engine_id INTEGER NOT NULL REFERENCES engines(id),
  category_id INTEGER NOT NULL REFERENCES categories(id),
  elo REAL NOT NULL DEFAULT 1500,
  games_played INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (engine_id, category_id)
);

CREATE TABLE IF NOT EXISTS rating_history (
  id INTEGER PRIMARY KEY,
  engine_id INTEGER NOT NULL REFERENCES engines(id),
  category_id INTEGER NOT NULL REFERENCES categories(id),
  elo REAL NOT NULL,
  game_id INTEGER NOT NULL REFERENCES games(id),
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tournament_rating_commits (
  tournament_id INTEGER PRIMARY KEY REFERENCES tournaments(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'claimed', 'applied', 'failed')),
  requested_at TEXT NOT NULL,
  applied_at TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS workers (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL,
  token_hash TEXT,
  token_expires_at TEXT,
  status TEXT NOT NULL DEFAULT 'minted'
    CHECK (status IN ('minted', 'connected', 'building', 'ready', 'busy', 'offline', 'revoked')),
  session_id TEXT,
  app_commit TEXT,
  protocol_version INTEGER,
  hw TEXT,
  last_seen TEXT
);

CREATE TABLE IF NOT EXISTS opening_suites (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS openings (
  id INTEGER PRIMARY KEY,
  suite_id INTEGER NOT NULL REFERENCES opening_suites(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  fen TEXT NOT NULL,
  UNIQUE (suite_id, position)
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY,
  display_name TEXT NOT NULL,
  text TEXT NOT NULL,
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO chat_settings (key, value) VALUES
  ('enabled', 'true'),
  ('slowmode_seconds', '0'),
  ('max_message_length', '300'),
  ('allow_anonymous_names', 'true'),
  ('retention_days', '30');

CREATE TABLE IF NOT EXISTS runner_commands (
  id INTEGER PRIMARY KEY,
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
CREATE INDEX IF NOT EXISTS idx_rating_history_engine_category_at ON rating_history(engine_id, category_id, at);
CREATE INDEX IF NOT EXISTS idx_runner_commands_status_created ON runner_commands(status, created_at);
CREATE INDEX IF NOT EXISTS idx_workers_status ON workers(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_token_hash ON workers(token_hash) WHERE token_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_session_id ON workers(session_id) WHERE session_id IS NOT NULL;
