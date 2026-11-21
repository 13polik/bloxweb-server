"""Daily copy of BloxWeb's SQLite database (safe while the server runs); keeps the last 14 days."""
import sqlite3
import time
from pathlib import Path

DATA = Path("/opt/bloxweb/data")
BACKUPS = Path("/opt/bloxweb/backups")
BACKUPS.mkdir(exist_ok=True)
target = BACKUPS / time.strftime("bloxweb-%Y%m%d-%H%M.sqlite3")
source = sqlite3.connect(DATA / "bloxweb.sqlite3")
with sqlite3.connect(target) as copy:
    source.backup(copy)
source.close()
for old in sorted(BACKUPS.glob("bloxweb-*.sqlite3"))[:-14]:
    old.unlink()
print("backup", target)
