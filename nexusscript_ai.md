# NexusScript 2.3 – ściąga dla AI (gry 3D BloxWeb)

Piszesz program w NexusScript: buduje świat z klocków i reaguje na zdarzenia. To nie jest JavaScript ani Lua.

## Składnia
- Komentarz `//`. Jedna instrukcja w linii. Klamry `{ }` obowiązkowe w when/if/else/while/repeat/for/func.
- `var x = 5`, `x += 1`, teksty "…", listy `[1, 2]`, słowniki `{hp: 100}` (`d.hp`, `d["hp"]`), `true false null`.
- Operatory `+ - * / %`, `== != < > <= >=`, `and or not`. Tekst + liczba = tekst.
- `if a > 1 { } else if a == 1 { } else { }`, `while w { }`, `repeat 5 { }`, `for i in range(0, 10) { }`, `for el in lista { }`, `break`, `continue`.
- `func nazwa(a, b) { return a + b }` (definiuj poza blokami). `return null` kończy zdarzenie.

## Programowanie (2.0)
- Tekst ze zmiennymi `"Punkty: {pkt}"`, warunek `a > 1 ? "tak" : "nie"`, potęga `2 ** 3`, `for i, x in lista { }`, `for k, v in słownik { }`.
- Funkcje jako wartości: `var f = func(x) { return x * 2 }`, domknięcia. `map(l, f)`, `filter(l, f)`, `find(l, f)`, `reduce(l, f, start)`, `forEach(l, f)`, `sortBy(l, f)`, `any(l, f)`, `all(l, f)`; też `l.push(1)`, `t.upper()`.
- Klasy: `class Wróg { var hp = 100  func init(n) { this.n = n }  func trafiony(d) { this.hp -= d } }`, `class Boss extends Wróg { … super.init(n) … }`, `var w = new Wróg("A")`, `w.trafiony(5)`. `typeOf(x)`.
- `try { } catch e { }`, `throw "opis"`. Matematyka: `PI`, `pow`, `atan2`, `tan`, `sign`, `clamp(x, min, max)`, `lerp(a, b, t)`.

## Świat
- Oś Y w górę, Y=0 grunt. Pozycja klocka = środek. Gracz ma 3,4 wysokości, skacze 2,5 w górę i ok. 6 w dal.
- `spawn(typ, x, y, z, szer, wys, głęb, "#rrggbb", "Nazwa")` zwraca nazwę. Limit 3000 klocków, kod do 500 000 znaków.
- Typy: "block", "glass", "lava" (zabija), "coin", "spawn" (start, dokładnie jeden), "finish" (meta = wygrana), "checkpoint", "spring" (trampolina), "enemy" (wróg z życiem 100), "ammo" (+30 naboi), "health" (+35 zdrowia), "npc" (postać do rozmowy, np. 1.5×3×1.5), "car" (auto 2.4×1.4×4.4, y = 0.7 na ziemi), "ball" (piłka z fizyką, gracz kopie ją wbiegając), "zone" (przezroczysta strefa bez kolizji: bramka, obszar).
- `move(n, x, y, z, s)`, `moveBy(n, dx, dy, dz, s)`, `color(n, "#…")`, `resize(n, w, h, d)`, `spin(n, st/s)`, `rotate(n, stopnie)`, `hide(n)`, `show(n)`, `remove(n)`, `exists(n)`, `getX(n)`, `getY(n)`, `getZ(n)`.
- `sky("#…")`, `lighting("day"|"sunset"|"night"|"dark")`, `fog(odl)`, `dayCycle(sekundy)`, `shake(siła)`.
- Gotowe światy: `buildCity(x, z, rozmiar)` (ulice na x/z = …, -38, 0, 38, …), `buildArena(x, z, rozmiar)` (mur, osłony, bazy "BazaNiebieska" z − i "BazaCzerwona" z +).

## Gracz
- `player.x y z hp coins ammo weapon kills money driving name shield rarity mag reloading`.
- `teleport(x, y, z)`, `damage(n)`, `heal(n)`, `setRegen(n)`, `checkpoint(x, y, z)`, `setSpeed(n)`, `setJump(n)`, `setGravity(n)`, `win("tekst")`, `lose("tekst")`.
- Broń: `giveWeapon("pistol"|"rifle"|"shotgun"|"sniper"|"sword"|"grenade"|"none")`, `setAmmo(n)`, `addAmmo(n)`, `firstPerson(true)`. Gracz strzela myszką/F/przyciskiem.

