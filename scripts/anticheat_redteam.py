"""Red-team check of BloxWeb's server-side anti-cheat.

Plays a set of cheating clients against a LOCAL server and reports for each cheat
whether the server blocked it, detected it, or let it through. It talks only to
localhost so it never touches real players.

Run the local server first (python server.py, port 8093), then:
    python scripts/anticheat_redteam.py [--base http://127.0.0.1:8093]
"""
import argparse
import math
import secrets
import sys
import time
from urllib.parse import urlparse

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--base", default="http://127.0.0.1:8093")
args = parser.parse_args()
if urlparse(args.base).hostname not in ("127.0.0.1", "localhost", "::1"):
    sys.exit("Ten skrypt działa tylko na lokalnym serwerze (localhost).")
http = httpx.Client(base_url=args.base, timeout=20)
results = []


def api(op, **body):
    r = http.post("/api/" + op, json=body)
    return r.status_code, r.json()


def player(name="Cheater"):
    pid = "BLOX-RT" + secrets.token_hex(3).upper()
    status, data = api("session", token="", id=pid, name=name + secrets.token_hex(2), avatar={})
    assert status == 200, data
    return data["token"], data["user"]["id"]


def cs_room(token):
    status, data = api("room", token=token, action="create", game="cs2")
    assert status == 200, data
    # Report the spawn spot once, as the real client does after entering, to end the entry grace.
    me = next(p for p in data["room"]["players"] if p["id"] == data["user"]["id"]) if "user" in data else data["room"]["players"][-1]
    api("sync", token=token, position=dict(x=me["x"], y=1.5, z=me["z"], rotY=0), social=False)
    return data["room"]


def me_in(room, uid):
    return next((p for p in (room or {}).get("players", []) if p["id"] == uid), None)


def report(name, verdict, detail):
    results.append((name, verdict, detail))
    print(f"[{verdict:^11}] {name}: {detail}", flush=True)


def walk(token, uid, path, hz=10, **extra):
    """Send positions at `hz` per second; returns the last sync answer."""
    last = None
    for x, y, z in path:
        _, last = api("sync", token=token, position=dict(x=x, y=y, z=z, rotY=0), social=False, **extra)
        time.sleep(1 / hz)
    return last


seq = {"n": 0}


def action(token, **a):
    seq["n"] += 1
    _, data = api("sync", token=token, actions=[dict(seq=seq["n"], **a)], social=False)
    mine = me_in(data.get("room"), data["user"]["id"]) or {}
    ack = next((x for x in mine.get("acknowledgements", []) if x["seq"] == seq["n"]), {})
    return data, ack.get("error")


# 1. Teleport hack: jump across the map every sync.
token, uid = player()
cs_room(token)
notice = None
for i in range(30):
    _, data = api("sync", token=token, position=dict(x=80 if i % 2 else -80, y=1.5, z=-70), social=False)
    notice = notice or data.get("notice")
    if data.get("room") is None:
        break
report("Teleport", "WYKRYTY" if notice else "PRZESZEDŁ", notice or "brak reakcji")

# 2. Speed hack: run steadily faster than the game allows (normal ≈ 8 j/s).
for speed in (13, 16, 27, 40):
    token, uid = player()
    cs_room(token)
    # 8 seconds along the open south edge of the map (z=-80), longer than any lag allowance.
    path = [(-70 + speed * 0.1 * i, 1.5, -80) for i in range(1, 81)]
    walk(token, uid, [(-70, 1.5, -70 - i) for i in range(1, 11)], hz=5)
    started = time.time()
    data = walk(token, uid, path)
    took = time.time() - started
    me = me_in(data.get("room"), uid)
    reached = (me["x"] + 70) if me else 0
    wanted = speed * took
    if data.get("room") is None or data.get("notice"):
        verdict = "WYKRYTY"
    elif reached / took <= 11.5:  # the game's top speed in CS is 9.6 units/s
        verdict = "ZABLOKOWANY"
    else:
        verdict = "PRZESZEDŁ"
    report(f"Speedhack {speed} j/s", verdict, f"przebył {reached:.1f} j. w {took:.1f} s, czyli ≈{reached / took:.1f} j/s (cheat chciał {speed})")

