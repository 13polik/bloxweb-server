"""BloxWeb 11: anonymous authenticated social API and server-run co-op rooms.

Run: python3 server.py. DATABASE_URL enables durable PostgreSQL storage.
Without it, local development stores SQLite in DATA_DIR (default ./data).
The simulation is deliberately lightweight; accounts/economy from the old HTML
remain local. Production needs TLS, backups and process supervision.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import random
import re
import secrets
import time
from pathlib import Path
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from storage import open_database
from bot_ai import BotDirector

ROOT = Path(__file__).parent
DATA = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)
db = open_database(DATA)
secret_file = DATA / "server-secret"
if not secret_file.exists():
    secret_file.write_text(secrets.token_hex(32))
    secret_file.chmod(0o600)
SERVER_SECRET = secret_file.read_text().strip().encode()
TRUST_VISITOR = os.environ.get("TRUST_PREVIEW_PROXY") == "1"
# Optional Cloudflare Worker running the NexusScript assistant model.
AI_URL = os.environ.get("BLOX_AI_URL", "")
AI_KEY = os.environ.get("BLOX_AI_KEY", "")
AI_DAILY_LIMIT = int(os.environ.get("BLOX_AI_DAILY_LIMIT", "250"))
# The same language reference is embedded in the page for the copyable AI prompt.
NEXUS_REFERENCE = (ROOT / "nexusscript.md").read_text(encoding="utf-8") if (ROOT / "nexusscript.md").exists() else ""
rooms = {}
presence = {}
rates = defaultdict(deque)
login_failures = defaultdict(deque)
# Live room connections (uid -> socket state) and anti-cheat bookkeeping.
sockets = {}
cheat_strikes = defaultdict(deque)
coin_buckets = {}
COIN_BUCKET, COIN_REFILL = 5000, 30
# Staff roles live only in the database; the matching badges are shown from the
# role, never from a browser save. owner (CEO) > admin.
ROLES = {"owner", "admin"}
ROLE_BADGES = {"b_ceo", "b_admin"}
anticheat_log = deque(maxlen=100)
# This single process is the only writer, so profiles, sessions and social
# relations can be cached and invalidated on every write. A /sync then needs
# no database round trip at all, which keeps the room simulation smooth.
user_cache = {}
token_cache = {}
relation_cache = {}
LOGIN_PATTERN = r"[a-z0-9_.-]{3,20}"
log = logging.getLogger("bloxweb")
GAME_IDS = {"castle_defense", "cs2"}
COLORS = ["head", "torso", "leftArm", "rightArm", "leftLeg", "rightLeg"]
TOWERS = {
    "archer": dict(cost=50, damage=15, range=16, cooldown=.85),
    "cannon": dict(cost=100, damage=45, range=13, cooldown=1.6),
    "ice": dict(cost=150, damage=20, range=18, cooldown=1.1),
    "fire": dict(cost=200, damage=35, range=12, cooldown=1.3),
    "laser": dict(cost=300, damage=80, range=22, cooldown=1),
}
WEAPONS = {
    "glock": dict(price=0, ammo=20, reload=1.5, damage=25, headshot=100, cooldown=.2),
    "usp": dict(price=200, ammo=12, reload=1.8, damage=34, headshot=140, cooldown=.2),
    "deagle": dict(price=650, ammo=7, reload=2.2, damage=63, headshot=250, cooldown=.5),
    "mp5": dict(price=1500, ammo=30, reload=2.5, damage=26, headshot=105, cooldown=.1),
    "ak47": dict(price=2500, ammo=30, reload=2.8, damage=36, headshot=145, cooldown=.1),
    "m4a1": dict(price=3100, ammo=30, reload=2.7, damage=33, headshot=130, cooldown=.1),
    "awp": dict(price=4750, ammo=10, reload=3.5, damage=115, headshot=450, cooldown=1.5),
}
# Exact arena boxes are extracted by the build script from initCS2.
MAP = json.loads((ROOT / "arena.json").read_text()) if (ROOT / "arena.json").exists() else []


def now():
    return time.monotonic()


def clean(s, limit=32):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(s or "")).strip()[:limit]


def avatar(value):
    value = value if isinstance(value, dict) else {}
    out = {k: v for k, v in value.items() if k in COLORS and isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)}
    for k in ("hat", "back", "face", "tshirt", "pants"):
        if re.fullmatch(r"[a-z0-9_-]{1,40}", str(value.get(k, ""))):
            out[k] = value[k]
    return out


def fail(message, status=400):
    raise HTTPException(status, message)


def number(v, default=0, low=-1000, high=1000):
    try:
        n = float(v)
        return max(low, min(high, n)) if math.isfinite(n) else default
    except (ValueError, TypeError):
        return default


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def token_user(token):
    """Resolve a session token from a signed-in device or an original guest token."""
    if not token:
        return None
    digest = hash_token(token)
    if digest in token_cache:
        return token_cache[digest]
    row = db.execute("SELECT user_id FROM sessions WHERE token_hash=?", (digest,)).fetchone()
    if not row:
        row = db.execute("SELECT id AS user_id FROM users WHERE token_hash=?", (digest,)).fetchone()
    if row:
        token_cache[digest] = row["user_id"]
        return row["user_id"]
    return None


def auth(request, body):
    token = request.headers.get("authorization", "").removeprefix("Bearer ") or body.get("token", "")
    if not isinstance(token, str) or len(token) > 150:
        fail("Nieprawidłowa sesja.", 401)
    uid = token_user(token)
    if not uid or not profile(uid):
        fail("Sesja wygasła. Połącz konto ponownie.", 401)
    if profile(uid)["banned"]:
        fail("To konto zostało zablokowane przez administrację BloxWeb.", 403)
    return profile(uid)


def profile(uid):
    if uid not in user_cache:
        u = db.execute("SELECT id,name,avatar,login,progress,role,banned FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            return None
        user_cache[uid] = dict(id=u["id"], name=u["name"], avatar=json.loads(u["avatar"]), login=u["login"],
                               progress=json.loads(u["progress"]) if u["progress"] else None,
                               role=u["role"] if u["role"] in ROLES else None, banned=bool(u["banned"]))
    return user_cache[uid]


def item_ids(value, limit):
    value = value if isinstance(value, list) else []
    return sorted({v for v in value if isinstance(v, str) and re.fullmatch(r"[a-z0-9_-]{1,40}", v)})[:limit]


def progress_data(value):
    """Validate a progress snapshot: BloxBux, owned items, badges and quests."""
    value = value if isinstance(value, dict) else {}
    quests = value.get("quests") if isinstance(value.get("quests"), dict) else {}
    counters = {k: int(number(v, 0, 0, 1e9)) for k, v in quests.items()
                if k != "claimed" and isinstance(k, str) and re.fullmatch(r"[a-z0-9_]{1,40}", k)}
    return dict(coins=int(number(value.get("coins"), 0, 0, 1e12)), owned=item_ids(value.get("owned"), 500),
                badges=[b for b in item_ids(value.get("badges"), 100) if b not in ROLE_BADGES],
                quests=dict(list(counters.items())[:50], claimed=item_ids(quests.get("claimed"), 100)))


def merge_progress(server, base, current):
    """Apply one device's changes (current minus the base it started from) on
    top of the server copy, so two devices earning at once both keep coins."""
    current = progress_data(current)
    if server is None:
        return current
    if base is None:
        # A device that never synced: combine (highest coins, all items)
        # rather than adding its whole balance on top a second time.
        base = dict(current, coins=min(current["coins"], server["coins"]),
                    quests={k: min(v, server["quests"].get(k, 0)) for k, v in current["quests"].items() if k != "claimed"})
    base = progress_data(base)
    quests = dict(server["quests"])
    for key, value in current["quests"].items():
        if key != "claimed":
            quests[key] = max(0, quests.get(key, 0) + value - base["quests"].get(key, 0))
    quests["claimed"] = sorted(set(server["quests"]["claimed"]) | set(current["quests"]["claimed"]))
    return dict(coins=max(0, server["coins"] + current["coins"] - base["coins"]),
                owned=sorted(set(server["owned"]) | set(current["owned"])),
                badges=sorted(set(server["badges"]) | set(current["badges"])), quests=quests)


def coin_allowance(uid, gained):
    """Token bucket for BloxBux earned in the browser: up to 5000 at once
    (the largest single reward is 2500) refilling 30 per second. Anything above
    is dropped, so edited local saves or auto-clickers cannot mint coins."""
    level, stamp = coin_buckets.get(uid, (COIN_BUCKET, now()))
    level = min(COIN_BUCKET, level + (now()-stamp)*COIN_REFILL)
    allowed = min(gained, int(level))
    coin_buckets[uid] = (level-allowed, now())
    if allowed < gained:
        strike(uid, "bloxbux", f"+{gained} zablokowano {gained-allowed}")
    return allowed


def save_progress(uid, change):
    if not isinstance(change, dict):
        return
    current = profile(uid)
    merged = merge_progress(current["progress"], change.get("base"), change.get("current"))
    # The first upload imports an existing browser save as it is, so players
    # who earned coins before accounts existed keep them; later gains are rate-limited.
    if current["progress"] is None:
        if merged["coins"] > 100000:
            log.warning("anticheat %s first import with %s BloxBux", uid, merged["coins"])
    elif merged["coins"] > current["progress"]["coins"]:
        before = current["progress"]["coins"]
        merged["coins"] = before + coin_allowance(uid, merged["coins"]-before)
    if merged != current["progress"]:
        db.execute("UPDATE users SET progress=? WHERE id=?", (json.dumps(merged), uid))
        db.commit()
        current["progress"] = merged


def save_profile(uid, name, look):
    current = profile(uid)
    name, look = clean(name, 16) or current["name"], avatar(look)
    if (name, look) != (current["name"], current["avatar"]):
        db.execute("UPDATE users SET name=?,avatar=? WHERE id=?", (name, json.dumps(look), uid))
        db.commit()
        current.update(name=name, avatar=look)


def user_view(uid):
    u = profile(uid)
    if not u:
        return None
    p = presence.get(uid, {})
    online = now() - p.get("seen", 0) < 15
    room = rooms.get(p.get("room", "")) if online else None
    return dict(id=u["id"], name=u["name"], avatar=u["avatar"], role=u["role"],
                status="ingame" if room else "online" if online else "offline",
                gameId=room["game"] if room else None, roomCode=room["code"] if room else None)


def relations(uid):
    if uid not in relation_cache:
        fs = db.execute("SELECT a,b FROM friends WHERE a=? OR b=?", (uid, uid)).fetchall()
        ins = db.execute("SELECT sender FROM requests WHERE target=?", (uid,)).fetchall()
        outs = db.execute("SELECT target FROM requests WHERE sender=?", (uid,)).fetchall()
        msgs = db.execute("SELECT * FROM (SELECT * FROM messages WHERE sender=? OR target=? ORDER BY id DESC LIMIT 500) ORDER BY id", (uid, uid)).fetchall()
        relation_cache[uid] = dict(friends=[r["b"] if r["a"] == uid else r["a"] for r in fs],
                                   incoming=[r["sender"] for r in ins], outgoing=[r["target"] for r in outs],
                                   messages=[dict(r) for r in msgs])
    return relation_cache[uid]


# ---------- Player-made games (Studio 3D + NexusScript) ----------
PART_TYPES = {"block", "lava", "coin", "spawn", "finish", "checkpoint", "spring", "enemy", "glass", "ammo", "health"}
HEX = re.compile(r"#[0-9a-fA-F]{6}")
# Short stems of common Polish/English swear words; titles, descriptions,
# part names and script text are all checked because other children see them.
BLOCKED_WORDS = re.compile(r"kurw|chuj|\bhuj|pierdol|jeba|jebi|\bjeb|pizd|spierd|kutas|dziwk|cwel|pedal|fuck|shit|bitch|nigg|whore|cunt")
game_publish_times = defaultdict(deque)
game_plays_seen = set()
ai_calls = defaultdict(deque)
ai_daily = deque()


def unfold(text):
    return str(text).casefold().translate(str.maketrans("ąćęłńóśźż0134@$", "acelnoszzoieaas"))


def rude(*texts):
    return any(BLOCKED_WORDS.search(unfold(t)) for t in texts if t)


def vec(value, low, high, default):
    value = value if isinstance(value, list) and len(value) == 3 else [default]*3
    return [round(number(v, default, low, high), 2) for v in value]


def game_data(value):
    """Validate a Studio 3D project: data only, the script stays text that the
    client interprets in a sandbox. Returns the canonical copy that is stored."""
    if not isinstance(value, dict) or value.get("format") != "bloxweb-nexus":
        fail("Nieprawidłowy projekt gry.")
    settings = value.get("settings") if isinstance(value.get("settings"), dict) else {}
    sky = settings.get("sky") if HEX.fullmatch(str(settings.get("sky", ""))) else "#8fd3ff"
    parts = []
    raw_parts = value.get("parts") if isinstance(value.get("parts"), list) else []
    if len(raw_parts) > 600:
        fail("Gra może mieć najwyżej 600 elementów.")
    for raw in raw_parts:
        if not isinstance(raw, dict) or raw.get("t") not in PART_TYPES:
            continue
        part = dict(t=raw["t"], p=vec(raw.get("p"), -500, 500, 0), s=vec(raw.get("s"), .2, 200, 1),
                    c=raw["c"] if HEX.fullmatch(str(raw.get("c", ""))) else "#9aa4b1")
        name = clean(raw.get("n"), 24)
        if name:
            part["n"] = name
        if raw.get("r"):
            part["r"] = round(number(raw.get("r"), 0, -360, 360), 1)
        parts.append(part)
    script = str(value.get("script") or "")
    if len(script) > 20000:
        fail("Skrypt NexusScript może mieć najwyżej 20 000 znaków.")
    return dict(format="bloxweb-nexus", version=1, settings=dict(
        speed=number(settings.get("speed"), 8, 4, 16), jump=number(settings.get("jump"), 12, 6, 22),
        gravity=number(settings.get("gravity"), 30, 10, 45), sky=sky), parts=parts, script=script)


def game_card(row):
    author = profile(row["author"]) or {}
    return dict(id=row["id"], title=row["title"], description=row["description"], author=author.get("name", "Gracz"),
                authorId=row["author"], authorRole=author.get("role"), cover=row["cover"] if "cover" in row.keys() else None, plays=row["plays"], created=row["created"], updated=row["updated"],
                hidden=row["hidden"], revision=row["revision"])


def ai_request(prompt, code):
    """Forward one NexusScript request to the Cloudflare Worker running the model."""
    import urllib.request
    payload = json.dumps(dict(prompt=prompt, code=code, reference=NEXUS_REFERENCE)).encode()
    request = urllib.request.Request(AI_URL, data=payload, method="POST", headers={
        "Content-Type": "application/json", "X-Blox-Key": AI_KEY,
        # Cloudflare refuses the default "Python-urllib" agent with 403.
        "User-Agent": "BloxWeb-Server/19"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


COVER = re.compile(r"data:image/(jpeg|webp|png);base64,[A-Za-z0-9+/=]{100,60000}")
PROJECT_META = ("description", "publishedId", "publishedRevision", "publishedPrint", "aiDescription")


def cover_data(value):
    return value if isinstance(value, str) and COVER.fullmatch(value) else None


def project_data(value):
    """A private Studio 3D project saved in the cloud: the game data plus editor metadata."""
    if not isinstance(value, dict):
        fail("Nieprawidłowy projekt.")
    project_id = clean(value.get("id"), 40)
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,40}", project_id):
        fail("Nieprawidłowy identyfikator projektu.")
    data = game_data(dict(value, format="bloxweb-nexus"))
    data.update(id=project_id, name=clean(value.get("name"), 40) or "Moja gra 3D",
                updated=number(value.get("updated"), time.time()*1000, 0, 1e14))
    for key in PROJECT_META:
        if isinstance(value.get(key), (str, int, float)) and not isinstance(value.get(key), bool):
            data[key] = value[key] if not isinstance(value[key], str) else value[key][:600]
    return data


def staff(user, level="admin"):
    if user["role"] != "owner" and (level == "owner" or user["role"] != "admin"):
        fail("Brak uprawnień administratora.", 403)


def admin_user_view(uid):
    u = profile(uid)
    if not u:
        return None
    p = presence.get(uid, {})
    return dict(user_view(uid), login=u["login"], banned=u["banned"], room=p.get("room"),
                coins=(u["progress"] or {}).get("coins", 0),
                games=db.execute("SELECT COUNT(*) FROM published_games WHERE author=?", (uid,)).fetchone()[0])


def forget_relations(*uids):
    for uid in uids:
        relation_cache.pop(uid, None)


def relation(a, b):
    return b in relations(a)["friends"]


def social(uid):
    r = relations(uid)
    people = lambda ids: [v for v in map(user_view, ids) if v]
    return dict(friends=people(r["friends"]), incoming=people(r["incoming"]),
                outgoing=people(r["outgoing"]), messages=r["messages"])


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def password_ok(password, stored):
    try:
        _, n, r, p, salt, digest = (stored or "").split("$")
        check = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(check.hex(), digest)
    except ValueError:
        return False


def credentials(body):
    login, password = clean(body.get("login"), 40).lower(), body.get("password")
    if not re.fullmatch(LOGIN_PATTERN, login):
        fail("Login: 3–20 znaków, tylko litery a–z, cyfry, kropka, myślnik i podkreślenie.")
    if not isinstance(password, str) or not 6 <= len(password) <= 128:
        fail("Hasło musi mieć od 6 do 128 znaków.")
    return login, password


def account_view(uid):
    return dict(login=profile(uid)["login"])


DUMMY_HASH = password_hash(secrets.token_hex(8))


def leave(uid):
    p = presence.get(uid)
    if not p:
        return
    room = rooms.get(p.get("room"))
    if room:
        room["players"].pop(uid, None)
        if room["owner"] == uid:
            room["owner"] = next(iter(room["players"]), "")
        if not room["players"]:
            room["emptySince"] = now()
    p["room"] = None


def strike(uid, kind, detail=""):
    """Record a suspicious action. Many in a minute remove the player from the room."""
    log.warning("anticheat %s %s %s", uid, kind, detail)
    anticheat_log.append(dict(time=time.time(), user=uid, kind=kind, detail=str(detail)[:80]))
    q = cheat_strikes[uid]
    q.append(now())
    while q and q[0] < now()-60:
        q.popleft()
    if len(q) >= 25 and presence.get(uid, {}).get("room"):
        q.clear()
        kick(uid, "Wykryto nieprawidłowe działanie gry (" + kind + "). Zostałeś usunięty z pokoju.")


def kick(uid, reason):
    log.warning("anticheat kick %s: %s", uid, reason)
    anticheat_log.append(dict(time=time.time(), user=uid, kind="kick", detail=reason[:80]))
    leave(uid)
    presence.setdefault(uid, dict(seen=now(), room=None))["notice"] = reason
    conn = sockets.get(uid)
    if conn:
        conn["notice"] = reason
        conn["event"].set()


def room_input(uid, body):
    """Apply one player's position and queued actions (shared by /sync and the socket)."""
    room = rooms.get(presence.get(uid, {}).get("room"))
    if not room or uid not in room["players"]:
        return None
    p = room["players"][uid]
    p["seen"] = now()
    pos = body.get("position")
    if isinstance(pos, dict):
        elapsed = min(2, max(.05, now()-p["lastMove"]))
        x, z = number(pos.get("x"), p["x"], -89, 89), number(pos.get("z"), p["z"], -89, 89)
        distance = math.hypot(x-p["x"], z-p["z"])
        maximum = elapsed*18+1
        if distance > maximum:
            # Lag spikes are covered by `elapsed`; a far bigger jump is a teleport/speed hack.
            if distance > maximum*1.6:
                strike(uid, "ruch", f"{distance:.1f}>{maximum:.1f}")
            ratio = maximum/distance
            x, z = p["x"]+(x-p["x"])*ratio, p["z"]+(z-p["z"])*ratio
        y = number(pos.get("y"), .5, .5, 16)
        if room["game"] == "cs2" and y > 11:
            # Arena walls are 12 high and crates plus a jump reach about 8: higher means flying.
            strike(uid, "lot", f"y={y:.1f}")
            y = 11
        p.update(x=x, y=y, z=z, rotY=number(pos.get("rotY")),
                 moving=bool(pos.get("moving")), dancing=bool(pos.get("dancing")), lastMove=now())
    actions = body.get("actions", [])
    if not isinstance(actions, list):
        fail("Nieprawidłowa lista akcji.")
    for action in actions[:30]:
        if not isinstance(action, dict):
            continue
        sequence = int(number(action.get("seq"), 0, 0, 1e12))
        if sequence <= p["sequence"]:
            continue
        p["sequence"] = sequence
        message = act(room, p, action)
        p["acknowledgements"].append(dict(seq=sequence, error=message))
        p["acknowledgements"] = p["acknowledgements"][-35:]
        if uid not in room["players"]:
            return None
    return room


