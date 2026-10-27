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


def test_bloxbux_gains_are_rate_limited_from_the_first_sync(client):
    me = guest(client, "Ala", "BLOX-111111")
    first = dict(coins=120000, owned=[], badges=[], quests={})
    synced = call(client, "sync", token=me["token"], progress=dict(base=None, current=first))
    assert synced["progress"]["coins"] == 5000  # a fresh account cannot import a made-up fortune
    start = synced["progress"]
    hacked = dict(start, coins=999999)
    synced = call(client, "sync", token=me["token"], progress=dict(base=start, current=hacked))
    assert synced["progress"]["coins"] <= 5100  # the bucket is spent, only the slow refill gets through


def test_shop_items_cost_bloxbux_and_unknown_items_are_refused(client):
    me = guest(client, "Ala", "BLOX-111111")
    # The first sync spends the whole earning budget (5000), as an auto-clicker would.
    start = call(client, "sync", token=me["token"], progress=dict(base=None, current=dict(coins=5000, owned=[], badges=[], quests={})))["progress"]
    price = client.server.ITEM_PRICES["dominus"]
    # The cheat adds an expensive item but keeps the balance: with no earning budget left
    # the server takes the price from the balance.
    free = dict(start, owned=["dominus", "made_up_item"])
    after = call(client, "sync", token=me["token"], progress=dict(base=start, current=free))["progress"]
    assert after["owned"] == ["dominus"] and after["coins"] <= start["coins"]-price+50


def test_teleporting_and_flying_get_the_player_removed(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    client.server.rooms[room["code"]]["players"]["BLOX-111111"]["settleUntil"] = 0  # past the entry grace
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


def test_walking_through_a_wall_is_refused(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    server = client.server
    player = server.rooms[room["code"]]["players"]["BLOX-111111"]
    # The wall at x=-50 runs from z=-70 to z=-50; walk straight through it at normal speed.
    player.update(x=-52.5, z=-60, lastMove=server.now()-.2, settleUntil=0)
    server.room_input("BLOX-111111", dict(position=dict(x=-47.5, y=1.5, z=-60)))
    assert player["x"] == -52.5
    assert any(e["kind"] == "ściana" for e in server.anticheat_log)


def test_a_steady_speed_hack_is_held_to_the_game_speed(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    server = client.server
    player = server.rooms[room["code"]]["players"]["BLOX-111111"]
    player.update(x=-70, z=-80, settleUntil=0)
    for i in range(40):  # 4 seconds at 20 units/s, twice the real top speed
        player["lastMove"] = server.now()-.1
        server.room_input("BLOX-111111", dict(position=dict(x=player["x"]+2, y=1.5, z=-80)))
    assert player["x"]+70 < 4*server.SPEED_LIMIT["cs2"]+20


def test_respawn_while_alive_is_refused(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    server = client.server
    state = server.rooms[room["code"]]
    player = state["players"]["BLOX-111111"]
    player.update(x=-60, z=-60, hp=40)
    server.act(state, player, dict(kind="respawn"))
    assert (player["x"], player["hp"]) == (-60, 40)


def test_positions_right_after_entry_are_ignored_until_the_client_catches_up(client):
    me, room = room_for(client, "Ala", "BLOX-111111")
    server = client.server
    player = server.rooms[room["code"]]["players"]["BLOX-111111"]
    start = (player["x"], player["z"])
    server.room_input("BLOX-111111", dict(position=dict(x=20, y=1.5, z=20)))  # old spot from before entry
    assert (player["x"], player["z"]) == start and not server.anticheat_log
    server.room_input("BLOX-111111", dict(position=dict(x=start[0]+.5, y=1.5, z=start[1])))
    assert player["x"] == start[0]+.5 and player["settleUntil"] == 0


def test_only_the_tab_that_entered_steers_the_player(client):
    me = guest(client, "Ala", "BLOX-111111")
    room = call(client, "room", token=me["token"], action="create", game="cs2", tab="tab-A")["room"]
    server = client.server
    player = server.rooms[room["code"]]["players"]["BLOX-111111"]
    player["settleUntil"] = 0
    start = (player["x"], player["z"])
    # An old tab of the same account keeps sending its stale spot: ignored, no strikes.
    for _ in range(30):
        call(client, "sync", token=me["token"], tab="tab-B", position=dict(x=20, y=1.5, z=20))
    assert (player["x"], player["z"]) == start and not server.anticheat_log
    call(client, "sync", token=me["token"], tab="tab-A", position=dict(x=start[0]+.4, y=1.5, z=start[1]))
    assert player["x"] == start[0]+.4
