"""Staff roles, account blocking and cloud-saved Studio projects."""
from test_accounts_social import call, client, guest  # noqa: F401  (pytest fixture)
from test_published_games import GAME


def staff(c):
    owner, admin, player = guest(c, "13polik", "BLOX-759762"), guest(c, "Mikolaj_Ps", "BLOX-828719"), guest(c, "Gracz", "BLOX-333333")
    c.server.db.execute("UPDATE users SET role='owner' WHERE id='BLOX-759762'")
    c.server.db.execute("UPDATE users SET role='admin' WHERE id='BLOX-828719'")
    c.server.db.commit()
    c.server.user_cache.clear()
    return owner, admin, player


def test_roles_are_visible_and_role_badges_cannot_be_forged(client):
    owner, admin, player = staff(client)
    assert call(client, "sync", token=owner["token"])["user"]["role"] == "owner"
    found = call(client, "search", token=player["token"], query="BLOX-828719")["users"][0]
    assert found["role"] == "admin"
    forged = dict(coins=0, owned=[], badges=["b_ceo", "b_admin", "b_obby"], quests={})
    synced = call(client, "sync", token=player["token"], progress=dict(base=None, current=forged))
    assert synced["progress"]["badges"] == ["b_obby"] and synced["user"]["role"] is None


def test_admin_tools_and_owner_only_actions(client):
    owner, admin, player = staff(client)
    call(client, "admin_overview", 403, token=player["token"])
    overview = call(client, "admin_overview", token=admin["token"])
    assert overview["users"] == 3 and {s["id"] for s in overview["staff"]} == {"BLOX-759762", "BLOX-828719"}
    assert call(client, "admin_user", token=admin["token"], query="333333")["users"][0]["id"] == "BLOX-333333"
    # Admin may kick but not ban or promote; nobody can touch the owner.
    call(client, "admin_ban", 403, token=admin["token"], target="BLOX-333333", banned=True)
    call(client, "admin_role", 403, token=admin["token"], target="BLOX-333333", role="admin")
    call(client, "admin_kick", 403, token=admin["token"], target="BLOX-759762")
    call(client, "admin_ban", 403, token=owner["token"], target="BLOX-759762", banned=True)
    # Owner bans: the player is locked out until unbanned.
    assert call(client, "admin_ban", token=owner["token"], target="BLOX-333333", banned=True)["user"]["banned"] is True
    call(client, "sync", 403, token=player["token"])
    call(client, "admin_ban", token=owner["token"], target="BLOX-333333", banned=False)
    call(client, "sync", token=player["token"])
    assert call(client, "admin_role", token=owner["token"], target="BLOX-333333", role="admin")["user"]["role"] == "admin"
    call(client, "admin_overview", token=player["token"])


def test_admin_restores_or_hides_reported_games(client):
    owner, admin, player = staff(client)
    reporters = [guest(client, f"R{i}", f"BLOX-44444{i}")["token"] for i in range(3)]
    game_id = call(client, "games_publish", token=player["token"], title="Do sprawdzenia", game=GAME)["id"]
    for t in reporters:
        call(client, "games_report", token=t, id=game_id, reason="test")
    listed = call(client, "admin_games", token=admin["token"])["games"]
    assert listed[0]["id"] == game_id and listed[0]["hidden"] == 1 and len(listed[0]["reasons"]) == 3
    call(client, "admin_game", token=admin["token"], id=game_id, action="show")
    assert [g["id"] for g in call(client, "games_list", token=owner["token"])["games"]] == [game_id]
    call(client, "admin_game", token=admin["token"], id=game_id, action="hide")
    assert call(client, "games_list", token=owner["token"])["games"] == []


def test_cover_is_stored_only_when_it_is_an_image(client):
    ala = guest(client, "Ala", "BLOX-111111")
    cover = "data:image/jpeg;base64," + "A" * 400
    call(client, "games_publish", token=ala["token"], title="Z okładką", game=GAME, cover=cover)
    call(client, "games_publish", token=ala["token"], title="Zła okładka", game=GAME, cover="javascript:alert(1)")
    covers = {g["title"]: g["cover"] for g in call(client, "games_list", token=ala["token"])["games"]}
    assert covers == {"Z okładką": cover, "Zła okładka": None}


def test_studio_projects_sync_between_devices(client):
    ala = guest(client, "Ala", "BLOX-111111")
    project = dict(GAME, id="proj-1", name="Mój świat", updated=1000, publishedId="G-ABC123", description="opis")
    call(client, "projects_save", token=ala["token"], project=project)
    call(client, "projects_save", token=ala["token"], project=dict(project, name="Mój świat 2", updated=2000))
    listed = call(client, "projects_list", token=ala["token"])["projects"]
    assert listed == [dict(id="proj-1", name="Mój świat 2", updated=2000)]
    got = call(client, "projects_get", token=ala["token"], id="proj-1")["project"]
    assert got["publishedId"] == "G-ABC123" and got["parts"][1]["n"] == "Most"
    # Other players cannot read it.
    olek = guest(client, "Olek", "BLOX-222222")
    call(client, "projects_get", 404, token=olek["token"], id="proj-1")
    call(client, "projects_save", 400, token=ala["token"], project=dict(project, id="../zle"))
    for i in range(19):
        call(client, "projects_save", token=ala["token"], project=dict(project, id=f"proj-x{i}"))
    call(client, "projects_save", 400, token=ala["token"], project=dict(project, id="proj-21"))
    call(client, "projects_delete", token=ala["token"], id="proj-1")
    assert len(call(client, "projects_list", token=ala["token"])["projects"]) == 19
