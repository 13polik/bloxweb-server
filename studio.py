"""Safe data-only Studio documents; never execute generated/user code."""
import math
import secrets
import time


def validate_project(value):
    if not isinstance(value, dict):
        raise ValueError("Nieprawidłowy projekt.")
    tiles = value.get("tiles")
    name = value.get("name", "")
    if (value.get("format") != "bloxweb-studio" or value.get("version") != 1
            or value.get("kind") not in ("obby", "coins")
            or value.get("theme") not in ("forest", "night", "sand")
            or not isinstance(name, str) or not 1 <= len(name.strip()) <= 48
            or not isinstance(tiles, list) or len(tiles) != 336
            or any(type(t) is not int or not 0 <= t <= 7 for t in tiles)):
        raise ValueError("Projekt musi mieć 24 × 14 poprawnych kafelków i nazwę do 48 znaków.")
    if tiles.count(4) != 1 or tiles.count(5) != 1:
        raise ValueError("Dodaj dokładnie jeden Start i jedną Metę.")
    if value["kind"] == "coins" and 2 not in tiles:
        raise ValueError("Gra z monetami musi zawierać monety.")
    raw = value.get("settings")
    raw = raw if isinstance(raw, dict) else {}
    settings = {}
    for key, default, low, high in (("speed", 6, 3, 10), ("jump", 12, 8, 18), ("gravity", 28, 18, 40)):
        number = raw.get(key, default)
        if type(number) not in (float, int) or not math.isfinite(number):
            number = default
        settings[key] = max(low, min(high, number))
    return dict(format="bloxweb-studio", version=1, id=str(value.get("id", ""))[:80],
                name=name.strip(), kind=value["kind"], theme=value["theme"],
                tiles=tiles[:], settings=settings, updated=time.time()*1000)


def procedural(prompt):
    """An explicitly labelled local generator, not an LLM/AI substitute."""
    text = prompt.casefold()
    theme = "night" if any(w in text for w in ("noc", "kosmo", "night")) else "sand" if any(
        w in text for w in ("piask", "pustyn", "desert")) else "forest"
    kind = "coins" if any(w in text for w in ("monet", "coin", "skarb")) else "obby"
    tiles = [0]*336
    for x in range(24):
        tiles[13*24+x] = 1
    for x, y, width in ((4, 11, 3), (9, 10, 3), (14, 11, 3), (18, 10, 3)):
        for dx in range(width):
            tiles[y*24+x+dx] = 1
        tiles[(y-1)*24+x+1] = 2
    tiles[12*24+1] = 4
    tiles[12*24+22] = 5
    tiles[12*24+12] = 6
    tiles[12*24+17] = 7
    if "law" in text:
        for x in (6, 7, 15):
            tiles[12*24+x] = 3
    return validate_project(dict(format="bloxweb-studio", version=1, id=secrets.token_hex(12),
                                 name=prompt.strip()[:48] or "Nowa przygoda", kind=kind,
                                 theme=theme, settings={}, tiles=tiles))


def from_ai(document):
    """Expand compact rectangles/objects. AI need not count 336 array entries."""
    if not isinstance(document, dict):
        raise ValueError("AI document")
    terrain, objects = document.get("terrain"), document.get("objects")
    if not isinstance(terrain, list) or not isinstance(objects, list) or len(terrain)+len(objects) > 200:
        raise ValueError("AI layout")
    tiles = [0]*336
    tiles[312:] = [1]*24
    for rectangle in terrain:
        x, y, w, h = (rectangle[k] for k in ("x", "y", "w", "h"))
        if (any(type(v) is not int for v in (x, y, w, h))
                or not 0 <= x < 24 or not 0 <= y < 13 or not 1 <= w <= 24-x or not 1 <= h <= 13-y):
            raise ValueError("AI rectangle")
        for row in range(y, y+h):
            for col in range(x, x+w):
                tiles[row*24+col] = 1
    types = dict(coin=2, lava=3, start=4, finish=5, checkpoint=6, spring=7)
    for item in objects:
        x, y, kind = item["x"], item["y"], item["type"]
        if (type(x) is not int or type(y) is not int or not 0 <= x < 24
                or not 0 <= y < 13 or kind not in types or tiles[y*24+x] != 0):
            raise ValueError("AI object")
        tiles[y*24+x] = types[kind]
    return validate_project(dict(format="bloxweb-studio", version=1, id=secrets.token_hex(12),
                                 name=document.get("name"), kind=document.get("kind"),
                                 theme=document.get("theme"), settings=document.get("settings"),
                                 tiles=tiles))
