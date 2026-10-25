"""Live room socket and server-side anti-cheat checks."""
import json

from test_accounts_social import call, client, guest  # noqa: F401  (pytest fixture)


def room_for(c, name, pid, game="cs2"):
    me = guest(c, name, pid)
    room = call(c, "room", token=me["token"], action="create", game=game)["room"]
    return me, room


def receive(ws, kind, tries=60):
    for _ in range(tries):
        message = json.loads(ws.receive_text())
        if message["type"] == kind:
            return message
    raise AssertionError("no " + kind)


def test_socket_streams_room_state_and_accepts_input(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps(dict(token=me["token"])))
        assert receive(ws, "ready")["id"] == "BLOX-111111"
        state = receive(ws, "room")
        assert state["room"]["code"] == room["code"] and state["me"]["money"] == 800
        assert "acknowledgements" not in state["room"]["players"][0]
        ws.send_text(json.dumps(dict(type="in", position=dict(x=-69, y=1.5, z=-69), actions=[dict(seq=1, kind="chat", text="Hej!")])))
        for _ in range(60):
            state = receive(ws, "room")
            if state["me"]["sequence"] == 1 and state["room"]["chat"]:
                break
        assert state["room"]["chat"][-1]["text"] == "Hej!"
        assert state["room"]["players"][0]["x"] == -69
        ws.send_text(json.dumps(dict(type="ping", t=123)))
        assert receive(ws, "pong")["t"] == 123
    # With a socket the client asks /sync to leave the room out.
    assert call(client, "sync", token=me["token"], room=False)["room"] is None


def test_socket_rejects_unknown_token(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps(dict(token="zly-token")))
        try:
            ws.receive_text()
            assert False, "socket should close"
        except Exception:
            pass


def test_bloxbux_gains_are_rate_limited_after_first_import(client):
    me = guest(client, "Ala", "BLOX-111111")
    first = dict(coins=120000, owned=[], badges=[], quests={})
    synced = call(client, "sync", token=me["token"], progress=dict(base=None, current=first))
    assert synced["progress"]["coins"] == 120000  # existing saves are imported unchanged
    hacked = dict(first, coins=999999)
    synced = call(client, "sync", token=me["token"], progress=dict(base=first, current=hacked))
    assert synced["progress"]["coins"] == 125000  # only the 5000 bucket got through
    small = dict(first, coins=125025)
    assert call(client, "sync", token=me["token"], progress=dict(base=dict(first, coins=125000), current=small))["progress"]["coins"] <= 125025


def test_teleporting_and_flying_get_the_player_removed(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    notices = []
    for i in range(30):
        x = 80 if i % 2 else -80
        notices.append(call(client, "sync", token=me["token"], position=dict(x=x, y=1.5, z=-70))["notice"])
    assert any(n and "Wykryto" in n for n in notices)
    assert call(client, "sync", token=me["token"])["room"] is None
    server = client.server
    assert not server.rooms[room["code"]]["players"]


def test_room_chat_filter_and_rate_limit(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    synced = call(client, "sync", token=me["token"], actions=[dict(seq=1, kind="chat", text="ty kurwa"), dict(seq=2, kind="chat", text="Cześć"), dict(seq=3, kind="chat", text="Drugi")])
    acks = {a["seq"]: a["error"] for a in synced["room"]["players"][0]["acknowledgements"]}
    assert "niedozwolone" in acks[1] and acks[2] is None and "Za szybko" in acks[3]
    assert [m["text"] for m in synced["room"]["chat"]] == ["Cześć"]


def test_aimbot_headshot_rate_kicks_the_player(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    server = client.server
    state = server.rooms[room["code"]]
    player = state["players"]["BLOX-111111"]
    server.MAP.clear()
    for _ in range(45):
        state["enemies"] = [dict(id=1, x=player["x"], y=.5, z=player["z"]-20, hp=10**9, maxHp=100, cooldown=9, rot=0)]
        player.update(shootUntil=0, reloadUntil=0)
        player["weapons"][0]["ammo"] = 20
        head = state["enemies"][0]["y"]+2.6
        origin = [player["x"], head, player["z"]]
        server.act(state, player, dict(kind="shoot", origin=origin, direction=[0, 0, -1]))
        if "BLOX-111111" not in state["players"]:
            break
    assert "BLOX-111111" not in state["players"]
    assert "aimbot" in call(client, "sync", token=me["token"])["notice"]


def test_socket_accepts_the_page_origin_even_with_a_site_allowlist(client, monkeypatch):
    me, room = room_for(client, "Ala", "BLOX-111111")
    monkeypatch.setattr(client.server, "origins", ["https://bloxweb.pages.dev"])
    with client.websocket_connect("/ws", headers={"origin": "http://testserver"}) as ws:
        ws.send_text(json.dumps(dict(token=me["token"])))
        assert receive(ws, "ready")["id"] == "BLOX-111111"
    try:
        with client.websocket_connect("/ws", headers={"origin": "https://zla-strona.example"}) as ws:
            ws.send_text(json.dumps(dict(token=me["token"])))
            ws.receive_text()
        assert False, "foreign origin must be refused"
    except AssertionError:
        raise
    except Exception:
        pass
