"""API regression tests on a throwaway SQLite database.

Run: python -m pytest tests  (needs httpx and pytest, see requirements-dev.txt)
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as data:
        monkeypatch.setenv("DATA_DIR", data)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("RENDER", raising=False)
        sys.path.insert(0, str(ROOT))
        sys.modules.pop("server", None)
        server = importlib.import_module("server")
        with TestClient(server.app) as c:
            c.server = server
            yield c
        server.db.close()
        sys.path.remove(str(ROOT))


def call(c, operation, status=200, **body):
    response = c.post("/api/" + operation, json=body)
    assert response.status_code == status, response.text
    return response.json()


def guest(c, name, pid):
    return call(c, "session", token="", id=pid, name=name, avatar={})


def test_guest_session_is_reused_by_token(client):
    first = guest(client, "Ala", "BLOX-111111")
    again = call(client, "session", token=first["token"], name="Ala", avatar={})
    assert again["user"]["id"] == first["user"]["id"] == "BLOX-111111"
    assert first["account"] == {"login": None}


def test_register_then_login_on_another_device_keeps_friends_and_messages(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    call(client, "friend", token=ala["token"], target="BLOX-222222", action="request")
    call(client, "friend", token=olek["token"], target="BLOX-111111", action="accept")
    call(client, "message", token=olek["token"], target="BLOX-111111", text="Cześć!")

    registered = call(client, "register", token=ala["token"], login="Ala_Gra", password="tajne123")
    assert registered["account"] == {"login": "ala_gra"}

    # A different device: no token, only login and password.
    device = call(client, "login", login="ala_gra", password="tajne123")
    assert device["user"]["id"] == "BLOX-111111"
    assert device["token"] != ala["token"]
    assert [f["id"] for f in device["social"]["friends"]] == ["BLOX-222222"]
    assert device["social"]["messages"][-1]["text"] == "Cześć!"
    # Both the original guest token and the new device token stay valid.
    for token in (ala["token"], device["token"]):
        assert call(client, "sync", token=token)["user"]["id"] == "BLOX-111111"


def test_message_reaches_recipient_on_next_sync(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    call(client, "friend", token=ala["token"], target="BLOX-222222", action="request")
    before = call(client, "sync", token=olek["token"])  # warms Olek's cache
    assert [u["id"] for u in before["social"]["incoming"]] == ["BLOX-111111"]
    call(client, "friend", token=olek["token"], target="BLOX-111111", action="accept")
    call(client, "message", token=ala["token"], target="BLOX-222222", text="Gramy?")
    after = call(client, "sync", token=olek["token"])
    assert after["social"]["messages"][-1] == {**after["social"]["messages"][-1], "sender": "BLOX-111111", "text": "Gramy?"}
    assert [u["id"] for u in after["social"]["friends"]] == ["BLOX-111111"]


def test_profile_changes_are_visible_to_friends(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    call(client, "friend", token=ala["token"], target="BLOX-222222", action="request")
    call(client, "friend", token=olek["token"], target="BLOX-111111", action="accept")
    call(client, "sync", token=ala["token"], profile={"name": "AlaNowa", "avatar": {"pants": "jeans"}})
    friends = call(client, "sync", token=olek["token"])["social"]["friends"]
    assert friends[0]["name"] == "AlaNowa" and friends[0]["avatar"]["pants"] == "jeans"


def test_reconnect_with_keep_profile_does_not_revert_a_rename_from_another_device(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "register", token=ala["token"], login="ala", password="tajne123")
    phone = call(client, "login", login="ala", password="tajne123")
    call(client, "sync", token=phone["token"], profile={"name": "AlaZTelefonu", "avatar": {}})
    # The computer reconnects with its stale local nick but nothing edited locally.
    back = call(client, "session", token=ala["token"], name="Ala", avatar={}, keepProfile=True)
    assert back["user"]["name"] == "AlaZTelefonu"
    assert call(client, "sync", token=ala["token"])["user"]["name"] == "AlaZTelefonu"


def progress(coins, owned=("none",), claimed=()):
    return {"coins": coins, "owned": list(owned), "badges": ["b_welcome"], "quests": {"q_coins": 0, "claimed": list(claimed)}}


def test_bloxbux_and_items_follow_the_account_to_another_device(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "register", token=ala["token"], login="ala", password="tajne123")
    first = call(client, "sync", token=ala["token"], progress={"base": None, "current": progress(750, ["none", "jeans"])})
    assert first["progress"]["coins"] == 750
    phone = call(client, "login", login="ala", password="tajne123")
    assert phone["progress"]["coins"] == 750 and "jeans" in phone["progress"]["owned"]


def test_changes_from_two_devices_add_up_instead_of_overwriting(client):
    ala = guest(client, "Ala", "BLOX-111111")
    base = call(client, "sync", token=ala["token"], progress={"base": None, "current": progress(500)})["progress"]
    # Computer earns 200 while the phone spends 100 on a hat, both from 500.
    call(client, "sync", token=ala["token"], progress={"base": base, "current": progress(700)})
    after = call(client, "sync", token=ala["token"], progress={"base": base, "current": progress(400, ["none", "cap"])})["progress"]
    assert after["coins"] == 600 and "cap" in after["owned"]


def test_first_sync_of_a_new_device_does_not_double_coins(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "sync", token=ala["token"], progress={"base": None, "current": progress(900)})
    merged = call(client, "sync", token=ala["token"], progress={"base": None, "current": progress(500, ["none", "camo"])})["progress"]
    assert merged["coins"] == 900 and "camo" in merged["owned"]


def test_progress_is_validated_and_private(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    bad = {"coins": -5, "owned": ["ok_item", "<script>", 7], "badges": "x", "quests": {"q_coins": "9", "claimed": ["q_a"]}}
    saved = call(client, "sync", token=ala["token"], progress={"base": None, "current": bad})["progress"]
    assert saved == {"coins": 0, "owned": ["ok_item"], "badges": [], "quests": {"q_coins": 9, "claimed": ["q_a"]}}
    call(client, "friend", token=ala["token"], target="BLOX-222222", action="request")
    call(client, "friend", token=olek["token"], target="BLOX-111111", action="accept")
    assert "progress" not in str(call(client, "sync", token=olek["token"])["social"])


def test_login_errors_and_brute_force_limit(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "register", token=ala["token"], login="ala", password="tajne123")
    call(client, "login", 401, login="ala", password="zle-haslo")
    call(client, "login", 401, login="nikt", password="tajne123")
    for _ in range(9):
        call(client, "login", 401, login="ala", password="zle-haslo")
    call(client, "login", 429, login="ala", password="tajne123")


def test_failed_logins_are_limited_per_address_across_logins(client):
    for n in range(30):
        call(client, "login", 401, login=f"konto{n}", password="zle-haslo")
    call(client, "login", 429, login="jeszcze_inne", password="zle-haslo")


def test_a_class_behind_one_address_can_all_connect(client):
    for n in range(40):
        guest(client, f"Uczen{n}", f"BLOX-{100000+n}")


def test_register_validation(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    call(client, "register", 400, token=ala["token"], login="a", password="tajne123")
    call(client, "register", 400, token=ala["token"], login="ala", password="123")
    call(client, "register", token=ala["token"], login="ala", password="tajne123")
    call(client, "register", 400, token=ala["token"], login="ala2", password="tajne123")
    call(client, "register", 409, token=olek["token"], login="ALA", password="tajne123")


def test_logout_ends_only_that_device(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "register", token=ala["token"], login="ala", password="tajne123")
    phone = call(client, "login", login="ala", password="tajne123")
    call(client, "logout", token=phone["token"])
    call(client, "sync", 401, token=phone["token"])
    assert call(client, "sync", token=ala["token"])["user"]["id"] == "BLOX-111111"


def test_login_never_leaks_into_public_profiles(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    call(client, "register", token=ala["token"], login="ala", password="tajne123")
    found = call(client, "search", token=olek["token"], query="Ala")["users"]
    assert found and "login" not in found[0] and "ala" not in str(found[0]).replace("Ala", "")


def test_room_create_join_chat_and_join_friend(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    room = call(client, "room", token=ala["token"], action="create", game="cs2", public=True)["room"]
    joined = call(client, "room", token=olek["token"], action="join", code=room["code"])["room"]
    assert {p["id"] for p in joined["players"]} == {"BLOX-111111", "BLOX-222222"}
    call(client, "sync", token=olek["token"], actions=[{"seq": 1, "kind": "chat", "text": "hej"}])
    assert call(client, "sync", token=ala["token"])["room"]["chat"][-1]["text"] == "hej"
    call(client, "room", 403, token=olek["token"], action="friend", target="BLOX-111111")
    call(client, "room", token=olek["token"], action="leave")
    assert [p["id"] for p in call(client, "sync", token=ala["token"])["room"]["players"]] == ["BLOX-111111"]


def test_health_reports_version(client):
    assert client.get("/health").json()["version"] == 19