# 3. Fly hack: hover high above the arena.
token, uid = player()
cs_room(token)
data = walk(token, uid, [(-70, 15, -70)] * 30)
me = me_in(data.get("room"), uid)
report("Latanie (y=15)", "WYKRYTY" if data.get("room") is None or data.get("notice") else
       "ZABLOKOWANY" if me and me["y"] <= 11 else "PRZESZEDŁ",
       data.get("notice") or f"serwer trzyma y={me and me['y']}")

# 4. Noclip: walk at normal speed straight through the wall at x=-50 (z -70..-50).
token, uid = player()
cs_room(token)
walk(token, uid, [(-70 + 0.8 * i, 1.5, -70 + 0.8 * i) for i in range(1, 13)])
data = walk(token, uid, [(-60 + 0.8 * i, 1.5, -60) for i in range(1, 26)])
me = me_in(data.get("room"), uid)
report("Przechodzenie przez ściany", "PRZESZEDŁ" if me and me["x"] > -48 else "ZABLOKOWANY",
       f"gracz stoi na x={me and round(me['x'], 1)} (ściana x -51.5..-48.5)")

# 5. Rapid fire: 30 shots in one packet.
token, uid = player()
room = cs_room(token)
me = me_in(room, uid)
_, data = api("sync", token=token, social=False, actions=[
    dict(seq=1000 + i, kind="shoot", origin=[me["x"], 2.5, me["z"]], direction=[1, 0, 1]) for i in range(30)])
ammo = me_in(data["room"], uid)["weapons"][0]["ammo"]
report("Szybkie strzelanie (30 strzałów naraz)", "ZABLOKOWANY" if ammo >= 19 else "PRZESZEDŁ",
       f"serwer zużył {20 - ammo} naboi")

# 6. Shot from a fake origin next to the enemy (magic bullet).
token, uid = player()
room = cs_room(token)
enemy = room["enemies"][0]
before = enemy["hp"]
_, data = api("sync", token=token, social=False, actions=[dict(seq=1, kind="shoot",
              origin=[enemy["x"], enemy["y"] + 2.6, enemy["z"] + 2], direction=[0, 0, -1])])
after = next((e["hp"] for e in data["room"]["enemies"] if e["id"] == enemy["id"]), 0)
report("Strzał z fałszywej pozycji", "ZABLOKOWANY" if after == before else "PRZESZEDŁ",
       f"życie bota {before} -> {after}")

# 7. Shooting through a wall: player at (-55,-60), bot placed beyond the wall is not possible from
#    the client, so aim through the wall at whatever bot lies behind it and count hits.
token, uid = player()
room = cs_room(token)
walk(token, uid, [(-70 + 0.8 * i, 1.5, -70 + 0.8 * i) for i in range(1, 13)])
walk(token, uid, [(-60 + 0.8 * i, 1.5, -60) for i in range(1, 7)])
hits = 0
for i in range(8):
    data, _ = action(token, kind="shoot", origin=[-55.2, 2.5, -60], direction=[1, 0, 0])
    time.sleep(0.25)
shots = [fx for fx in data["room"].get("fx", []) if fx.get("player") == uid and fx["kind"] == "shot"]
far = max((fx["end"][0] for fx in shots), default=-55)
report("Strzał przez ścianę", "ZABLOKOWANY" if far <= -51 else "PRZESZEDŁ",
       f"pociski kończą się na x={far:.1f} (ściana zaczyna się na x=-51.5)")

# 8. Buying without money and outside the base.
token, uid = player()
cs_room(token)
_, err_money = action(token, kind="buy", item="awp")
walk(token, uid, [(-70 + 0.8 * i, 1.5, -70 + 0.8 * i) for i in range(1, 25)])
_, err_far = action(token, kind="buy", item="usp")
report("Kupno AWP bez pieniędzy", "ZABLOKOWANY" if err_money else "PRZESZEDŁ", err_money or "kupiono")
report("Kupno poza bazą", "ZABLOKOWANY" if err_far else "PRZESZEDŁ", err_far or "kupiono")

