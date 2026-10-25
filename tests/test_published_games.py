"""Studio 3D games: publishing, catalogue, reports and the AI proxy guard."""
from test_accounts_social import call, client, guest  # noqa: F401  (pytest fixture)

GAME = dict(format="bloxweb-nexus", version=1, settings=dict(speed=8, jump=12, gravity=30, sky="#8fd3ff"),
            parts=[dict(t="spawn", p=[0, 1, 0], s=[4, 1, 4], c="#70c6ff"),
                   dict(t="block", n="Most", p=[0, 0, 8], s=[4, 1, 10], c="#4eae79"),
                   dict(t="finish", p=[0, 1, 16], s=[4, 1, 4], c="#ffffff")],
            script='when start {\n  say("Witaj!")\n}\n')


def test_publish_list_play_and_update(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    published = call(client, "games_publish", token=ala["token"], title="Mój obby", description="Skacz!", game=GAME)
    game_id = published["id"]
    assert game_id.startswith("G-")

    listed = call(client, "games_list", token=olek["token"])
    assert [g["id"] for g in listed["games"]] == [game_id]
    assert listed["games"][0]["author"] == "Ala" and listed["mine"] == []

    opened = call(client, "games_get", token=olek["token"], id=game_id)
    assert opened["game"]["parts"][1]["n"] == "Most" and "say" in opened["game"]["script"]
    call(client, "games_get", token=olek["token"], id=game_id)
    assert call(client, "games_list", token=olek["token"])["games"][0]["plays"] == 1

    # Only the author may update; the id stays the same.
    call(client, "games_publish", 403, token=olek["token"], id=game_id, title="Cudza", game=GAME)
    call(client, "games_publish", token=ala["token"], id=game_id, title="Mój obby 2", game=GAME)
    assert call(client, "games_list", token=olek["token"])["games"][0]["title"] == "Mój obby 2"


def test_invalid_and_rude_games_are_rejected(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "games_publish", 400, token=ala["token"], title="Ok tytuł", game=dict(format="other"))
    call(client, "games_publish", 400, token=ala["token"], title="ab", game=GAME)
    call(client, "games_publish", 400, token=ala["token"], title="Kurwa gra", game=GAME)
    rude = dict(GAME, script='when start { say("ty ch.uj") say("CHUJ") }')
    call(client, "games_publish", 400, token=ala["token"], title="Fajna gra", game=rude)
    # Unknown part types are dropped and numbers are clamped.
    odd = dict(GAME, parts=[dict(t="bomb", p=[0, 0, 0]), dict(t="block", p=[9999, 0, 0], s=[0, 1, 1], c="red")])
    game_id = call(client, "games_publish", token=ala["token"], title="Dziwna", game=odd)["id"]
    stored = call(client, "games_get", token=ala["token"], id=game_id)["game"]["parts"]
    assert stored == [dict(t="block", p=[500, 0, 0], s=[.2, 1, 1], c="#9aa4b1")]


def test_three_reports_hide_a_game_and_author_can_withdraw(client):
    tokens = [guest(client, f"G{i}", f"BLOX-33333{i}")["token"] for i in range(5)]
    game_id = call(client, "games_publish", token=tokens[0], title="Gra testowa", game=GAME)["id"]
    call(client, "games_report", 400, token=tokens[0], id=game_id)
    for t in tokens[1:3]:
        call(client, "games_report", token=t, id=game_id, reason="brzydkie")
    call(client, "games_report", token=tokens[1], id=game_id)  # repeated report is not counted
    assert len(call(client, "games_list", token=tokens[4])["games"]) == 1
    call(client, "games_report", token=tokens[3], id=game_id)
    assert call(client, "games_list", token=tokens[4])["games"] == []
    call(client, "games_get", 404, token=tokens[4], id=game_id)
    # The author still sees it, flagged as hidden, and cannot republish over the review.
    assert call(client, "games_list", token=tokens[0])["mine"][0]["hidden"] == 1
    call(client, "games_publish", 403, token=tokens[0], id=game_id, title="Gra testowa", game=GAME)

    other = call(client, "games_publish", token=tokens[4], title="Druga gra", game=GAME)["id"]
    call(client, "games_unpublish", 403, token=tokens[0], id=other)
    call(client, "games_unpublish", token=tokens[4], id=other)
    assert call(client, "games_list", token=tokens[0])["games"] == []


def test_ai_is_off_without_worker_configuration(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "ai_code", 503, token=ala["token"], prompt="zrób obby")
    assert client.get("/health").json()["ai"] is False


def test_ai_proxy_limits_and_forwards_reference(client, monkeypatch):
    server = client.server
    sent = []
    monkeypatch.setattr(server, "AI_URL", "https://worker.test")
    monkeypatch.setattr(server, "AI_KEY", "sekret")
    monkeypatch.setattr(server, "ai_request", lambda prompt, code: sent.append((prompt, code)) or {"text": "```nexus\nsay(\"hej\")\n```"})
    ala = guest(client, "Ala", "BLOX-111111")
    assert "nexus" in call(client, "ai_code", token=ala["token"], prompt="zrób obby", code="var a = 1")["text"]
    assert sent == [("zrób obby", "var a = 1")]
    call(client, "ai_code", 400, token=ala["token"], prompt="kurwa gra")
    for _ in range(5):
        call(client, "ai_code", token=ala["token"], prompt="zrób wieżę")
    call(client, "ai_code", 429, token=ala["token"], prompt="jeszcze jedna")
    assert server.NEXUS_REFERENCE.startswith("# NexusScript")


def test_page_embeds_the_same_language_reference():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    page = (root / "public" / "index.html").read_text(encoding="utf-8")
    start = page.index('<script type="text/plain" id="nexusReference">\n') + len('<script type="text/plain" id="nexusReference">\n')
    embedded = page[start:page.index("</script>", start)]
    assert embedded == (root / "nexusscript.md").read_text(encoding="utf-8")
