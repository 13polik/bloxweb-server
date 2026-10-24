-- BloxWeb 15: BloxBux, owned items, badges and quests saved on the account.
-- Additive only: one nullable column; existing rows keep NULL until a device uploads.
-- Run once BEFORE deploying the matching server.py.
ALTER TABLE bloxweb.users ADD COLUMN IF NOT EXISTS progress TEXT;
