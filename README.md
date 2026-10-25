# BloxWeb 13: serwer i strona

## Multiplayer na żywo i antycheat (18)

W pokoju gra łączy się z serwerem przez WebSocket (`/ws`): serwer wysyła stan pokoju 20 razy na sekundę, a gracz wysyła ruch i akcje od razu. Wspólna część stanu jest kodowana raz na pokój, więc słaby CPU Render Free obsługuje więcej graczy. Gdy WebSocket nie działa, gra wraca do zapytań `/api/sync`. Wymaga pakietu `websockets` (jest w requirements.txt).

Antycheat po stronie serwera (przeglądarce nie da się w pełni ufać):
- BloxBux: przyrost salda ma limit (pula 5000, odnawia się 30 na sekundę); nadwyżka z edytowanego zapisu lub autoklikera jest odrzucana. Pierwszy import starego zapisu przechodzi bez zmian.
- Ruch: teleporty i loty ponad ściany areny są przycinane i zliczane; 25 naruszeń w minutę usuwa gracza z pokoju.
- Strzały są liczone przez serwer (amunicja, szybkostrzelność, ściany); 90% trafień w głowę przy 40+ strzałach usuwa gracza (aimbot).
- Czat w pokoju: filtr słów i limit jednej wiadomości na 0,8 s. Przycisk kopania BloxBux przyjmuje tylko prawdziwe kliknięcia, do 6 na sekundę.
Zdarzenia trafiają do logu Render jako `anticheat …`.

## Konta bez e-maila (14)

Gość może w „Konto i logowanie” przypisać do swojego ID login i hasło (bez e-maila i danych osobowych, więc działa też na kontach dzieci z kontrolą rodzicielską).
Na innym urządzeniu logowanie tym loginem przywraca to samo ID, znajomych i wiadomości. Stary kod dostępu nadal działa.
Hasła są haszowane scryptem; 10 błędnych prób blokuje login na 15 minut.

## Synchronizacja postępu (15)

Nick, wygląd, BloxBux, posiadane przedmioty, odznaki i misje są zapisywane na koncie i synchronizowane między urządzeniami co ok. 1,5 s.
Każde urządzenie wysyła tylko swoje zmiany względem ostatnio zsynchronizowanej wersji, więc zarobki i wydatki z kilku urządzeń sumują się zamiast się nadpisywać.
Urządzenie, które łączy się z kontem pierwszy raz, łączy swój stan z kontem (wyższe saldo, suma przedmiotów); logowanie na nowym urządzeniu przejmuje stan konta.
Postęp jest prywatny i nie trafia do profili widocznych dla innych. To nadal nie jest anty-cheat: saldo pochodzi z przeglądarki.

Migracje uruchamia raz administrator, w kolejności dat, przed wdrożeniem odpowiadającej wersji serwera:
`migrations/2026-10-24_accounts.sql` (wersja 14), `migrations/2026-10-25_progress.sql` (wersja 15). Obie tylko dodają kolumny, tabele i indeksy.

Testy: `pip install -r requirements-dev.txt`, potem `python -m pytest tests` (SQLite w katalogu tymczasowym).

## Awatar i sklep

Zakładka Awatar ma podgląd rzeczywistego modelu R6 3D, obracany myszą/dotykiem lub przyciskami.
Kategorie, wyszukiwanie, filtry posiadanych/założonych/dostępnych cenowo przedmiotów oraz sortowanie ułatwiają wybór.
Przymierzanie nie zmienia monet, posiadanych rzeczy ani zapisanego stroju. Zakup wymaga osobnego potwierdzenia; ponowne zakładanie posiadanej rzeczy jest darmowe.
Zachowano identyfikatory i ceny. Wszystkie 15 czapek i 11 dodatków mają dodatkowe detale, współdzielone przez podgląd oraz gry z klasycznym modelem R6. Miniatury sklepu wyrenderowano z tych samych modeli.
Ubrania mają przeszycia i wykończenia, poprawiono także wychodzącą poza kadr twarz z sercami. Brak bonusów bojowych, lotu czy uprawnień moderatora za zakup kosmetyków.
Przy braku WebGL pozostaje podgląd 2D. Renderer 3D edytora jest zwalniany po opuszczeniu zakładki lub wejściu do gry.
Tak jak dotąd, portfel i kolekcja są lokalnym zapisem przeglądarki, nie serwerowym portfelem odpornym na modyfikacje. Podgląd Computer przechowuje te dane tylko w pamięci sesji.