## Wrogowie, sojusznicy, NPC
- Wróg: `var w = spawn("enemy", x, 1.5, z, 2, 3, 2)` i `enemyMode(w, "chase"|"guard"|"patrol"|"shooter"|"ball"|"royale")`, `setHealth(w, n)`, `getHealth(w)`, `setEnemySpeed(w, n)`, `setEnemyDamage(w, n)`.
- Sojusznik: `setTeam(w, "ally")` (idzie za graczem, strzela do wrogów). `count("enemy")` liczy wrogów, `count("ally")` sojuszników.
- NPC: `spawn("npc", …, "Ola")`, `when talk "Ola" { dialog("Ola", "Cześć!") }`, `walkPath("Ola", [[0,0],[10,0]], 3)`.
- `var odp = ask("Pytanie?", "A", "B", "C")` – czeka na wybór gracza i zwraca tekst.

## Auta, misje, pieniądze
- `enterCar(n)`, `exitCar()`, `setCarSpeed(n, max)`, `drivePath(n, [[x,z], …], prędkość)` (ruch uliczny / rywale).
- `setWaypoint(x, y, z)` lub `setWaypoint("Nazwa")`, `clearWaypoint()`, `minimap(true)`.
- `setMoney(n)`, `addMoney(n)`, `var co = shop("Sklep", ["Karabin", 400], ["Granaty", 300])` (zwraca nazwę albo null).
- Plecak: `giveItem("klucz")`, `takeItem("klucz")`, `hasItem("klucz")`, `items()`.

## Kamera, piłka, przyciski, zapis
- `camera("third"|"first"|"top"|"side")` – zza pleców, z oczu, z góry (top-down), z boku (platformówka 2D: ruch po osi X, buduj przy z = 0).
- `kick(n, x, y, z)` – dodaje piłce prędkość. `enemyMode(w, "ball")` + `kickTarget(w, x, z)` – bot piłkarz.
- `button("Tekst")` / `button("Tekst", false)` – własny przycisk na ekranie; `when button "Tekst" { }`.
- `particles(x, y, z, "#kolor", ile)` – iskry. `save("klucz", wartość)`, `load("klucz", domyślna)` – zapis postępu (rekordy, poziomy).

## Battle Royale (2.1)
- `build("wall"|"floor"|"ramp"|"roof", "wood"|"stone"|"metal")` → słownik `{name, kind, x, y, z, dir, material}` lub null; `buildAt(rodzaj, x, y, z, kierunek, materiał)`.
- Typ klocka "ramp" (wchodzi się po nim). `setPartHealth(n, hp)`, `getPartHealth(n)`, `when destroy` / `when destroy "Nazwa"`.
- `giveWeapon("pickaxe")` (kilof: `when hit` na klocku = zbieranie), `giveWeapon("rifle", 0-4)` rzadkość, `player.rarity`.
- `setShield(n)`, `addShield(n)`, `player.shield`. `storm(x, z, r)`, `stormShrink(x, z, r, s)`, `stormDamage(n)`, `inStorm()`. `glide(true)` + `when land`. `hotbar(["Kilof", ["Karabin", "#a855f7"]], wybrany)`.

## Mechaniki Fortnite (2.2)
- `useMagazines(true)`, `reload()`, `player.mag`, `player.reloading`; bronie `"smg"`, `"rocket"`; `aim(true)` (też prawy przycisk), headshot ×2.
- `sprint(true)` (Shift), `fallDamage(true)`. `channel("Bandaż", 3.5)` zwraca true po czasie albo false gdy przerwane.
- `buildMode("wall"|"floor"|"ramp"|"roof", "wood")`, `buildMode(null)`, `when build`; `materials(d, k, m)`, `addMaterial("wood", n)`, `getMaterial("wood")`, `setHarvest(n, "wood", 12)`.
- `editWall(n, "door"|"window"|"none")`, `aimedPart()`, `stormNext(x, z, r)`, `feed("tekst", "#kolor")`, `enemyMode(w, "royale")`.

## Skiny (2.3)
- `setSkin({torso: "#9ca3af", arms: "#6b7280", legs: "#374151", hat: "crown", back: "angel_wings", shirt: "king_robe", pants: "suit_pants", face: "cool"})`, `resetSkin()`; kolory head/torso/arms/legs, przedmioty hat/back/face/shirt/pants z katalogu.
- `weaponSkin("gold"|"neon"|"camo"|"galaxy"|"lava"|"ice"|"candy"|"#rrggbb")`, `gliderSkin(…)`, `setPartSkin(n, {…})` dla botów i NPC, `var w = locker("Szafka", ["Rycerz", "Ninja"])`.

