// BloxWeb NexusScript assistant on Cloudflare Workers AI.
// Only the BloxWeb server calls it (shared secret in X-Blox-Key); players never see the key.
// The server sends the language reference, the player's request and the current code.

const DEFAULT_MODEL = "@cf/meta/llama-3.1-8b-instruct-fast";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json; charset=utf-8" } });
}

function sameKey(a, b) {
  // Constant-time comparison of the shared secret.
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export default {
  async fetch(request, env) {
    if (request.method !== "POST") return json({ error: "BloxWeb AI: tylko POST" }, 405);
    if (!env.BLOX_KEY || !sameKey(request.headers.get("x-blox-key") || "", env.BLOX_KEY)) return json({ error: "unauthorized" }, 401);
    let body;
    try { body = await request.json(); } catch { return json({ error: "bad json" }, 400); }
    const prompt = String(body.prompt || "").slice(0, 600);
    const code = String(body.code || "").slice(0, 8000);
    const reference = String(body.reference || "").slice(0, 12000);
    if (prompt.length < 3) return json({ error: "empty prompt" }, 400);
    const system =
      "Jesteś programistą gier dla dzieci na platformie BloxWeb. Piszesz WYŁĄCZNIE w języku NexusScript, " +
      "opisanym w dokumentacji poniżej. Nie używaj JavaScriptu, Lua ani funkcji spoza dokumentacji. " +
      "Każdy blok when/if/while/repeat/for/func ma klamry { }. Teksty dla gracza po polsku, odpowiednie dla dzieci. " +
      "Odpowiadasz jednym blokiem kodu ```nexus ... ``` z całym programem i niczym więcej.\n\n" + reference;
    const user = "Zadanie: " + prompt + (code.trim() ? "\n\nObecny kod gry (rozbuduj go albo popraw):\n```nexus\n" + code + "\n```" : "");
    try {
      const out = await env.AI.run(env.MODEL || DEFAULT_MODEL, {
        messages: [{ role: "system", content: system }, { role: "user", content: user }],
        max_tokens: 2048,
        temperature: 0.3,
      });
      return json({ text: String(out?.response || "") });
    } catch (error) {
      return json({ error: "model error" }, 502);
    }
  },
};