## Historia ostatnio granych

Sekcja „Ostatnio grane” przechowuje do sześciu różnych dostępnych gier, od najnowszej.
Ponowne uruchomienie przesuwa tytuł na początek bez duplikatu. Aktualnie katalog zawiera trzy gry.
Historia jest lokalna dla profilu i przeglądarki; dotychczasowy pojedynczy zapis jest automatycznie odczytywany.
W podglądzie Computer pamięć jest sesyjna, tak jak pozostałe lokalne dane tego podglądu.

## Logo i pozostałe gry (13.0)

Nowy autorski znak „B”, wordmark i favicon zastępują pochylony kwadrat.
Katalog ma nowe okładki Castle Defense i piłki, kategorię Sport oraz czytelne oznaczenia trybów zamiast przykładowych procentów ocen na kartach.

Castle Defense zachowuje kolizje, 20 fal i ekonomię. Nowe modele obejmują zamek, pięć odrębnych typów wież, poziomy i przeciwników.
Dodano minimapę, opis wybranego typu, wybór klawiszami 1–5 oraz potwierdzaną sprzedaż najbliższej wieży (X) z dokładnym zwrotem 70% inwestycji.
Serwerowe działanie `sell` wymaga identyfikatora tej samej najbliższej wieży oraz dystansu do 7 metrów. Nieprawidłowe lub ponowne żądanie nie daje złota.
Przykładowo Strzelec poziomu 2 kosztował 90 i zwraca 63 zł, a poziomu 3 kosztował 170 i zwraca 119 zł.

Piłka Nożna 3D jest odblokowana jako beta wyłącznie SOLO.
Mecz 3 na 3: gracz, dwóch niebieskich botów oraz trzech czerwonych botów, z bramkarzem w każdej drużynie.
Sterowanie: WASD, E strzał na prawą bramkę, Q podanie, Shift sprint, P pauza; są też przyciski dotykowe i joystick.
Piłka ma fizykę stałego kroku 1/60 s, tarcie, odbicia, słupki i kontrolę pełnego przekroczenia linii bramkowej.
Mecz trwa do 5 goli lub 180 sekund aktywnej gry, z 2-sekundowymi wznowieniami po golach. Pauza zatrzymuje zegar.
Wygrana daje 200 lokalnych BloxBux raz na mecz; pełny mecz bez wygranej daje 30 po co najmniej 60 s aktywnej gry. Nagrody i portfel pozostają lokalne, niechronione przed ręczną edycją.
Piłka nie jest przyjmowana przez API pokoi i nie jest przedstawiana jako multiplayer.

Wydanie 13 zawiera klienta i serwer z obsługą `sell`; należy wdrażać je razem.
Użytkownik zatwierdził publikację po zakończeniu testów. Podgląd przeszedł 9 grup nowych funkcji i 3 grupy synchronizacji dwóch niezależnych kont. Testy backendu: 34 regresyjne, 17 botów, 10 sprzedaży wież oraz reset rundy CS. Wcześniejsze pełne testy klienta: 19 grup solo, 16 sieciowych i 8 Studio.

Serwer FastAPI udostępnia grę na `/`, API na `/api/*` i kontrolę stanu na `/health`.
Jedna instancja procesu obsługuje wspólną symulację pokoi.

## Wdrożenie