def spawn_bot(room):
    points = [(-28,-39),(32,-38),(-14,20),(58,18),(-25,52),(62,55)]
    random.shuffle(points)
    x, z = max(points, key=lambda p:min((math.hypot(p[0]-e["x"],p[1]-e["z"]) for e in room["enemies"]), default=100))
    room["serial"] += 1
    room["enemies"].append(dict(id=room["serial"], x=x, y=.5, z=z, hp=100, maxHp=100, cooldown=2, rot=0))


def player_state(uid, game, slot=0):
    return dict(id=uid, x=-70 + slot*2 if game == "cs2" else slot*2,
                y=1.5 if game == "cs2" else .5, z=-70 if game == "cs2" else 18,
                rotY=0, hp=100, money=800, kills=0, deaths=0,
                weapons=[dict(id="glock", ammo=20)], currentWeapon=0,
                reloadUntil=0, shootUntil=0, shieldUntil=now()+3, lastMove=now(), seen=now(),
                sequence=0, acknowledgements=[], moving=False, dancing=False)


def create_room(uid, game, public=False):
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    while code in rooms:
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    room = dict(code=code, game=game, owner=uid, public=public, players={}, serial=0,
                enemies=[], turrets=[], fx=[], chat=[], revision=0, phase="playing",
                created=now(), emptySince=0, gold=300, hp=250, wave=0, countdown=15,
                betweenWaves=True, pending=0, spawnWait=0, kills=0, round=1, generation=1)
    if game == "cs2":
        for _ in range(5):
            spawn_bot(room)
    rooms[code] = room
    enter_room(uid, room)
    return room


