"""SQLite for local development; least-privilege PostgreSQL for deployment."""
import os
import sqlite3


class Row(dict):
    def __getitem__(self, key):
        return list(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [col.name for col in cursor.description]
    return lambda values: Row(zip(names, values))


class Postgres:
    def __init__(self, url):
        import psycopg
        self.driver = psycopg
        self.url = url
        self.connection = self.connect()

    def connect(self):
        return self.driver.connect(
            self.url, autocommit=True, connect_timeout=12,
            prepare_threshold=None, row_factory=row_factory,
            options="-c search_path=bloxweb,pg_catalog -c statement_timeout=10000",
        )

    def execute(self, query, parameters=()):
        # Only fixed, server-authored SQL reaches this adapter.
        query = query.replace("id=? COLLATE NOCASE", "lower(id)=lower(?)")
        ignore = "INSERT OR IGNORE" in query
        query = query.replace("INSERT OR IGNORE", "INSERT")
        if ignore:
            query += " ON CONFLICT DO NOTHING"
        query = query.replace("?", "%s")
        if self.connection.closed or self.connection.broken:
            self.connection = self.connect()
        return self.connection.execute(query, parameters or None)

    def commit(self):
        # Do not keep read transactions open across HTTP requests.
        pass

    def close(self):
        self.connection.close()


def open_database(data):
    url = os.environ.get("DATABASE_URL", "")
    if url:
        if not url.startswith(("postgresql://", "postgres://")):
            raise RuntimeError("DATABASE_URL must be a PostgreSQL URL")
        return Postgres(url)
    if os.environ.get("RENDER") == "true":
        raise RuntimeError("Persistent DATABASE_URL is required on Render")
    db = sqlite3.connect(data / "bloxweb.sqlite3", check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.create_function("fold", 1, lambda value: str(value or "").casefold(), deterministic=True)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
     id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, visitor_hash TEXT UNIQUE,
     name TEXT NOT NULL, avatar TEXT NOT NULL, created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS friends(
     a TEXT NOT NULL REFERENCES users(id), b TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(a,b));
    CREATE TABLE IF NOT EXISTS requests(
     sender TEXT NOT NULL REFERENCES users(id), target TEXT NOT NULL REFERENCES users(id),
     created REAL NOT NULL, PRIMARY KEY(sender,target));
    CREATE TABLE IF NOT EXISTS messages(
     id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL REFERENCES users(id),
     target TEXT NOT NULL REFERENCES users(id), text TEXT NOT NULL, created REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS messages_pair ON messages(sender,target,id);
    """)
    db.commit()
    return db