- Python 3.12, `pip install -r requirements.txt`, `python server.py`.
- Render: plan Free, Frankfurt, jedna instancja i jeden worker.
- `DATABASE_URL`: prywatny adres PostgreSQL Supabase z SSL. Nigdy nie umieszczaj go w HTML ani repozytorium.
- Wymagany osobny schemat `bloxweb`, tabela użytkowników i ograniczona rola `bloxweb_runtime`.
- `schema.sql` uruchamia administrator jednorazowo po utworzeniu roli; serwer nie ma praw do migracji.
- `ALLOWED_ORIGINS`: lista dozwolonych adresów strony oddzielona przecinkami.
- `TRUST_PREVIEW_PROXY` pozostaje wyłączone na Render.
- Bez `DATABASE_URL` tryb lokalny używa SQLite; na Render brak tej zmiennej przerywa start, zamiast tworzyć nietrwałą bazę.

## Portal, Studio i CS (12.0)

Nowy grafitowo-pomarańczowy interfejs zachowuje istniejące dane kont i funkcje społecznościowe.
CS ma prawą dłoń trzymającą pistolet, animowany odrzut i przeładowanie, szczegółowe modele operatorów i odświeżone materiały areny.
Boty solo oraz serwerowe używają ograniczonego wyszukiwania drogi A*, widoczności, opóźnienia reakcji, pamięci celu, flankowania i osłon.
Magazynek botów ma 8 nabojów, serie są krótkie, a przeładowanie trwa 1,8 s.
Wersja protokołu API pozostaje 11, zgodnie ze starszym klientem; wersja interfejsu to 12.

Zakładka „Twórz gry · Beta” zawiera edytor map 2D 24 × 14 oraz dwa szablony: obby i zbieranie monet.
Można ustawiać platformy, monety, lawę, start i metę, cofać zmiany oraz testować grę klawiaturą i dotykiem.
Nowe narzędzia: checkpointy, sprężyny, pędzel 1 × 1 / 3 × 3, prostokąty i wypełnienie.
Każdy projekt ma ustawienia prędkości (3–10), skoku (8–18) i grawitacji (18–40).
Starsze mapy dostają domyślne wartości fizyki 6/12/28; import jest nadal wyłącznie danymi.
Biblioteka pozwala duplikować mapy, pobierać JSON i wczytywać pliki do 60 KB.
Do 20 projektów jest zapisywanych lokalnie w przeglądarce, oddzielnie dla profilu.
Eksport/import JSON służy do przenoszenia map między urządzeniami; import nie wykonuje kodu.
Beta nie obejmuje publicznego katalogu gier, chmury ani multiplayera własnych map.
Bezpośredni adres `/#studio` otwiera Studio i tworzy pierwszy szablon, jeżeli biblioteka jest pusta.

Na poziomie strony blokowane są gesty zoomu, Ctrl/Cmd z +/−/0 oraz Ctrl z kółkiem.
Nie zastępuje to systemowych ustawień dostępności ani uprawnień przeglądarki.

## Przechowywanie i limity

Znajomi, zaproszenia, konta online i wiadomości są przechowywane w PostgreSQL.
Pokoje i trwające rundy pozostają w pamięci, więc znikają po restarcie.
### Końcowa poprawka wersji 13

- Niezależne kontakty dotykowe w CS: joystick, strzał, przeładowanie, zmiana broni i sklep.
- Zwolnienie innego palca nie zatrzymuje trzymanego strzału; anulowanie kontaktu i wyjście czyszczą sterowanie.
- Wspólny ekran przygotowania wszystkich trzech gier, pokoi online i testów Studio, kończący się po przygotowaniu pierwszego obrazu. Animacja respektuje ograniczenie ruchu.
- Zachowana końcowa poprawka dotyku awatara: obrót, kategorie, przymierzanie i zakupy bez podwójnego naliczenia.

Kod konta online jest prywatnym kluczem odzyskiwania; publiczny identyfikator BLOX nie daje dostępu do konta.
Monety, przedmioty i postęp dawnych kont nadal są zapisami lokalnymi przeglądarki.
Ta wersja nie zapewnia pełnego systemu anty-cheat ani moderacji publicznej platformy.

Render Free usypia nieaktywne usługi i współdzieli limit godzin w obrębie workspace:
https://render.com/docs/free
Supabase Free ma limity zasobów i może wstrzymać nieaktywny projekt:
https://supabase.com/pricing
