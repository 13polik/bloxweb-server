-- Run as schema owner. Existing users, friends, requests and messages stay intact.
CREATE TABLE IF NOT EXISTS bloxweb.studio_games(
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES bloxweb.users(id),
 project_id TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL,
 project TEXT NOT NULL, created DOUBLE PRECISION NOT NULL,
 updated DOUBLE PRECISION NOT NULL, published INTEGER NOT NULL DEFAULT 1,
 plays INTEGER NOT NULL DEFAULT 0, UNIQUE(owner,project_id));
ALTER TABLE bloxweb.studio_games ENABLE ROW LEVEL SECURITY;
GRANT SELECT,INSERT,UPDATE,DELETE ON bloxweb.studio_games TO bloxweb_runtime;
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname='bloxweb'
   AND tablename='studio_games' AND policyname='runtime_access') THEN
  CREATE POLICY runtime_access ON bloxweb.studio_games TO bloxweb_runtime
    USING (true) WITH CHECK (true);
 END IF;
END $$;