def enter_room(uid, room):
    if uid not in room["players"] and len(room["players"]) >= 6:
        fail("Pokój jest pełny (6 graczy).")
    leave(uid)
    room["players"][uid] = player_state(uid, room["game"], len(room["players"]))
    presence[uid] = dict(seen=now(), room=room["code"])
    room["emptySince"] = 0


def ray_box(o, d, box):
    lo, hi = 0, 180
    for i, (center, size) in enumerate(zip(box[:3], box[3:])):
        a, b = center-size/2, center+size/2
        if abs(d[i]) < 1e-8:
            if not a <= o[i] <= b:
                return math.inf
        else:
            t1, t2 = (a-o[i])/d[i], (b-o[i])/d[i]
            lo, hi = max(lo, min(t1, t2)), min(hi, max(t1, t2))
            if lo > hi:
                return math.inf
    return lo


def blocked(o, d):
    return min((ray_box(o, d, b) for b in MAP if b[4] > .3), default=180)


def free(x, z):
    return not any(abs(x-b[0]) < b[3]/2+.8 and abs(z-b[2]) < b[5]/2+.8 for b in MAP if b[4] > 1)


def emit(room, kind, **kwargs):
    room["serial"] += 1
    room["fx"].append(dict(id=room["serial"], kind=kind, until=now()+1, **kwargs))
    room["fx"] = room["fx"][-40:]