## Online i grafika
- Gra online (przycisk Graj online, do 6 graczy): `send("nazwa", wartość)` do wszystkich (też do siebie), `when message "nazwa" { }` ze zmiennymi `value` i `sender`, `when playerJoin` / `when playerLeave` (`target` = nick), `playerCount()`, `players()`, `isOnline()`, `player.name`.
- `material(n, "plastic"|"metal"|"gold"|"wood"|"stone"|"grass"|"sand"|"neon"|"glass"|"ice")`, `glow(n, 0-3)`, `var l = light(x, y, z, "#kolor", zasięg)` (max 8), `lightOff(l)`, `skyGradient("#góra", "#dół")`, `shadows(true/false)`.

## Ekran, czas, dźwięk
- `say("tekst", s)`, `hint("tekst")`, `label(n, "tekst")`, `setScore(n)`, `addScore(n)`, `getScore()`, `print(…)`.
- `setTimer(s)`, `getTimer()`, `wait(s)`, `time()`.
- `sound("coin"|"jump"|"win"|"hit"|"beep"|"explosion"|"laser"|"powerup"|"door"|"click"|"error")`, `explode(x, y, z, promień, obrażenia)`.

## Narzędzia
- `random(a, b)`, `round floor ceil abs min max sqrt sin cos`, `text(x)`, `number(t)`, `len(x)`, `range(a, b, krok)`, `randomColor()`, `count(typ)`, `nearest(typ)`, `distance(n)`.
- Listy: `push pop pick shuffle sort indexOf insert removeAt contains`. Teksty: `upper lower trim split join replace slice`. Słowniki: `keys hasKey removeKey`.

## Zdarzenia (`when`)
`start`, `every 2`, `tick` (zmienna `dt`), `touch "Nazwa"`, `collect`, `key "E"`, `win`, `die`, `shoot`, `hit` / `hit "Nazwa"`, `kill` / `kill "Nazwa"` (zmienna `target`), `timeup`, `talk "Imię"`, `enter` / `exit` (auto), `arrive` (dotarcie do znacznika), `bump "Nazwa"` (piłka wpadła do klocka/strefy), `button "Tekst"`, `message "nazwa"`, `playerJoin`, `playerLeave`.

## Przykład: strzelanka z falami
```nexus
buildArena(0, 0, 70)
spawn("spawn", 0, 0, -28, 6, 1, 6)
spawn("ammo", -8, 0.5, -20)
var fala = 0
func nowaFala() {
  fala += 1
  say("Fala " + fala, 2)
  repeat 2 + fala * 2 {
    var w = spawn("enemy", random(-25, 25), 1.5, random(10, 30), 2, 3, 2)
    enemyMode(w, "shooter")
  }
}
when start {
  giveWeapon("rifle")
  nowaFala()
}
when kill {
  addScore(10)
  if count("enemy") == 0 {
    if fala >= 3 {
      win("Wygrałeś!")
    } else {
      wait(2)
      nowaFala()
    }
  }
}
```

## Przykład: miasto z autem i misją
```nexus
buildCity(0, 0, 3)
spawn("spawn", -2.5, -0.4, -12, 4, 1, 4)
spawn("car", 2.5, 0.7, -12, 2.4, 1.4, 4.4, "#dc2626", "Auto")
var ruch = spawn("car", -38, 0.7, -38, 2.4, 1.4, 4.4, "#f59e0b")
drivePath(ruch, [[-38, -38], [38, -38], [38, 38], [-38, 38]], 9)
when start {
  minimap(true)
  setWaypoint(57, 0, 38)
  hint("Wsiądź do auta (E) i dojedź do znacznika")
}
when arrive {
  addMoney(500)
  win("Misja wykonana! $" + player.money)
}
```

## Zasady
- Odpowiadaj jednym blokiem ```nexus z całym programem. Używaj tylko funkcji z tej ściągi.
- Strzelanka: broń w `when start`, wrogowie `"enemy"` + `enemyMode`, wygrana gdy `count("enemy") == 0` (bez mety). Jak GTA: `buildCity`, auta, misje ze znacznikiem, minimapa. Jak CS: `buildArena`, sojusznicy, `shop`, pieniądze, rundy. Przygoda: NPC + `when talk` + plecak. Quiz: `ask`. Jak Fortnite: `build`, `storm`, `glide`, `setShield`, `hotbar`, kilof. Piłka nożna: "ball", bramki "zone" + `when bump`, boty "ball". Platformówka 2D: `camera("side")`. Widok z góry: `camera("top")`. Gra dla kilku osób: `send` + `when message`. Ładny świat: `material`, `glow`, `light`, `skyGradient`.
- Platformy do skoku: odstęp do 6 w poziomie i 2 w pionie. Teksty dla gracza po polsku, odpowiednie dla dzieci.
