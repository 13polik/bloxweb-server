"""Nick rules: the reserved official account, staff names, staff-like words and unique nicks."""
import re

from test_accounts_social import call, client, guest  # noqa: F401  (pytest fixture)


def test_official_account_is_reserved_and_cannot_be_befriended(client):
    official = client.server.profile(client.server.OFFICIAL_ID)
    assert official["name"] == "BloxWeb" and official["role"] == "official"
    for fake in ["BloxWeb", "Bl0x_Web", "B L O X W E B", "bloxxweb", "BloxWebFan"]:
        player = guest(client, fake, "BLOX-" + re.sub(r"[^A-Z0-9]", "", fake.upper())[:8] + "X")
        assert re.fullmatch(r"Gracz\d{4,5}", player["user"]["name"]), player["user"]["name"]
        assert "zarezerwowany" in player["notice"]
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "friend", 400, token=ala["token"], target=client.server.OFFICIAL_ID, action="request")
    overview_count = client.server.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert overview_count == 7


def test_staff_nicks_belong_to_staff_only(client):
    owner = guest(client, "13polik", "BLOX-759762")
    assert owner["user"]["name"] == "13polik" and owner["notice"] is None
    for fake in ["I3polik", "l3p0lik", "13polik_fan", "Mikołaj Ps"]:
        player = guest(client, fake, "BLOX-" + str(abs(hash(fake)) % 900000 + 100000))
        assert player["user"]["name"].startswith("Gracz"), (fake, player["user"]["name"])


def test_staff_like_words_are_refused_for_players(client):
    for word in ["Admin", "4dm1n", "Moderator", "CEO", "Support_BloxWeb"]:
        player = guest(client, word, "BLOX-" + str(abs(hash(word)) % 900000 + 100000))
        assert player["user"]["name"].startswith("Gracz"), (word, player["user"]["name"])
    assert guest(client, "Modelarz", "BLOX-333333")["user"]["name"] == "Modelarz"


def test_nicks_are_unique_and_renames_to_taken_nicks_are_refused(client):
    first = guest(client, "Ola", "BLOX-111111")
    second = guest(client, "OLA", "BLOX-222222")
    assert first["user"]["name"] == "Ola"
    assert re.fullmatch(r"OLA\d{4,5}", second["user"]["name"]) and "zajęty" in second["notice"]
    kuba = guest(client, "Kuba", "BLOX-333333")
    refused = call(client, "sync", token=kuba["token"], profile={"name": "0la", "avatar": {}})
    assert refused["user"]["name"] == "Kuba" and "zajęty" in refused["notice"]
    renamed = call(client, "sync", token=kuba["token"], profile={"name": "Kuba2", "avatar": {}})
    assert renamed["user"]["name"] == "Kuba2" and renamed["notice"] is None
    # The old nick is free again.
    assert guest(client, "Kuba", "BLOX-444444")["user"]["name"] == "Kuba"


def test_existing_repeats_and_fakes_are_renamed_on_start(client):
    server = client.server
    for uid, name, created in [("BLOX-A1", "Zosia", 1), ("BLOX-A2", "zosia", 2), ("BLOX-A3", "B1oxWeb", 3)]:
        server.db.execute("INSERT INTO users(id,token_hash,name,avatar,created) VALUES(?,?,?,?,?)",
                          (uid, "t-" + uid, name, "{}", created))
    server.prepare_names()
    names = {r["id"]: r["name"] for r in server.db.execute("SELECT id,name FROM users").fetchall()}
    assert names["BLOX-A1"] == "Zosia"
    assert re.fullmatch(r"zosia\d{4,5}", names["BLOX-A2"])
    assert names["BLOX-A3"].startswith("Gracz") and names[server.OFFICIAL_ID] == "BloxWeb"


def test_look_alike_alphabets_cannot_fake_a_nick(client):
    # Cyrillic о/х/А and Greek Β look like Latin letters.
    for i, fake in enumerate(["BlохWeb", "13pоlik", "ΒloxWeb", "Аdmin"]):
        player = guest(client, fake, "BLOX-55555" + str(i))
        assert player["user"]["name"].startswith("Gracz"), (fake, player["user"]["name"])
    assert guest(client, "Żaneta_Łódź", "BLOX-666666")["user"]["name"] == "Żaneta_Łódź"