def act(room, p, action):
    kind = action.get("kind")
    if room["phase"] != "playing" and kind not in ("chat", "restart"):
        return "Mecz jest już zakończony."
    if kind == "chat":
        text = clean(action.get("text"), 300)
        if text and now()-p.get("chatAt", 0) < .8:
            return "Za szybko piszesz. Odczekaj chwilę."
        if text and rude(text):
            strike(p["id"], "czat")
            return "Wiadomość zawiera niedozwolone słowa."
        if text:
            p["chatAt"] = now()
            room["serial"] += 1
            sender = user_view(p["id"])
            room["chat"].append(dict(id=room["serial"], sender=p["id"], name=sender["name"], role=sender["role"], text=text))
            room["chat"] = room["chat"][-60:]
        return
    if kind == "restart":
        if p["id"] != room["owner"] or room["phase"] == "playing":
            return
        uid, game, code, players, public = room["owner"], room["game"], room["code"], list(room["players"]), room["public"]
        fresh = create_room(uid, game, public)
        rooms.pop(fresh["code"])
        generation = room["generation"]+1
        room.update(fresh, code=code, generation=generation)
        room.pop("_bot_director", None)
        for i, pid in enumerate(players):
            room["players"][pid] = player_state(pid, game, i)
            presence[pid]["room"] = code
        return
    if kind == "respawn" and room["game"] == "cs2":
        p.update(x=-70, y=1.5, z=-70, hp=100, reloadUntil=0)
        return
    if room["game"] == "castle_defense":
        if kind == "build":
            tower = action.get("tower")
            spec = TOWERS.get(tower)
            x, z = round(number(action.get("x"))), round(number(action.get("z")))
            if not spec or len(room["turrets"]) >= 60 or room["gold"] < spec["cost"]:
                return "Za mało złota lub osiągnięto limit wież."
            if not 9 <= math.hypot(x, z) <= 54 or math.hypot(x-p["x"], z-p["z"]) > 7:
                return "Buduj w zasięgu 7 metrów, poza zamkiem."
            if any(math.hypot(t["x"]-x, t["z"]-z) < 3 for t in room["turrets"]):
                return "Wieże muszą być oddalone o 3 metry."
            room["serial"] += 1
            room["turrets"].append(dict(id=room["serial"], type=tower, x=x, z=z, level=1, cooldown=0))
            room["gold"] -= spec["cost"]
        elif kind == "upgrade":
            tower = min(room["turrets"], key=lambda t: math.hypot(t["x"]-p["x"], t["z"]-p["z"]), default=None)
            if not tower or math.hypot(tower["x"]-p["x"], tower["z"]-p["z"]) > 7:
                return "Podejdź do wieży, którą chcesz ulepszyć."
            cost = round(TOWERS[tower["type"]]["cost"]*.8*tower["level"])
            if tower["level"] >= 3 or room["gold"] < cost:
                return "Maksymalny poziom lub za mało złota."
            room["gold"] -= cost
            tower["level"] += 1
        elif kind == "sell":
            tower = min(room["turrets"], key=lambda t: math.hypot(t["x"]-p["x"],t["z"]-p["z"]), default=None)
            if not tower or math.hypot(tower["x"]-p["x"],tower["z"]-p["z"]) > 7:
                return "Podejdź do wieży, którą chcesz sprzedać."
            if action.get("towerId") != tower["id"]:
                return "Najbliższa wieża się zmieniła. Otwórz sprzedaż ponownie."
            base = TOWERS[tower["type"]]["cost"]
            invested = base + sum(round(base*.8*level) for level in range(1,tower["level"]))
            room["gold"] += invested*7//10
            room["turrets"].remove(tower)
        elif kind == "repair":
            if room["gold"] < 100 or room["hp"] >= 250:
                return "Naprawa wymaga uszkodzenia zamku i 100 złota."
            room["gold"] -= 100
            room["hp"] = min(250, room["hp"]+60)
        elif kind == "next" and room["betweenWaves"]:
            room["gold"] += math.floor(room["countdown"])*2
            room["countdown"] = 0
        return
    w = p["weapons"][p["currentWeapon"]]
    spec = WEAPONS[w["id"]]
    if kind == "switch":
        index = int(number(action.get("index"), -1, -1, 20))
        if 0 <= index < len(p["weapons"]):
            p["currentWeapon"] = index
            p["reloadUntil"] = 0
    elif kind == "reload":
        if w["ammo"] < spec["ammo"] and p["reloadUntil"] <= now():
            p["reloadUntil"] = now()+spec["reload"]
    elif kind == "buy":
        item = action.get("item")
        if math.hypot(p["x"]+70, p["z"]+70) > 17:
            return "Zakupy są dostępne tylko w żółtej bazie."
        if item == "kevlar":
            if p["money"] < 650 or p.get("kevlar"):
                return "Za mało pieniędzy lub masz już pancerz."
            p["money"] -= 650
            p["kevlar"] = True
            p["hp"] = min(150, p["hp"]+50)
        elif item in WEAPONS:
            owned = next((i for i, v in enumerate(p["weapons"]) if v["id"] == item), None)
            if owned is not None:
                p["currentWeapon"] = owned
                p["reloadUntil"] = 0
                return
            if p["money"] < WEAPONS[item]["price"]:
                return "Za mało pieniędzy na tę broń."
            p["money"] -= WEAPONS[item]["price"]
            p["weapons"].append(dict(id=item, ammo=WEAPONS[item]["ammo"]))
            p["currentWeapon"] = len(p["weapons"])-1
            p["reloadUntil"] = 0
    elif kind == "shoot":
        if p["reloadUntil"] > now() or p["shootUntil"] > now() or w["ammo"] <= 0:
            return
        origin, direction = action.get("origin"), action.get("direction")
        if not isinstance(origin, list) or not isinstance(direction, list) or len(origin) != 3 or len(direction) != 3:
            return
        o = [number(v) for v in origin]
        d = [number(v) for v in direction]
        length = math.sqrt(sum(v*v for v in d))
        if length < .1 or math.hypot(o[0]-p["x"], o[2]-p["z"]) > 5 or abs(o[1]-p["y"]) > 8:
            return
        d = [v/length for v in d]
        w["ammo"] -= 1
        p["shootUntil"] = now()+spec["cooldown"]
        distance, target, head = blocked(o, d), None, False
        for enemy in room["enemies"]:
            for y, size, is_head in [(enemy["y"]+1.5, (1.65, 2, .9), False), (enemy["y"]+2.6, (.75, .75, .75), True)]:
                hit = ray_box(o, d, [enemy["x"], y, enemy["z"], *size])
                if hit < distance:
                    distance, target, head = hit, enemy, is_head
        endpoint = [o[i]+d[i]*min(distance, 140) for i in range(3)]
        emit(room, "shot", origin=o, end=endpoint, player=p["id"], hit=bool(target))
        stats = p.setdefault("aim", dict(shots=0, hits=0, heads=0))
        stats["shots"] += 1
        stats["hits"] += bool(target)
        stats["heads"] += bool(target and head)
        if stats["shots"] >= 40 and stats["heads"] >= stats["shots"]*.9:
            # Bots move and strafe; 90% headshots over 40+ shots is an aimbot.
            kick(p["id"], "Wykryto nienaturalną celność (aimbot). Zostałeś usunięty z pokoju.")
            return
        if target:
            damage = spec["headshot"] if head else spec["damage"]
            target["hp"] -= damage
            if target["hp"] <= 0:
                room["enemies"].remove(target)
                room["kills"] += 1
                p["kills"] += 1
                p["money"] += 300
                room["round"] = min(6, 1+room["kills"]//4)
                if room["kills"] >= 20:
                    room["phase"] = "won"
                else:
                    spawn_bot(room)


def tick(room, dt):
    room["revision"] += 1
    room["fx"] = [fx for fx in room["fx"] if fx["until"] > now()]
    if room["phase"] != "playing" or not room["players"]:
        return
    if room["game"] == "castle_defense":
        if room["betweenWaves"]:
            room["countdown"] = max(0, room["countdown"]-dt)
            if room["countdown"] <= 0:
                room.update(betweenWaves=False, wave=room["wave"]+1, spawnWait=0)
                room["pending"] = min(28, 4+room["wave"]*2)
        else:
            room["spawnWait"] -= dt
            if room["pending"] > 0 and room["spawnWait"] <= 0:
                boss = room["wave"]%5 == 0 and room["pending"] == 1
                angle = random.random()*math.tau
                hp = (36+room["wave"]*12)*(5 if boss else 1)
                room["serial"] += 1
                room["enemies"].append(dict(id=room["serial"], x=math.cos(angle)*51, z=math.sin(angle)*51,
                    hp=hp, maxHp=hp, boss=boss, cooldown=1, slowUntil=0, burnUntil=0))
                room["pending"] -= 1
                room["spawnWait"] = .55
            for e in list(room["enemies"]):
                if e["burnUntil"] > now():
                    e["hp"] -= 20*dt
                distance = math.hypot(e["x"], e["z"])
                if distance > 8.5:
                    speed = (2.1+room["wave"]*.15)*(.65 if e["boss"] else 1)*(.5 if e["slowUntil"] > now() else 1)
                    e["x"] -= e["x"]/distance*speed*dt
                    e["z"] -= e["z"]/distance*speed*dt
                else:
                    e["cooldown"] -= dt
                    if e["cooldown"] <= 0:
                        room["hp"] = max(0, room["hp"]-(12 if e["boss"] else 4))
                        e["cooldown"] = 1.2
            for t in room["turrets"]:
                t["cooldown"] -= dt
                spec = TOWERS[t["type"]]
                e = min(room["enemies"], key=lambda e: math.hypot(e["x"]-t["x"], e["z"]-t["z"]), default=None)
                if e and t["cooldown"] <= 0 and math.hypot(e["x"]-t["x"], e["z"]-t["z"]) < spec["range"]+2*(t["level"]-1):
                    t["cooldown"] = spec["cooldown"]*(.85**(t["level"]-1))
                    damage = spec["damage"]*(1.6**(t["level"]-1))
                    for enemy in room["enemies"]:
                        if enemy is e or (t["type"] == "cannon" and math.hypot(e["x"]-enemy["x"], e["z"]-enemy["z"]) < 5):
                            enemy["hp"] -= damage
                    if t["type"] == "ice":
                        e["slowUntil"] = now()+3
                    if t["type"] == "fire":
                        e["burnUntil"] = now()+4
                    emit(room, "tower", origin=[t["x"], 2.5, t["z"]], end=[e["x"], 2, e["z"]])
            dead = [e for e in room["enemies"] if e["hp"] <= 0]
            room["gold"] += sum(90 if e["boss"] else 20 for e in dead)
            room["enemies"] = [e for e in room["enemies"] if e["hp"] > 0]
            if room["hp"] <= 0:
                room["phase"] = "lost"
            elif room["pending"] == 0 and not room["enemies"]:
                room["gold"] += 60+room["wave"]*5
                room.update(betweenWaves=True, countdown=12)
                if room["wave"] >= 20:
                    room["phase"] = "won"
    else:
        for p in room["players"].values():
            if 0 < p["reloadUntil"] <= now():
                w = p["weapons"][p["currentWeapon"]]
                w["ammo"] = WEAPONS[w["id"]]["ammo"]
                p["reloadUntil"] = 0
        if "_bot_director" not in room:
            room["_bot_director"] = BotDirector(MAP)
        director = room["_bot_director"]
        def sight(enemy, player):
            origin = [enemy["x"],3,enemy["z"]]
            delta = [player["x"]-origin[0],player["y"]+2-origin[1],player["z"]-origin[2]]
            length = math.sqrt(sum(v*v for v in delta)) or 1
            return blocked(origin,[v/length for v in delta]) >= length-.25
        def bot_fire(enemy, player, hit):
            origin, end = [enemy["x"],3,enemy["z"]], [player["x"],player["y"]+2,player["z"]]
            if hit and now() >= player.get("shieldUntil",0):
                player["hp"] -= 5 if player.get("kevlar") else 8
            else:
                end[0] += random.choice([-1,1])*2
            emit(room,"bot",origin=origin,end=end,enemy=enemy["id"])
            if player["hp"] <= 0:
                player.update(hp=100,x=-70,y=1.5,z=-70,deaths=player["deaths"]+1,reloadUntil=0,shieldUntil=now()+2.5)
                player["money"] = max(0,player["money"]-200)
                player["kevlar"] = False
        director.update(room["enemies"],list(room["players"].values()),dt,now(),sight,bot_fire)


ROUND = {"x", "y", "z", "rotY", "rot", "hp", "countdown"}


def compact(item):
    return {k: round(v, 2) if k in ROUND and isinstance(v, float) else v for k, v in item.items()}


def public_room(room):
    players = []
    for p in room["players"].values():
        public = compact({k: p[k] for k in ("id", "x", "y", "z", "rotY", "hp", "kills", "deaths", "moving", "dancing")})
        public.update(user_view(p["id"]) or {})
        players.append(public)
    view = {k: room[k] for k in ("code", "game", "owner", "public", "revision", "phase", "gold", "hp", "wave", "countdown", "betweenWaves", "pending", "kills", "round", "generation", "turrets", "fx")}
    view["countdown"] = round(view["countdown"], 2)
    view["enemies"] = [compact(e) for e in room["enemies"]]
    view["chat"] = room["chat"][-20:]
    return view | dict(players=players)


def private_view(p):
    return {k: p[k] for k in ("id", "money", "weapons", "currentWeapon", "sequence", "acknowledgements")} | dict(reloadRemaining=round(max(0, p["reloadUntil"]-now()), 2))


def room_view(room, uid):
    if not room:
        return None
    view = public_room(room)
    if uid in room["players"]:
        me = private_view(room["players"][uid])
        view["players"] = [p | me if p["id"] == uid else p for p in view["players"]]
    return view


def broadcast():
    """Push each room's state to its connected players: the shared part is
    encoded once per room, only the small personal part per player."""
    for room in rooms.values():
        listeners = [uid for uid in room["players"] if uid in sockets]
        if not listeners:
            continue
        shared = json.dumps(public_room(room), separators=(",", ":"))
        for uid in listeners:
            conn = sockets[uid]
            conn["latest"] = '{"type":"room","room":' + shared + ',"me":' + json.dumps(private_view(room["players"][uid]), separators=(",", ":")) + '}'
            conn["event"].set()


async def simulation():
    previous = now()
    while True:
        await asyncio.sleep(.05)
        current = now()
        dt, previous = min(.2, current-previous), current
        for uid, p in list(presence.items()):
            if p.get("room") and current-p["seen"] > 20:
                leave(uid)
        for code, room in list(rooms.items()):
            tick(room, dt)
            if room["emptySince"] and current-room["emptySince"] > 180:
                rooms.pop(code, None)
        broadcast()
        if len(cheat_strikes) > 5000:
            cheat_strikes.clear()
        if len(coin_buckets) > 20000:
            coin_buckets.clear()
        if len(rates) > 10000:
            rates.clear()
        if len(login_failures) > 10000:
            login_failures.clear()
        # Caches refill from the database on demand; the caps only bound memory.
        if len(relation_cache) > 2000:
            relation_cache.clear()
        if len(user_cache) > 20000 or len(token_cache) > 20000:
            user_cache.clear()
            token_cache.clear()


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(simulation())
    yield
    task.cancel()
    db.close()


app = FastAPI(lifespan=lifespan)
origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["POST", "GET", "OPTIONS"], allow_headers=["Content-Type", "Authorization"])