# 9. Respawn as a heal / escape: "respawn" while alive.
token, uid = player()
cs_room(token)
walk(token, uid, [(-70 + 0.8 * i, 1.5, -70) for i in range(1, 16)])
data, err = action(token, kind="respawn")
me = me_in(data.get("room"), uid)
report("Odrodzenie bez śmierci (teleport do bazy / leczenie)",
       "ZABLOKOWANY" if me and me["x"] > -65 else "PRZESZEDŁ", f"po komendzie x={me and round(me['x'], 1)}, hp={me and me['hp']}")

# 10. Aimbot: waits at the base and fires a perfect, leading headshot whenever a bot is in view.
import json
from pathlib import Path
WALLS = json.loads((Path(__file__).resolve().parent.parent / "arena.json").read_text())


def visible(a, b):
    d = [b[k] - a[k] for k in range(3)]
    for cx, cy, cz, sx, sy, sz in WALLS:
        if sy <= .3:
            continue
        t0, t1 = 0.0, 1.0
        for k, (c, size) in enumerate(((cx, sx), (cy, sy), (cz, sz))):
            lo, hi = c - size / 2, c + size / 2
            if abs(d[k]) < 1e-9:
                if not lo <= a[k] <= hi:
                    t0 = 2
                continue
            u, v = (lo - a[k]) / d[k], (hi - a[k]) / d[k]
            t0, t1 = max(t0, min(u, v)), min(t1, max(u, v))
        if t0 < t1:
            return False
    return True


token, uid = player()
room = cs_room(token)
kicked, shots, hits, end, seen = None, 0, 0, time.time() + 90, {}
while time.time() < end and not kicked:
    _, data = api("sync", token=token, social=False)
    if data.get("room") is None:
        kicked = data.get("notice") or "usunięty z pokoju"
        break
    me = me_in(data["room"], uid)
    target = min(data["room"]["enemies"], key=lambda e: math.hypot(e["x"] - me["x"], e["z"] - me["z"]))
    eye = [me["x"], me["y"] + 2.5, me["z"]]
    # Lead the target: predict where the bot will be when the shot arrives (~0.1 s later).
    last = seen.get(target["id"])
    vx, vz = ((target["x"] - last[0]) / (time.time() - last[2]), (target["z"] - last[1]) / (time.time() - last[2])) if last else (0, 0)
    seen[target["id"]] = (target["x"], target["z"], time.time())
    head = [target["x"] + vx * .1, target["y"] + 2.6, target["z"] + vz * .1]
    if me["weapons"][0]["ammo"] == 0:
        action(token, kind="reload")
        time.sleep(1.6)
    elif visible(eye, head):
        data, _ = action(token, kind="shoot", origin=eye, direction=[head[k] - eye[k] for k in range(3)])
        shots += 1
        hits += any(fx.get("player") == uid and fx.get("hit") for fx in (data.get("room") or {}).get("fx", [])[-3:])
        if data.get("room") is None:
            kicked = data.get("notice") or "usunięty z pokoju"
        time.sleep(0.22)
    else:
        # Bots hunt the player, so the cheat waits at the base until one walks into view.
        time.sleep(0.1)
report("Aimbot (same headshoty przy widoczności)", "WYKRYTY" if kicked else "PRZESZEDŁ",
       (kicked or "brak reakcji") + f" po {shots} strzałach (ok. {hits} trafień)")

# 11. BloxBux and free shop items through the progress save.
token, uid = player()
base = dict(coins=100, owned=[], badges=[], quests={})
api("sync", token=token, progress=dict(base=None, current=base), social=False)
_, data = api("sync", token=token, progress=dict(base=base, current=dict(base, coins=999999)), social=False)
report("Dodanie 999 999 BloxBux", "ZABLOKOWANY" if data["progress"]["coins"] < 10000 else "PRZESZEDŁ",
       f"serwer zapisał {data['progress']['coins']} BloxBux")
