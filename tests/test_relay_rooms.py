"""Relay rooms: parkour and Studio games run in the browser, the server shares positions and messages."""
from test_accounts_social import call, client, guest  # noqa: F401  (pytest fixture)
from test_published_games import GAME


def test_studio_game_room_shares_positions_and_script_messages(client):
    ala, olek = guest(client, "Ala", "BLOX-111111"), guest(client, "Olek", "BLOX-222222")
    gid = call(client, "games_publish", token=ala["token"], title="Wyścig", game=GAME)["id"]
    room = call(client, "room", token=ala["token"], action="create", game="nexus:" + gid.lower(), tab="a")["room"]
    assert room["game"] == "nexus:" + gid
    call(client, "room", token=olek["token"], action="join", code=room["code"], tab="b")
    # Scripts may teleport and drive fast: far moves are shared as they are, without strikes.
    state = call(client, "sync", token=ala["token"], tab="a", position=dict(x=900, y=40, z=-700),
                 actions=[dict(seq=1, kind="msg", name="punkt", value={"__d": [["gracz", "Ala"]]})])["room"]
    me = next(p for p in state["players"] if p["id"] == "BLOX-111111")
    assert (me["x"], me["y"], me["z"]) == (900, 40, -700) and not client.server.anticheat_log
    seen = call(client, "sync", token=olek["token"], tab="b")["room"]
    assert seen["events"][-1]["name"] == "punkt" and seen["events"][-1]["sender"] == "BLOX-111111"
    assert not seen["enemies"]  # nothing is simulated in a relay room


def test_studio_rooms_only_for_catalogue_games_and_messages_are_limited(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "room", 404, token=ala["token"], action="create", game="nexus:G-NOPE00")
    gid = call(client, "games_publish", token=ala["token"], title="Gra", game=GAME)["id"]
    call(client, "room", token=ala["token"], action="create", game="nexus:" + gid, tab="a")
    big = call(client, "sync", token=ala["token"], tab="a", actions=[dict(seq=1, kind="msg", name="x", value="y" * 700)])
    acks = {a["seq"]: a["error"] for a in big["room"]["players"][0]["acknowledgements"]}
    assert "za duża" in acks[1]
    flood = call(client, "sync", token=ala["token"], tab="a", actions=[dict(seq=10 + i, kind="msg", name="m", value=i) for i in range(15)])
    assert len(flood["room"]["events"]) == 10


def test_parkour_room_announces_new_stages(client):
    ala = guest(client, "Ala", "BLOX-111111")
    call(client, "room", token=ala["token"], action="create", game="obby", tab="a")
    state = call(client, "sync", token=ala["token"], tab="a", actions=[dict(seq=1, kind="stage", stage=3), dict(seq=2, kind="stage", stage=2)])["room"]
    texts = [m["text"] for m in state["chat"]]
    assert texts == ["Ala dotarł do etapu 3!"]
