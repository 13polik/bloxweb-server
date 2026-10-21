# BloxWeb 11: serwer i strona

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

## Studio Beta (11.1)

Zakładka „Twórz gry · Beta” zawiera edytor map 2D 24 × 14 oraz dwa szablony: obby i zbieranie monet.
Można ustawiać platformy, monety, lawę, start i metę, cofać zmiany oraz testować grę klawiaturą i dotykiem.
Do 20 projektów jest zapisywanych lokalnie w przeglądarce, oddzielnie dla profilu.
Eksport/import JSON służy do przenoszenia map między urządzeniami; import nie wykonuje kodu.
Beta nie obejmuje publicznego katalogu gier, chmury ani multiplayera własnych map.
Bezpośredni adres `/#studio` otwiera Studio i tworzy pierwszy szablon, jeżeli biblioteka jest pusta.

Na poziomie strony blokowane są gesty zoomu, Ctrl/Cmd z +/−/0 oraz Ctrl z kółkiem.
Nie zastępuje to systemowych ustawień dostępności ani uprawnień przeglądarki.

## Przechowywanie i limity

Znajomi, zaproszenia, konta online i wiadomości są przechowywane w PostgreSQL.
Pokoje i trwające rundy pozostają w pamięci, więc znikają po restarcie.
Kod konta online jest prywatnym kluczem odzyskiwania; publiczny identyfikator BLOX nie daje dostępu do konta.
Monety, przedmioty i postęp dawnych kont nadal są zapisami lokalnymi przeglądarki.
Ta wersja nie zapewnia pełnego systemu anty-cheat ani moderacji publicznej platformy.

Render Free usypia nieaktywne usługi i współdzieli limit godzin w obrębie workspace:
https://render.com/docs/free
Supabase Free ma limity zasobów i może wstrzymać nieaktywny projekt:
https://supabase.com/pricing
