-- ONE-OFF, DESTRUCTIVE: removes every account except BLOX-759762 (13polik, owner)
-- and BLOX-828719 (Mikolaj_Ps, admin), with everything that belongs to them.
-- Requested by the owner on 2026-10-26. Run only after explicit confirmation,
-- after migrations 2026-10-25_published_games.sql and 2026-10-26_roles_projects.sql.
-- A copy of the removed rows is kept in schema bloxweb_backup until the owner asks to drop it.
BEGIN;
CREATE SCHEMA IF NOT EXISTS bloxweb_backup;
REVOKE ALL ON SCHEMA bloxweb_backup FROM PUBLIC, anon, authenticated;
CREATE TABLE bloxweb_backup.users_20261026 AS SELECT * FROM bloxweb.users WHERE id NOT IN ('BLOX-759762','BLOX-828719');
CREATE TABLE bloxweb_backup.messages_20261026 AS SELECT * FROM bloxweb.messages WHERE sender NOT IN ('BLOX-759762','BLOX-828719') OR target NOT IN ('BLOX-759762','BLOX-828719');
CREATE TABLE bloxweb_backup.friends_20261026 AS SELECT * FROM bloxweb.friends WHERE a NOT IN ('BLOX-759762','BLOX-828719') OR b NOT IN ('BLOX-759762','BLOX-828719');
CREATE TABLE bloxweb_backup.published_games_20261026 AS SELECT * FROM bloxweb.published_games WHERE author NOT IN ('BLOX-759762','BLOX-828719');
CREATE TABLE bloxweb_backup.studio_projects_20261026 AS SELECT * FROM bloxweb.studio_projects WHERE user_id NOT IN ('BLOX-759762','BLOX-828719');
-- Children first (foreign keys), then the accounts.
DELETE FROM bloxweb.game_reports WHERE reporter NOT IN ('BLOX-759762','BLOX-828719')
  OR game_id IN (SELECT id FROM bloxweb.published_games WHERE author NOT IN ('BLOX-759762','BLOX-828719'));
DELETE FROM bloxweb.published_games WHERE author NOT IN ('BLOX-759762','BLOX-828719');
DELETE FROM bloxweb.studio_projects WHERE user_id NOT IN ('BLOX-759762','BLOX-828719');
DELETE FROM bloxweb.messages WHERE sender NOT IN ('BLOX-759762','BLOX-828719') OR target NOT IN ('BLOX-759762','BLOX-828719');
DELETE FROM bloxweb.requests WHERE sender NOT IN ('BLOX-759762','BLOX-828719') OR target NOT IN ('BLOX-759762','BLOX-828719');
DELETE FROM bloxweb.friends WHERE a NOT IN ('BLOX-759762','BLOX-828719') OR b NOT IN ('BLOX-759762','BLOX-828719');
DELETE FROM bloxweb.sessions WHERE user_id NOT IN ('BLOX-759762','BLOX-828719');
DELETE FROM bloxweb.users WHERE id NOT IN ('BLOX-759762','BLOX-828719');
COMMIT;
