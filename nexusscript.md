# NexusScript 1.0 – język gier 3D w BloxWeb Studio

NexusScript to prosty język do tworzenia gier 3D w BloxWeb. Program buduje świat z klocków i reaguje na zdarzenia (start gry, dotknięcie klocka, zebranie monety, klawisz, upływ czasu). Kod działa w bezpiecznej piaskownicy: nie ma dostępu do internetu, plików ani strony.

## Świat i jednostki
- Oś X: lewo/prawo, oś Y: góra/dół (Y=0 to poziom gruntu), oś Z: przód/tył.
- Gracz ma ok. 3,4 jednostki wzrostu i skacze na ok. 2,5 jednostki w górę. Skok w dal to ok. 6–7 jednostek.
- Pozycja klocka to jego środek. `spawn("block", 0, 0, 0, 4, 1, 4)` tworzy płytę 4×1×4, której górna powierzchnia jest na Y=0,5.
- Pod światem nie ma podłogi: kto spadnie poniżej najniższego klocka o 30 jednostek, traci życie i wraca do ostatniego checkpointu.
- Limit: 600 klocków w grze.

## Typy klocków
- `"block"` – zwykły klocek, można po nim chodzić.
- `"glass"` – półprzezroczysty klocek, można po nim chodzić.
- `"lava"` – zabija po dotknięciu.
- `"coin"` – moneta do zebrania (nie blokuje ruchu).
- `"spawn"` – miejsce startu gracza (płyta). Powinien być dokładnie jeden.
- `"finish"` – meta: dotknięcie wygrywa grę (jeśli skrypt nie używa `when touch` na mecie inaczej).
- `"checkpoint"` – płyta zapisu: po śmierci gracz wraca na ostatni dotknięty checkpoint.
- `"spring"` – trampolina, wybija gracza wysoko.
- `"enemy"` – wróg: goni gracza w promieniu 18 jednostek i zadaje 25 obrażeń.

## Składnia
- Komentarze: `// do końca linii` oraz `/* blok */`.
- Instrukcje oddziela się nową linią lub średnikiem.
- Typy wartości: liczby (`3`, `2.5`), teksty (`"Cześć"` lub `'Cześć'`), `true`, `false`, `null`, listy `[1, 2, 3]`.
- Zmienne: `var punkty = 0`, potem `punkty = punkty + 1` albo `punkty += 1` (także `-=`, `*=`, `/=`).
- Operatory: `+ - * / %`, porównania `== != < > <= >=`, logiczne `and or not`. Tekst + liczba skleja tekst.
- Listy: `var l = [1, 2]`, `l[0]`, `l[1] = 5`, `push(l, 3)`, `len(l)`.
- Warunki: `if x > 3 { ... } else if x == 3 { ... } else { ... }`
- Pętle: `while warunek { ... }`, `repeat 5 { ... }`, `for i in range(0, 10) { ... }`, `for el in lista { ... }`, `break`, `continue`.
- Funkcje: `func nazwa(a, b) { return a + b }`. Wywołanie: `nazwa(1, 2)`.
- Klamry `{ }` są obowiązkowe. Nie ma średników na końcu bloków ani słowa `end`.

## Zdarzenia (`when`)
Kod w zdarzeniu uruchamia się automatycznie. Każde zdarzenie działa niezależnie, a `wait()` wstrzymuje tylko je.
- `when start { ... }` – raz, na początku gry. Tu najlepiej budować świat.
- `when every 2 { ... }` – co podaną liczbę sekund.
- `when tick { ... }` – w każdej klatce; zmienna `dt` to czas klatki w sekundach. Używaj oszczędnie.
- `when touch "Nazwa" { ... }` – gdy gracz dotknie klocka o tej nazwie (raz na każde wejście na klocek).
- `when collect { ... }` – po zebraniu monety (`player.coins` to liczba zebranych).
- `when key "E" { ... }` – po naciśnięciu klawisza (litera lub `"space"`). Na telefonie przycisk AKCJA działa jak `"E"`.
- `when win { ... }` i `when die { ... }` – po wygranej i po utracie życia.

