-- Tables from contracts/CONTRACT.md. Idempotent: runs on every startup.
CREATE TABLE IF NOT EXISTS challenges (
  id text PRIMARY KEY, session_id text NOT NULL, seed bigint NOT NULL, variant_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
  attempts int NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS attempts (
  id text PRIMARY KEY, challenge_id text, cohort text NOT NULL, device text,
  nondominant_hand boolean DEFAULT false, round_id text, features jsonb, score real,
  pass boolean, trail_key text, created_at timestamptz DEFAULT now());
CREATE INDEX IF NOT EXISTS attempts_cohort ON attempts (cohort, round_id);

CREATE TABLE IF NOT EXISTS tokens (
  id text PRIMARY KEY, session_id text NOT NULL, action text NOT NULL,
  expires_at timestamptz NOT NULL, consumed_at timestamptz);

CREATE TABLE IF NOT EXISTS pow (
  id text PRIMARY KEY, session_id text NOT NULL, nonce text NOT NULL, bits int NOT NULL,
  expires_at timestamptz NOT NULL, solved_at timestamptz);

CREATE TABLE IF NOT EXISTS reservations (
  id text PRIMARY KEY, session_id text NOT NULL, token_id text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS variants (
  id text PRIMARY KEY, config jsonb NOT NULL, status text NOT NULL,  -- active | candidate | retired
  created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS approvals (
  id text PRIMARY KEY, interrupt_id text, variant_id text NOT NULL, gate jsonb,
  status text NOT NULL DEFAULT 'pending', decided_at timestamptz);

CREATE TABLE IF NOT EXISTS gate_decisions (
  id text PRIMARY KEY, candidate text NOT NULL, baseline text NOT NULL, result jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS lab_commands (
  id text PRIMARY KEY, kind text NOT NULL, status text NOT NULL DEFAULT 'queued',
  created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE IF NOT EXISTS lab_events (
  id bigserial PRIMARY KEY, run_id text, body jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now());
