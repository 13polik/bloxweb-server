-- BloxWeb 19: staff roles, account blocking, game covers and cloud-saved Studio projects.
-- Additive: new nullable/defaulted columns and one new table. Run AFTER 2026-10-25_published_games.sql
-- and BEFORE deploying the matching server.py.
ALTER TABLE bloxweb.users ADD COLUMN IF NOT EXISTS role TEXT;
ALTER TABLE bloxweb.users ADD COLUMN IF NOT EXISTS banned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bloxweb.published_games ADD COLUMN IF NOT EXISTS cover TEXT;
-- Every player's private Studio 3D projects (up to 20 each), synced between devices.
CREATE TABLE IF NOT EXISTS bloxweb.studio_projects (
 user_id TEXT NOT NULL REFERENCES bloxweb.users(id),
 id TEXT NOT NULL,
 name TEXT NOT NULL,
 data TEXT NOT NULL,
 updated DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(user_id, id));
ALTER TABLE bloxweb.studio_projects ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON bloxweb.studio_projects FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON bloxweb.studio_projects TO bloxweb_runtime;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname='runtime_access' AND polrelid='bloxweb.studio_projects'::regclass) THEN
    CREATE POLICY runtime_access ON bloxweb.studio_projects TO bloxweb_runtime USING (true) WITH CHECK (true);
  END IF;
END $$;
-- Staff chosen by the owner: CEO (13polik) and administrator (Mikolaj_Ps), matched by ID.
UPDATE bloxweb.users SET role='owner' WHERE id='BLOX-759762';
UPDATE bloxweb.users SET role='admin' WHERE id='BLOX-828719';
