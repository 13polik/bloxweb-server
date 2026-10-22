"""Run: python -m unittest discover -s tests -v (isolated temporary SQLite)."""
import os
import tempfile
import unittest
from unittest.mock import patch

TEMP = tempfile.TemporaryDirectory()
os.environ["BLOX_DATA"] = TEMP.name
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_URL_FILE", None)
from fastapi.testclient import TestClient
import server
from studio import procedural, validate_project, from_ai
from maps import MAPS


class Release14(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def register(self):
        r = self.client.post("/api/session", json={"name": "Tester"})
        self.assertEqual(r.status_code, 200)
        return r.json()

    def post(self, user, operation, **body):
        return self.client.post("/api/"+operation, json={"token": user["token"], **body})

    def test_project_validation(self):
        p = procedural("Nocny tor monet i lawy")
        self.assertEqual(len(p["tiles"]), 336)
        for bad in ({**p, "tiles": [0]*336}, {**p, "tiles": p["tiles"]+[1]}, {**p, "kind": "javascript"}):
            with self.assertRaises(ValueError):
                validate_project(bad)
        compact = dict(name="Test AI", kind="coins", theme="night", terrain=[dict(x=4,y=11,w=3,h=1)],
                       objects=[dict(type="start",x=1,y=12),dict(type="finish",x=22,y=12),
                                dict(type="coin",x=5,y=10)])
        self.assertEqual(len(from_ai(compact)["tiles"]), 336)
        compact["objects"].append(dict(type="coin", x=4, y=11))
        with self.assertRaises(ValueError):
            from_ai(compact)

    def test_shared_publication_authorization_update_and_withdraw(self):
        owner, guest = self.register(), self.register()
        project = procedural("Mapa monet dla znajomych")
        result = self.post(owner, "studio", action="publish", project=project, description="<b>Opis</b>")
        self.assertEqual(result.status_code, 200, result.text)
        gid = result.json()["id"]
        self.assertIn(gid, [g["id"] for g in self.client.get("/api/games").json()["games"]])
        self.assertEqual(self.client.get("/api/games/"+gid).json()["project"]["tiles"], project["tiles"])
        self.assertEqual(self.post(guest, "studio", action="unpublish", id=gid).status_code, 403)
        project["name"] = "Nowy tytuł"
        self.assertEqual(self.post(owner, "studio", action="publish", project=project).json()["id"], gid)
        self.post(guest, "studio", action="play", id=gid)
        self.assertEqual(self.post(owner, "studio", action="mine").json()["games"][0]["plays"], 1)
        self.assertEqual(self.post(owner, "studio", action="unpublish", id=gid).status_code, 200)
        self.assertEqual(self.client.get("/api/games/"+gid).status_code, 404)

    def test_ai_unavailable_is_not_fake_ai(self):
        user = self.register()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertEqual(self.post(user, "studio", action="generate", prompt="Tor przeszkód z monetami", mode="ai").status_code, 503)
        result = self.post(user, "studio", action="generate", prompt="Tor przeszkód z monetami", mode="procedural").json()
        self.assertEqual(result["generator"], "procedural")
        self.assertEqual(result["project"]["kind"], "coins")

    def test_room_votes_change_geometry_and_restart_votes_again(self):
        owner, guest = self.register(), self.register()
        result = self.post(owner, "room", action="create", game="cs2")
        code = result.json()["room"]["code"]
        self.post(guest, "room", action="join", code=code)
        room = server.rooms[code]
        a, b = room["players"].values()
        self.assertEqual(room["phase"], "voting")
        self.assertIsNotNone(server.act(room, a, {"kind": "map_vote", "mapId": "INVALID"}))
        self.assertIsNone(server.act(room, a, {"kind": "map_vote", "mapId": "temple"}))
        server.tick(room, .05)
        self.assertEqual(room["phase"], "voting")
        server.act(room, b, {"kind": "map_vote", "mapId": "temple"})
        server.tick(room, .05)
        self.assertEqual((room["phase"], room["mapId"], room["generation"]), ("playing", "temple", 2))
        self.assertEqual(len(room["enemies"]), 5)
        self.assertTrue(all(server.free(e["x"], e["z"], room) for e in room["enemies"]))
        room["owner"] = a["id"]
        room["phase"] = "won"
        server.act(room, a, {"kind": "restart"})
        self.assertEqual(room["phase"], "voting")
        self.assertEqual(room["votes"], {})

    def test_timeout_and_per_map_collision(self):
        user = self.register()
        room = server.create_room(user["user"]["id"], "cs2")
        room["voteUntil"] = 0
        server.tick(room, .05)
        self.assertEqual(room["phase"], "playing")
        self.assertIn(room["mapId"], MAPS)
        for key in MAPS:
            room["mapId"] = key
            self.assertTrue(server.free(-70, -70, room))
        room["mapId"] = "temple"
        self.assertFalse(server.free(0, 0, room))
        room["mapId"] = "depot"
        self.assertTrue(server.free(0, -36, room))


if __name__ == "__main__":
    unittest.main()
