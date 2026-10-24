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


def test_login_errors_and_brute_force_limit(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "register", token=ala["token"], login="ala", password="tajne123")
    call(client, "login", 401, login="ala", password="zle-haslo")
    call(client, "login", 401, login="nikt", password="tajne123")
    for _ in range(9):
        call(client, "login", 401, login="ala", password="zle-haslo")
    call(client, "login", 429, login="ala", password="tajne123")


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


def test_health_reports_version(client):
    assert client.get("/health").json()["version"] == 14