## Funkcje świata
- `spawn(typ, x, y, z, szer, wys, gleb, kolor, nazwa)` – tworzy klocek i zwraca jego nazwę. Domyślnie: rozmiar 4×1×4, kolor zależny od typu, nazwa automatyczna. Kolor jako `"#rrggbb"`.
- `move(nazwa, x, y, z, sekundy)` – przesuwa klocek do pozycji (płynnie, jeśli podano sekundy; zdarzenie czeka do końca ruchu). Gracz stojący na klocku jedzie razem z nim.
- `moveBy(nazwa, dx, dy, dz, sekundy)` – przesuwa o podany wektor.
- `color(nazwa, "#rrggbb")`, `resize(nazwa, szer, wys, gleb)`, `spin(nazwa, stopnieNaSekunde)` (sam wygląd, kolizja się nie obraca).
- `hide(nazwa)` / `show(nazwa)` – ukryty klocek nie blokuje i nie reaguje na dotyk. `remove(nazwa)` usuwa klocek.
- `exists(nazwa)`, `getX(nazwa)`, `getY(nazwa)`, `getZ(nazwa)`.
- `sky("#rrggbb")` – kolor nieba.

## Gracz
- Odczyt: `player.x`, `player.y`, `player.z`, `player.hp` (0–100), `player.coins`.
- `teleport(x, y, z)`, `damage(ile)`, `heal(ile)`, `checkpoint(x, y, z)` (ustawia miejsce odrodzenia).
- `setSpeed(4–16)`, `setJump(6–22)`, `setGravity(10–45)` – domyślnie 8, 12 i 30.
- `win("tekst")` – wygrana, `lose("tekst")` – przegrana (koniec gry).

## Interfejs i dźwięk
- `say("tekst", sekundy)` – duży komunikat na środku ekranu (domyślnie 3 s).
- `hint("tekst")` – stały napis u góry ekranu (pusty tekst go chowa).
- `setScore(liczba)` / `addScore(liczba)` / `getScore()` – licznik punktów na ekranie.
- `print(...)` – wypisuje do konsoli Studio (pomoc przy szukaniu błędów).
- `sound("coin" | "jump" | "win" | "hit" | "beep")`.

## Narzędzia
- `wait(sekundy)` – pauza w bieżącym zdarzeniu.
- `time()` – sekundy od startu gry.
- `random(a, b)` – losowa liczba całkowita od a do b (z obu końcami). `random()` – ułamek 0–1.
- `round(x)`, `floor(x)`, `ceil(x)`, `abs(x)`, `min(a, b)`, `max(a, b)`, `sqrt(x)`, `sin(stopnie)`, `cos(stopnie)`.
- `text(x)`, `number("12")`, `len(lista_lub_tekst)`, `push(lista, x)`, `pop(lista)`, `contains(lista_lub_tekst, x)`, `range(od, do, krok)`.

## Przykład: obby z ruchomą platformą i monetami
```nexus
// Plansza startowa i meta
spawn("spawn", 0, 0, 0, 6, 1, 6)
var z = 8
repeat 6 {
  spawn("block", random(-3, 3), 0, z, 4, 1, 4, "#4eae79")
  spawn("coin", 0, 2, z)
  z += 7
}
spawn("lava", 0, -1, 30, 30, 1, 60)
spawn("block", 0, 0, z, 4, 1, 4, "#ffb23c", "Winda")
spawn("finish", 0, 8, z + 8, 6, 1, 6)

when start {
  say("Zbierz monety i dotrzyj do mety!")
  hint("Monety: 0")
}

when collect {
  hint("Monety: " + player.coins)
  sound("coin")
}

when every 4 {
  move("Winda", 0, 8, z, 1.5)
  wait(1)
  move("Winda", 0, 0, z, 1.5)
}

when win {
  say("Brawo! Monety: " + player.coins)
}
```

## Zasady dla AI piszącego kod
- Odpowiadaj jednym blokiem kodu ```nexus ... ``` bez innych języków (to nie jest JavaScript ani Lua).
- Używaj wyłącznie funkcji z tej listy. Każdy blok `when`, `if`, `while`, `repeat`, `for`, `func` musi mieć klamry `{ }`.
- Zbuduj świat poleceniami `spawn` na początku programu lub w `when start`. Dodaj dokładnie jeden `"spawn"` i zwykle jeden `"finish"`.
- Odległości między platformami do skoku: najwyżej 6 jednostek w poziomie i 2 w pionie.
- Teksty dla gracza pisz po polsku. Gry muszą być odpowiednie dla dzieci.