@app.exception_handler(HTTPException)
async def error_response(request, exc):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    # Details go to the Render log only; players get a short, safe message.
    log.exception("Unhandled error in %s", request.url.path)
    return JSONResponse({"error": "Błąd serwera. Spróbuj ponownie za chwilę."}, status_code=500)


async def socket_writer(conn):
    ws = conn["ws"]
    while True:
        await conn["event"].wait()
        conn["event"].clear()
        if conn.get("pong") is not None:
            await ws.send_text(json.dumps(dict(type="pong", t=conn.pop("pong"))))
        if conn.get("notice"):
            await ws.send_text(json.dumps(dict(type="notice", text=conn.pop("notice"))))
        if conn.get("latest"):
            text, conn["latest"] = conn["latest"], None
            await ws.send_text(text)


@app.websocket("/ws")
async def room_socket(ws: WebSocket):
    """Live room connection: the client streams input, the server pushes state 20 times a second."""
    # The page served by this server (same host) and the configured sites may connect.
    origin = ws.headers.get("origin")
    same_host = bool(origin) and origin.split("://", 1)[-1] == ws.headers.get("host", "")
    if origins != ["*"] and origin and origin not in origins and not same_host:
        await ws.close(code=1008)
        return
    await ws.accept()
    uid, conn, writer = None, None, None
    try:
        first = await asyncio.wait_for(ws.receive(), 15)
        if first.get("type") == "websocket.disconnect":
            return
        hello = json.loads(first.get("text") or (first.get("bytes") or b"").decode() or "null")
        token = hello.get("token") if isinstance(hello, dict) else None
        uid = token_user(token) if isinstance(token, str) and len(token) <= 150 else None
        if not uid or not profile(uid):
            await ws.close(code=4401)
            return
        conn = dict(ws=ws, latest=None, event=asyncio.Event(), times=deque())
        previous = sockets.get(uid)
        sockets[uid] = conn
        if previous:
            previous["latest"] = None
            await previous["ws"].close(code=4000)
        writer = asyncio.create_task(socket_writer(conn))
        await ws.send_text(json.dumps(dict(type="ready", id=uid)))
        while True:
            text = await ws.receive_text()
            times = conn["times"]
            times.append(now())
            while times and times[0] < now()-1:
                times.popleft()
            if len(text) > 12000 or len(times) > 60:
                strike(uid, "spam", f"{len(times)}/s")
                break
            try:
                message = json.loads(text)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            presence.setdefault(uid, dict(seen=now(), room=None))["seen"] = now()
            if message.get("type") == "ping":
                conn["pong"] = number(message.get("t"), 0, 0, 1e13)
                conn["event"].set()
            elif message.get("type") == "in":
                try:
                    room_input(uid, message)
                except HTTPException:
                    pass
    except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, RuntimeError):
        pass
    finally:
        if writer:
            writer.cancel()
        if uid and sockets.get(uid) is conn:
            sockets.pop(uid, None)


