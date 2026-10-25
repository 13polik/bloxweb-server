# BloxWeb AI (Cloudflare Workers AI)

Model językowy dla asystenta NexusScript w Studio 3D. Działa na serwerach Cloudflare, więc telefon gracza tylko wysyła prośbę. Klucz nie trafia do kodu strony.

Przepływ: strona → serwer BloxWeb (`/api/ai_code`, limity: 6 próśb na 10 minut na gracza, dzienny limit `BLOX_AI_DAILY_LIMIT`, domyślnie 250) → ten worker → Workers AI.

## Wdrożenie (raz)

Wariant A, terminal (wymaga Node.js):

```bash
cd ai-worker
npx wrangler login
npx wrangler deploy
npx wrangler secret put BLOX_KEY
```

Wariant B, panel Cloudflare: Workers & Pages → Create → Worker → wklej `src/index.js`. Potem w ustawieniach workera dodaj binding Workers AI o nazwie `AI` i sekret `BLOX_KEY`.

Następnie w Render (usługa bloxweb-server → Environment) ustaw:

- `BLOX_AI_URL`: adres workera, np. `https://bloxweb-ai.<twoje-konto>.workers.dev`
- `BLOX_AI_KEY`: ta sama wartość co `BLOX_KEY`

`/health` pokazuje `"ai": true`, gdy serwer ma oba ustawienia.

## Limity

Darmowy plan Workers AI ma dzienny limit (10 000 „neuronów”). Przy modelu `llama-3.1-8b-instruct-fast` to ok. 200–300 odpowiedzi na dobę. Po wyczerpaniu limitu asystent zwraca błąd do następnego dnia, bez opłat. Wbudowany asystent i prompt dla innych AI działają dalej.