start = data["progress"]
free = dict(start, owned=["dominus", "banhammer"], badges=["legend", "speedrunner"])
_, data = api("sync", token=token, progress=dict(base=start, current=free), social=False)
paid = start["coins"] - data["progress"]["coins"]
report("Darmowe przedmioty ze sklepu (Dominus, BanHammer)",
       "PRZESZEDŁ" if "dominus" in data["progress"]["owned"] and paid < 1000 else "ZABLOKOWANY",
       f"posiadane: {data['progress']['owned']}, BloxBux {start['coins']} -> {data['progress']['coins']}")
report("Odznaki bez zdobycia", "PRZESZEDŁ" if data["progress"]["badges"] else "ZABLOKOWANY",
       f"odznaki: {data['progress']['badges']}")

token, uid = player()
_, data = api("sync", token=token, progress=dict(base=None, current=dict(coins=999999, owned=["dominus", "banhammer"], badges=[], quests={})), social=False)
report("Fortuna przy pierwszym zapisie (999 999 + przedmioty)", "ZABLOKOWANY" if data["progress"]["coins"] <= 5000 else "PRZESZEDŁ",
       f"serwer zapisał {data['progress']['coins']} BloxBux, przedmioty {data['progress']['owned']}")

# 12. Chat spam and replayed actions.
token, uid = player()
cs_room(token)
_, data = api("sync", token=token, social=False, actions=[dict(seq=i, kind="chat", text=f"spam {i}") for i in range(1, 11)])
sent = [m for m in data["room"]["chat"] if m["sender"] == uid]
report("Spam na czacie (10 wiadomości naraz)", "ZABLOKOWANY" if len(sent) <= 1 else "PRZESZEDŁ", f"przeszło {len(sent)}")

# 13. Staff tools and someone else's game.
token, uid = player()
status, data = api("admin_overview", token=token)
report("Panel admina bez uprawnień", "ZABLOKOWANY" if status == 403 else "PRZESZEDŁ", f"HTTP {status}")
status, data = api("admin_ban", token=token, target="BLOX-759762", banned=True)
report("Blokada konta CEO przez gracza", "ZABLOKOWANY" if status == 403 else "PRZESZEDŁ", f"HTTP {status}")
author, _ = player("Autor")
game = dict(format="bloxweb-nexus", version=1, settings=dict(speed=8, jump=12, gravity=30, sky="#8fd3ff"),
            parts=[dict(t="spawn", p=[0, 1, 0], s=[4, 1, 4], c="#70c6ff")], script="")
status, pub = api("games_publish", token=author, title="Gra testowa", game=game)
gid = pub.get("game", pub).get("id") if status == 200 else None
status, _ = api("games_unpublish", token=token, id=gid or "G-000000")
report("Usunięcie cudzej gry", "ZABLOKOWANY" if status == 403 else "PRZESZEDŁ", f"HTTP {status}")
if gid:
    api("games_unpublish", token=author, id=gid)

# 14. Impersonation with look-alike letters (Cyrillic о and х, Greek Ο).
for fake in ["BlохWeb", "13pоlik", "ΒloxWeb", "Аdmin"]:
    pid = "BLOX-RT" + secrets.token_hex(3).upper()
    _, data = api("session", token="", id=pid, name=fake, avatar={})
    name = data["user"]["name"]
    report(f"Podrobiony nick „{fake}” (obce litery)", "ZABLOKOWANY" if name != fake else "PRZESZEDŁ", f"nick na serwerze: {name}")

print()
passed = [r for r in results if r[1] == "PRZESZEDŁ"]
print(f"Wynik: {len(results) - len(passed)} z {len(results)} cheatów zablokowanych lub wykrytych.")
for name, _, detail in passed:
    print(" - PRZESZEDŁ:", name, "–", detail)
