-- BloxWeb 14: optional login + password accounts without e-mail.
-- Additive only: no column, row or policy is dropped or rewritten.
-- Run once as the project owner BEFORE deploying the matching server.py.
ALTER TABLE bloxweb.users ADD COLUMN IF NOT EXISTS login TEXT;
ALTER TABLE bloxweb.users ADD COLUMN IF NOT EXISTS password_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS users_login ON bloxweb.users(login);
-- One row per signed-in device; the original users.token_hash keeps working.
CREATE TABLE IF NOT EXISTS bloxweb.sessions (
 token_hash TEXT PRIMARY KEY,
 user_id TEXT NOT NULL REFERENCES bloxweb.users(id),
 created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS sessions_user ON bloxweb.sessions(user_id);
CREATE INDEX IF NOT EXISTS friends_b ON bloxweb.friends(b);
ALTER TABLE bloxweb.sessions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON bloxweb.sessions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON bloxweb.sessions TO bloxweb_runtime;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname='runtime_access' AND polrelid='bloxweb.sessions'::regclass) THEN
    CREATE POLICY runtime_access ON bloxweb.sessions TO bloxweb_runtime USING (true) WITH CHECK (true);
  END IF;
END $$;
