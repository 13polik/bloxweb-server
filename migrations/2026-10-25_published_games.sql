-- BloxWeb 17: games made in Studio 3D (parts + NexusScript) published for other players.
-- Additive only: two new tables; no existing column, row or policy changes.
-- Run once as the project owner BEFORE deploying the matching server.py.
-- hidden: 0 = visible, 1 = hidden after 3 reports (waits for review), 2 = withdrawn by its author.
CREATE TABLE IF NOT EXISTS bloxweb.published_games (
 id TEXT PRIMARY KEY,
 author TEXT NOT NULL REFERENCES bloxweb.users(id),
 title TEXT NOT NULL,
 description TEXT NOT NULL,
 data TEXT NOT NULL,
 created DOUBLE PRECISION NOT NULL,
 updated DOUBLE PRECISION NOT NULL,
 plays INTEGER NOT NULL DEFAULT 0,
 reports INTEGER NOT NULL DEFAULT 0,
 hidden INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS published_games_author ON bloxweb.published_games(author);
CREATE INDEX IF NOT EXISTS published_games_visible ON bloxweb.published_games(hidden, updated DESC);
CREATE TABLE IF NOT EXISTS bloxweb.game_reports (
 game_id TEXT NOT NULL REFERENCES bloxweb.published_games(id),
 reporter TEXT NOT NULL REFERENCES bloxweb.users(id),
 reason TEXT NOT NULL,
 created DOUBLE PRECISION NOT NULL,
 PRIMARY KEY(game_id, reporter));
ALTER TABLE bloxweb.published_games ENABLE ROW LEVEL SECURITY;
ALTER TABLE bloxweb.game_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON bloxweb.published_games FROM PUBLIC, anon, authenticated;
REVOKE ALL ON bloxweb.game_reports FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON bloxweb.published_games TO bloxweb_runtime;
GRANT SELECT, INSERT ON bloxweb.game_reports TO bloxweb_runtime;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname='runtime_access' AND polrelid='bloxweb.published_games'::regclass) THEN
    CREATE POLICY runtime_access ON bloxweb.published_games TO bloxweb_runtime USING (true) WITH CHECK (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policy WHERE polname='runtime_access' AND polrelid='bloxweb.game_reports'::regclass) THEN
    CREATE POLICY runtime_access ON bloxweb.game_reports TO bloxweb_runtime USING (true) WITH CHECK (true);
  END IF;
END $$;
