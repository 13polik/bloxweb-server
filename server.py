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
import math
import os
import random
import re
import secrets
import time
from pathlib import Path
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
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
rooms = {}
presence = {}
rates = defaultdict(deque)
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


def auth(request, body):
    token = request.headers.get("authorization", "").removeprefix("Bearer ") or body.get("token", "")
    if not isinstance(token, str) or len(token) > 150:
        fail("Nieprawidłowa sesja.", 401)
    user = db.execute("SELECT * FROM users WHERE token_hash=?", (hash_token(token),)).fetchone()
    if not user:
        fail("Sesja wygasła. Połącz konto ponownie.", 401)
    return dict(user)


def user_view(uid):
    u = db.execute("SELECT id,name,avatar FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return None
    p = presence.get(uid, {})
    online = now() - p.get("seen", 0) < 15
    room = rooms.get(p.get("room", "")) if online else None
    return dict(id=u["id"], name=u["name"], avatar=json.loads(u["avatar"]),
                status="ingame" if room else "online" if online else "offline",
                gameId=room["game"] if room else None, roomCode=room["code"] if room else None)


def relation(a, b):
    a, b = sorted((a, b))
    return db.execute("SELECT 1 FROM friends WHERE a=? AND b=?", (a, b)).fetchone() is not None


def social(uid):
    fs = db.execute("SELECT a,b FROM friends WHERE a=? OR b=?", (uid, uid)).fetchall()
    ins = db.execute("SELECT sender FROM requests WHERE target=?", (uid,)).fetchall()
    outs = db.execute("SELECT target FROM requests WHERE sender=?", (uid,)).fetchall()
    msgs = db.execute("SELECT * FROM (SELECT * FROM messages WHERE sender=? OR target=? ORDER BY id DESC LIMIT 500) ORDER BY id", (uid, uid)).fetchall()
    return dict(friends=[user_view(r["b"] if r["a"] == uid else r["a"]) for r in fs],
                incoming=[user_view(r["sender"]) for r in ins],
                outgoing=[user_view(r["target"]) for r in outs], messages=[dict(r) for r in msgs])


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
        if text:
            room["serial"] += 1
            room["chat"].append(dict(id=room["serial"], sender=p["id"], name=user_view(p["id"])["name"], text=text))
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


def room_view(room, uid):
    if not room:
        return None
    players = []
    for p in room["players"].values():
        public = {k: p[k] for k in ("id", "x", "y", "z", "rotY", "hp", "kills", "deaths", "moving", "dancing")}
        public.update(user_view(p["id"]) or {})
        if p["id"] == uid:
            public.update({k: p[k] for k in ("money", "weapons", "currentWeapon", "sequence", "acknowledgements")})
            public["reloadRemaining"] = max(0, p["reloadUntil"]-now())
        players.append(public)
    return {k: room[k] for k in ("code", "game", "owner", "public", "revision", "phase", "gold", "hp", "wave", "countdown", "betweenWaves", "pending", "kills", "round", "generation", "enemies", "turrets", "fx", "chat")} | dict(players=players)


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
        if len(rates) > 10000:
            rates.clear()


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


@app.get("/health")
async def health():
    db.execute("SELECT 1").fetchone()
    return dict(ok=True, version=11, rooms=len(rooms),
                storage="postgresql" if os.environ.get("DATABASE_URL") else "sqlite")


@app.get("/")
async def homepage():
    return FileResponse(ROOT / "public" / "index.html", headers={"Cache-Control": "no-cache"})


@app.post("/api/{operation}")
async def api(operation: str, request: Request):
    raw = await request.body()
    if len(raw) > 40000:
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
    if len(q) > (25 if operation == "session" else 1000):
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
        existing = db.execute("SELECT * FROM users WHERE token_hash=?", (hash_token(token),)).fetchone() if token else None
        if not existing:
            if body.get("token"):
                fail("Nieprawidłowy kod konta online.", 401)
            token = token or secrets.token_urlsafe(32)
            preferred = clean(body.get("id"), 54).upper()
            uid = preferred if re.fullmatch(r"BLOX-[A-Z0-9_-]{3,48}", preferred) else "BLOX-"+secrets.token_hex(5).upper()
            if db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                uid = "BLOX-"+secrets.token_hex(5).upper()
            db.execute("INSERT INTO users VALUES(?,?,?,?,?,?)", (uid, hash_token(token), visitor_hash, clean(body.get("name"), 16) or "Gracz", json.dumps(avatar(body.get("avatar"))), time.time()))
            db.commit()
        else:
            uid = existing["id"]
            db.execute("UPDATE users SET name=?,avatar=? WHERE id=?", (clean(body.get("name"), 16) or existing["name"], json.dumps(avatar(body.get("avatar"))), uid))
            db.commit()
        presence.setdefault(uid, dict(seen=now(), room=None))["seen"] = now()
        return dict(token=token, user=user_view(uid), social=social(uid))
    user = auth(request, body)
    uid = user["id"]
    presence.setdefault(uid, dict(seen=now(), room=None))["seen"] = now()
    if operation == "sync":
        if body.get("profile"):
            profile = body["profile"]
            if isinstance(profile, dict):
                db.execute("UPDATE users SET name=?,avatar=? WHERE id=?", (clean(profile.get("name"), 16) or user["name"], json.dumps(avatar(profile.get("avatar"))), uid))
                db.commit()
        room = rooms.get(presence[uid].get("room"))
        if room and uid in room["players"]:
            p = room["players"][uid]
            p["seen"] = now()
            pos = body.get("position")
            if isinstance(pos, dict):
                elapsed = min(2, max(.05, now()-p["lastMove"]))
                x, z = number(pos.get("x"), p["x"], -89, 89), number(pos.get("z"), p["z"], -89, 89)
                distance = math.hypot(x-p["x"], z-p["z"])
                maximum = elapsed*18+1
                if distance > maximum:
                    ratio = maximum/distance
                    x, z = p["x"]+(x-p["x"])*ratio, p["z"]+(z-p["z"])*ratio
                # Movement stays responsive client-side; bounds and max speed
                # are validated here. Full anti-cheat physics is out of scope.
                p.update(x=x, y=number(pos.get("y"), .5, .5, 16), z=z, rotY=number(pos.get("rotY")),
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
        return dict(user=user_view(uid), room=room_view(room, uid),
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
        return dict(social=social(uid))
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
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8093")), log_level="warning")