@app.get("/health")
async def health():
    db.execute("SELECT 1").fetchone()
    return dict(ok=True, version=19, ai=bool(AI_URL and AI_KEY), sockets=len(sockets), rooms=len(rooms),
                storage="postgresql" if os.environ.get("DATABASE_URL") else "sqlite")


@app.get("/")
async def homepage():
    return FileResponse(ROOT / "public" / "index.html", headers={"Cache-Control": "no-cache"})


@app.post("/api/{operation}")
async def api(operation: str, request: Request):
    raw = await request.body()
    # A published Studio game (parts + NexusScript) may be larger than other requests.
    if len(raw) > (220000 if operation in ("games_publish", "projects_save") else 40000):
        fail("Żądanie jest zbyt duże.", 413)
    try:
        body = json.loads(raw or "{}")
    except Exception:
        fail("Nieprawidłowy JSON.")
    if not isinstance(body, dict):
        fail("Nieprawidłowe dane.")
    identity = request.headers.get("x-visitor-id") if TRUST_VISITOR else None
    rate_key = body.get("token") or request.headers.get("authorization") or identity or request.client.host
    rate_key = ("session:" if operation == "session" else "api:")+hashlib.sha256(str(rate_key)[:200].encode()).hexdigest()
    q = rates[rate_key]
    while q and q[0] < now()-60:
        q.popleft()
    # New sessions are limited per address; a whole class behind one school
    # address must still be able to connect within a minute.
    if len(q) > (60 if operation == "session" else 1000):
        fail("Za dużo żądań. Spróbuj za chwilę.", 429)
    q.append(now())
    if operation == "session":
        token = body.get("token", "")
        if not isinstance(token, str) or len(token) > 150:
            fail("Nieprawidłowy kod sesji.")
        identity = identity+":"+clean(body.get("scope", "main"), 54) if identity else None
        visitor_hash = hashlib.sha256(identity.encode()).hexdigest() if identity else None
        if not token and identity:
            token = hmac.new(SERVER_SECRET, identity.encode(), hashlib.sha256).hexdigest()
        uid = token_user(token)
        if not uid:
            if body.get("token"):
                fail("Nieprawidłowy kod konta online.", 401)
            token = token or secrets.token_urlsafe(32)
            preferred = clean(body.get("id"), 54).upper()
            uid = preferred if re.fullmatch(r"BLOX-[A-Z0-9_-]{3,48}", preferred) else "BLOX-"+secrets.token_hex(5).upper()
            if db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                uid = "BLOX-"+secrets.token_hex(5).upper()
            db.execute("INSERT INTO users(id,token_hash,visitor_hash,name,avatar,created) VALUES(?,?,?,?,?,?)", (uid, hash_token(token), visitor_hash, clean(body.get("name"), 16) or "Gracz", json.dumps(avatar(body.get("avatar"))), time.time()))
            db.commit()
        elif not body.get("keepProfile"):
            save_profile(uid, body.get("name"), body.get("avatar"))
        presence.setdefault(uid, dict(seen=now(), room=None))["seen"] = now()
        return dict(token=token, user=user_view(uid), social=social(uid), account=account_view(uid),
                    progress=profile(uid)["progress"])
    if operation == "login":
        login, password = credentials(body)
        # One login may fail 10 times, one address 30 times (a school or home
        # network shares an address), per 15 minutes.
        buckets = [(login_failures[login], 10), (login_failures["ip:"+str(request.client.host)], 30)]
        for attempts, limit in buckets:
            while attempts and attempts[0] < now()-900:
                attempts.popleft()
            if len(attempts) >= limit:
                fail("Za dużo nieudanych prób logowania. Odczekaj 15 minut.", 429)
        row = db.execute("SELECT id,password_hash FROM users WHERE login=?", (login,)).fetchone()
        # The hash runs even for unknown logins so timing does not reveal them.
        valid = await asyncio.to_thread(password_ok, password, row["password_hash"] if row else DUMMY_HASH)
        if not row or not valid:
            for attempts, _ in buckets:
                attempts.append(now())
            fail("Nieprawidłowy login lub hasło.", 401)
        buckets[0][0].clear()
        uid, token = row["id"], secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions(token_hash,user_id,created) VALUES(?,?,?)", (hash_token(token), uid, time.time()))
        db.commit()
        token_cache[hash_token(token)] = uid
        presence.setdefault(uid, dict(seen=now(), room=None))["seen"] = now()
        return dict(token=token, user=user_view(uid), social=social(uid), account=account_view(uid),
                    progress=profile(uid)["progress"])
    user = auth(request, body)
    uid = user["id"]
    presence.setdefault(uid, dict(seen=now(), room=None))["seen"] = now()
    if operation == "register":
        if user["login"]:
            fail("To konto ma już login. Zaloguj się nim na innych urządzeniach.")
        login, password = credentials(body)
        if db.execute("SELECT 1 FROM users WHERE login=?", (login,)).fetchone():
            fail("Ten login jest już zajęty. Wybierz inny.", 409)
        stored = await asyncio.to_thread(password_hash, password)
        db.execute("UPDATE users SET login=?,password_hash=? WHERE id=? AND login IS NULL", (login, stored, uid))
        db.commit()
        user["login"] = login
        return dict(account=account_view(uid), user=user_view(uid))
    if operation == "logout":
        token = request.headers.get("authorization", "").removeprefix("Bearer ") or body.get("token", "")
        db.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(token),))
        db.commit()
        token_cache.pop(hash_token(token), None)
        leave(uid)
        return dict(ok=True)
    if operation == "sync":
        if body.get("profile"):
            changes = body["profile"]
            if isinstance(changes, dict):
                save_profile(uid, changes.get("name"), changes.get("avatar"))
        if body.get("progress"):
            save_progress(uid, body["progress"])
        room = room_input(uid, body)
        notice = presence.get(uid, {}).pop("notice", None)
        # With a live socket the room travels there; /sync only carries the rest.
        return dict(user=user_view(uid), room=room_view(room, uid) if body.get("room", True) else None,
                    inRoom=bool(room), notice=notice, progress=user["progress"],
                    social=social(uid) if body.get("social", True) else None,
                    rooms=[dict(code=r["code"], game=r["game"], count=len(r["players"]), phase=r["phase"]) for r in rooms.values() if r["public"] and r["players"] and len(r["players"]) < 6][:20])
    if operation == "search":
        query = clean(body.get("query"), 54)
        if len(query) < 2:
            fail("Wpisz co najmniej 2 znaki.")
        if query.isdigit():
            query = "BLOX-"+query
        found = db.execute("SELECT id FROM users WHERE id=? COLLATE NOCASE OR fold(name)=? LIMIT 12", (query, query.casefold())).fetchall()
        if not found:
            # Literal prefix match: wildcard characters are escaped.
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            found = db.execute("SELECT id FROM users WHERE fold(name) LIKE ? ESCAPE '\\' LIMIT 12", (escaped.casefold()+"%",)).fetchall()
        return dict(users=[user_view(r["id"]) for r in found if r["id"] != uid])
    if operation == "friend":
        target, kind = clean(body.get("target"), 54).upper(), body.get("action")
        if target == uid:
            fail("Nie możesz dodać siebie.")
        if not db.execute("SELECT 1 FROM users WHERE id=?", (target,)).fetchone():
            fail("Nie znaleziono tego ID.", 404)
        if kind == "request":
            if relation(uid, target):
                fail("Ten gracz jest już znajomym.")
            if db.execute("SELECT COUNT(*) FROM requests WHERE sender=?", (uid,)).fetchone()[0] >= 100:
                fail("Masz już 100 oczekujących zaproszeń.")
            if db.execute("SELECT 1 FROM requests WHERE sender=? AND target=?", (target, uid)).fetchone():
                a, b = sorted((uid, target))
                db.execute("INSERT OR IGNORE INTO friends VALUES(?,?)", (a, b))
                db.execute("DELETE FROM requests WHERE (sender=? AND target=?) OR (sender=? AND target=?)", (uid, target, target, uid))
            else:
                db.execute("INSERT OR IGNORE INTO requests VALUES(?,?,?)", (uid, target, time.time()))
        elif kind == "accept":
            if not db.execute("SELECT 1 FROM requests WHERE sender=? AND target=?", (target, uid)).fetchone():
                fail("Zaproszenie nie jest już aktualne.")
            a, b = sorted((uid, target))
            db.execute("INSERT OR IGNORE INTO friends VALUES(?,?)", (a, b))
            db.execute("DELETE FROM requests WHERE (sender=? AND target=?) OR (sender=? AND target=?)", (uid, target, target, uid))
        elif kind == "decline":
            db.execute("DELETE FROM requests WHERE sender=? AND target=?", (target, uid))
        elif kind == "cancel":
            db.execute("DELETE FROM requests WHERE sender=? AND target=?", (uid, target))
        elif kind == "remove":
            a, b = sorted((uid, target))
            db.execute("DELETE FROM friends WHERE a=? AND b=?", (a, b))
        else:
            fail("Nieznana operacja.")
        db.commit()
        forget_relations(uid, target)
        return dict(social=social(uid))
    if operation == "message":
        target, text = clean(body.get("target"), 54).upper(), clean(body.get("text"), 1000)
        if not text:
            fail("Wiadomość jest pusta.")
        if not relation(uid, target):
            fail("Wiadomości możesz wysyłać tylko znajomym.", 403)
        # Client-generated idempotency key is not needed for reads; sends use
        # a dedicated call and are never automatically retried.
        db.execute("INSERT INTO messages(sender,target,text,created) VALUES(?,?,?,?)", (uid, target, text, time.time()))
        db.commit()
        forget_relations(uid, target)
        return dict(social=social(uid))
    if operation == "games_publish":
        title, description = clean(body.get("title"), 40), clean(body.get("description"), 300)
        if len(title) < 3:
            fail("Tytuł musi mieć co najmniej 3 znaki.")
        data = game_data(body.get("game"))
        if rude(title, description, data["script"], *[p.get("n", "") for p in data["parts"]]):
            fail("Tytuł, opis lub tekst w grze zawiera niedozwolone słowa.")
        times = game_publish_times[uid]
        while times and times[0] < now()-3600:
            times.popleft()
        if len(times) >= 15:
            fail("Możesz opublikować najwyżej 15 wersji gier na godzinę.", 429)
        game_id = clean(body.get("id"), 12).upper()
        existing = db.execute("SELECT author,hidden FROM published_games WHERE id=?", (game_id,)).fetchone() if game_id else None
        stamp = time.time()
        if existing:
            if existing["author"] != uid:
                fail("Możesz aktualizować tylko własne gry.", 403)
            if existing["hidden"] == 1:
                fail("Ta gra została ukryta po zgłoszeniach i czeka na sprawdzenie.", 403)
            db.execute("UPDATE published_games SET title=?,description=?,data=?,updated=?,hidden=0,revision=revision+1,cover=COALESCE(?,cover) WHERE id=?",
                       (title, description, json.dumps(data), stamp, cover_data(body.get("cover")), game_id))
        else:
            if db.execute("SELECT COUNT(*) FROM published_games WHERE author=? AND hidden<>2", (uid,)).fetchone()[0] >= 20:
                fail("Masz już 20 opublikowanych gier. Wycofaj jedną, aby dodać nową.")
            game_id = "G-"+secrets.token_hex(3).upper()
            db.execute("INSERT INTO published_games(id,author,title,description,data,created,updated,plays,reports,hidden,revision,cover) VALUES(?,?,?,?,?,?,?,0,0,0,1,?)",
                       (game_id, uid, title, description, json.dumps(data), stamp, stamp, cover_data(body.get("cover"))))
        db.commit()
        times.append(now())
        revision = db.execute("SELECT revision FROM published_games WHERE id=?", (game_id,)).fetchone()["revision"]
        return dict(id=game_id, revision=revision, updated=stamp)
    if operation == "games_list":
        order = "plays DESC, updated DESC" if body.get("sort") == "popular" else "updated DESC"
        query = clean(body.get("query"), 40).casefold()
        rows = db.execute(f"SELECT id,author,title,description,plays,created,updated,hidden,revision,cover FROM published_games WHERE hidden=0 ORDER BY {order} LIMIT 200").fetchall()
        games = [game_card(r) for r in rows if not query or query in r["title"].casefold()][:60]
        mine = [game_card(r) for r in db.execute("SELECT id,author,title,description,plays,created,updated,hidden,revision,cover FROM published_games WHERE author=? AND hidden<>2 ORDER BY updated DESC", (uid,)).fetchall()]
        return dict(games=games, mine=mine)
    if operation == "games_get":
        game_id = clean(body.get("id"), 12).upper()
        row = db.execute("SELECT * FROM published_games WHERE id=?", (game_id,)).fetchone()
        # Staff can open hidden games to review reports.
        if not row or (row["hidden"] and row["author"] != uid and user["role"] not in ROLES):
            fail("Nie znaleziono tej gry albo została ukryta.", 404)
        if (uid, game_id) not in game_plays_seen:
            game_plays_seen.add((uid, game_id))
            db.execute("UPDATE published_games SET plays=plays+1 WHERE id=?", (game_id,))
            db.commit()
        return dict(card=game_card(row), game=json.loads(row["data"]))
    if operation == "games_report":
        game_id = clean(body.get("id"), 12).upper()
        row = db.execute("SELECT author FROM published_games WHERE id=?", (game_id,)).fetchone()
        if not row:
            fail("Nie znaleziono tej gry.", 404)
        if row["author"] == uid:
            fail("Nie możesz zgłosić własnej gry.")
        if not db.execute("SELECT 1 FROM game_reports WHERE game_id=? AND reporter=?", (game_id, uid)).fetchone():
            db.execute("INSERT INTO game_reports(game_id,reporter,reason,created) VALUES(?,?,?,?)",
                       (game_id, uid, clean(body.get("reason"), 200), time.time()))
            # Three different players hide the game until an administrator checks it.
            db.execute("UPDATE published_games SET reports=reports+1, hidden=CASE WHEN reports+1>=3 AND hidden=0 THEN 1 ELSE hidden END WHERE id=?", (game_id,))
            db.commit()
        return dict(ok=True)
    if operation == "games_unpublish":
        game_id = clean(body.get("id"), 12).upper()
        row = db.execute("SELECT author FROM published_games WHERE id=?", (game_id,)).fetchone()
        if not row or row["author"] != uid:
            fail("Możesz wycofać tylko własną grę.", 403)
        # Withdrawn games stay stored (hidden=2), nothing is deleted.
        db.execute("UPDATE published_games SET hidden=2 WHERE id=? AND hidden<>1", (game_id,))
        db.commit()
        return dict(ok=True)
    if operation == "ai_code":
        if not AI_URL or not AI_KEY:
            fail("Asystent AI na serwerze nie jest jeszcze włączony. Użyj asystenta wbudowanego lub promptu dla AI.", 503)
        prompt, code = clean(body.get("prompt"), 600), str(body.get("code") or "")[:8000]
        if len(prompt) < 3:
            fail("Opisz, co ma zrobić AI.")
        if rude(prompt):
            fail("Prośba zawiera niedozwolone słowa.")
        calls = ai_calls[uid]
        while calls and calls[0] < now()-600:
            calls.popleft()
        while ai_daily and ai_daily[0] < now()-86400:
            ai_daily.popleft()
        if len(calls) >= 6:
            fail("Limit: 6 próśb do AI na 10 minut. Spróbuj za chwilę.", 429)
        if len(ai_daily) >= AI_DAILY_LIMIT:
            fail("Dzienny limit AI na serwerze został wyczerpany. Wróć jutro albo użyj promptu dla innego AI.", 429)
        calls.append(now())
        ai_daily.append(now())
        try:
            answer = await asyncio.to_thread(ai_request, prompt, code)
        except Exception:
            log.exception("AI worker request failed")
            fail("Serwer AI nie odpowiedział. Spróbuj ponownie za chwilę.", 502)
        text = str(answer.get("text") or "")[:20000] if isinstance(answer, dict) else ""
        if not text:
            fail("AI nie zwróciło kodu. Spróbuj opisać grę inaczej.", 502)
        return dict(text=text)
    if operation == "projects_list":
        rows = db.execute("SELECT id,name,updated FROM studio_projects WHERE user_id=? ORDER BY updated DESC", (uid,)).fetchall()
        return dict(projects=[dict(id=r["id"], name=r["name"], updated=r["updated"]) for r in rows])
    if operation == "projects_get":
        row = db.execute("SELECT data FROM studio_projects WHERE user_id=? AND id=?", (uid, clean(body.get("id"), 40))).fetchone()
        if not row:
            fail("Nie znaleziono projektu w chmurze.", 404)
        return dict(project=json.loads(row["data"]))
    if operation == "projects_save":
        data = project_data(body.get("project"))
        exists = db.execute("SELECT 1 FROM studio_projects WHERE user_id=? AND id=?", (uid, data["id"])).fetchone()
        if exists:
            db.execute("UPDATE studio_projects SET name=?,data=?,updated=? WHERE user_id=? AND id=?",
                       (data["name"], json.dumps(data), data["updated"], uid, data["id"]))
        else:
            if db.execute("SELECT COUNT(*) FROM studio_projects WHERE user_id=?", (uid,)).fetchone()[0] >= 20:
                fail("W chmurze mieści się 20 projektów. Usuń jeden, aby zapisać nowy.")
            db.execute("INSERT INTO studio_projects(user_id,id,name,data,updated) VALUES(?,?,?,?,?)",
                       (uid, data["id"], data["name"], json.dumps(data), data["updated"]))
        db.commit()
        return dict(ok=True, id=data["id"], updated=data["updated"])
    if operation == "projects_delete":
        # A player removes their own private project; published games are separate.
        db.execute("DELETE FROM studio_projects WHERE user_id=? AND id=?", (uid, clean(body.get("id"), 40)))
        db.commit()
        return dict(ok=True)
    if operation == "admin_overview":
        staff(user)
        count = lambda q: db.execute(q).fetchone()[0]
        return dict(role=user["role"], users=count("SELECT COUNT(*) FROM users"), banned=count("SELECT COUNT(*) FROM users WHERE banned=1"),
                    games=count("SELECT COUNT(*) FROM published_games WHERE hidden=0"), hiddenGames=count("SELECT COUNT(*) FROM published_games WHERE hidden=1"),
                    online=sum(1 for p in presence.values() if now()-p.get("seen", 0) < 15), rooms=len(rooms), sockets=len(sockets),
                    staff=[admin_user_view(r["id"]) for r in db.execute("SELECT id FROM users WHERE role IS NOT NULL").fetchall()],
                    anticheat=list(anticheat_log)[-40:][::-1])
    if operation == "admin_games":
        staff(user)
        rows = db.execute("SELECT id,author,title,description,plays,created,updated,hidden,revision,reports FROM published_games WHERE hidden=1 OR reports>0 ORDER BY hidden DESC, reports DESC, updated DESC LIMIT 100").fetchall()
        games = []
        for r in rows:
            card = game_card(r) | dict(reports=r["reports"])
            card["reasons"] = [dict(reporter=x["reporter"], reason=x["reason"]) for x in db.execute("SELECT reporter,reason FROM game_reports WHERE game_id=? ORDER BY created DESC LIMIT 10", (r["id"],)).fetchall()]
            games.append(card)
        return dict(games=games)
    if operation == "admin_game":
        staff(user)
        game_id, action = clean(body.get("id"), 12).upper(), body.get("action")
        if not db.execute("SELECT 1 FROM published_games WHERE id=?", (game_id,)).fetchone():
            fail("Nie znaleziono gry.", 404)
        if action == "show":
            db.execute("UPDATE published_games SET hidden=0, reports=0 WHERE id=?", (game_id,))
        elif action == "hide":
            db.execute("UPDATE published_games SET hidden=1 WHERE id=?", (game_id,))
        else:
            fail("Nieznana operacja.")
        db.commit()
        log.warning("staff %s %s game %s", uid, action, game_id)
        return dict(ok=True)
    if operation == "admin_user":
        staff(user)
        query = clean(body.get("query"), 54)
        if query.isdigit():
            query = "BLOX-"+query
        rows = db.execute("SELECT id FROM users WHERE id=? COLLATE NOCASE OR fold(name)=? OR login=? LIMIT 10", (query, query.casefold(), query.casefold())).fetchall()
        return dict(users=[admin_user_view(r["id"]) for r in rows])
    if operation in ("admin_kick", "admin_ban", "admin_role"):
        staff(user, "admin" if operation == "admin_kick" else "owner")
        target = clean(body.get("target"), 54).upper()
        other = profile(target)
        if not other:
            fail("Nie znaleziono gracza.", 404)
        if other["role"] == "owner":
            fail("Konta właściciela nie można zmieniać.", 403)
        if operation == "admin_kick":
            if other["role"] and user["role"] != "owner":
                fail("Administratora może wyrzucić tylko właściciel.", 403)
            kick(target, "Administrator usunął cię z pokoju.")
        elif operation == "admin_ban":
            banned = body.get("banned") is True
            db.execute("UPDATE users SET banned=? WHERE id=?", (1 if banned else 0, target))
            db.commit()
            other["banned"] = banned
            if banned:
                kick(target, "To konto zostało zablokowane.")
                for digest in [k for k, v in token_cache.items() if v == target]:
                    token_cache.pop(digest, None)
        else:
            role = "admin" if body.get("role") == "admin" else None
            db.execute("UPDATE users SET role=? WHERE id=?", (role, target))
            db.commit()
            other["role"] = role
        log.warning("staff %s %s %s %s", uid, operation, target, body.get("banned", body.get("role", "")))
        return dict(user=admin_user_view(target))
    if operation == "room":
        action = body.get("action")
        if action == "leave":
            leave(uid)
            return dict(room=None)
        if action == "create":
            game = body.get("game")
            if game not in GAME_IDS:
                fail("Ta gra nie obsługuje jeszcze multiplayera.")
            room = create_room(uid, game, body.get("public") is True)
        elif action in ("join", "friend"):
            code = clean(body.get("code"), 12).upper()
            if action == "friend":
                target = clean(body.get("target"), 54).upper()
                if not relation(uid, target):
                    fail("Ten gracz nie jest znajomym.", 403)
                code = (user_view(target) or {}).get("roomCode")
            room = rooms.get(code)
            if not room or not room["players"]:
                fail("Nie znaleziono aktywnego pokoju. Sprawdź kod.", 404)
            enter_room(uid, room)
        else:
            fail("Nieznana operacja pokoju.")
        return dict(room=room_view(room, uid))
    fail("Nie znaleziono operacji.", 404)


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.WARNING)
    # Render's proxy is the only route in, so its X-Forwarded-For carries the
    # real player address that the per-IP rate limits need.
    behind_proxy = os.environ.get("RENDER") == "true"
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8093")), log_level="warning",
                proxy_headers=behind_proxy, forwarded_allow_ips="*" if behind_proxy else "127.0.0.1")
