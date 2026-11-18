import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_db = app.DB_PATH
        app.DB_PATH = Path(self.temp.name) / "test.sqlite3"

    def tearDown(self):
        app.DB_PATH = self.original_db
        self.temp.cleanup()

    def request(self, method, path, payload=None, token=None):
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_TYPE": "application/json" if payload is not None else "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        if token:
            environ["HTTP_AUTHORIZATION"] = f"Bearer {token}"
        result = {}

        def start_response(status, headers):
            result["status"] = int(status.split()[0])
            result["headers"] = dict(headers)

        raw = b"".join(app.application(environ, start_response))
        if result["headers"]["Content-Type"].startswith("application/json"):
            result["body"] = json.loads(raw)
        else:
            result["body"] = raw
        return result

    def create(self):
        data = {
            "player_count": 5, "wolf_count": 2, "villager_count": 1,
            "god_count": 2, "god_roles": ["预言家", "女巫"],
            "white_wolf_king": True,
        }
        response = self.request("POST", "/api/games", data)
        self.assertEqual(response["status"], 201)
        return response["body"]

    def test_role_distribution_and_permissions(self):
        game = self.create()
        game_id = game["game_id"]
        path = f"/api/games/{game_id}"
        self.assertEqual(self.request("GET", path)["body"]["joined_count"], 0)
        self.assertEqual(self.request("GET", path + "/host")["status"], 401)
        self.assertEqual(self.request("GET", path + "/host", token="wrong")["status"], 403)
        roles = []
        for i in range(5):
            joined = self.request("POST", path + "/join", {"nickname": f"玩家{i}"})
            self.assertEqual(joined["status"], 201)
            roles.append(joined["body"]["role"])
            self.assertEqual(self.request("GET", path + "/me", token=joined["body"]["player_token"])["body"]["role"], roles[-1])
        self.assertCountEqual(roles, ["白狼王", "普通狼人", "平民", "预言家", "女巫"])
        self.assertEqual(self.request("POST", path + "/join", {"nickname": "玩家0"})["status"], 409)
        self.assertEqual(self.request("POST", path + "/join", {"nickname": "新玩家"})["status"], 409)
        host = self.request("GET", path + "/host", token=game["host_token"])
        self.assertEqual(host["body"]["game"]["remaining_count"], 0)
        self.assertEqual(len(host["body"]["players"]), 5)
        self.assertNotIn("host_token", self.request("GET", path)["body"])
        self.assertNotIn("role", self.request("GET", path)["body"])

    def test_invalid_configuration_and_duplicate_nickname(self):
        invalid = {
            "player_count": 4, "wolf_count": 2, "villager_count": 1,
            "god_count": 1, "god_roles": ["女巫", "女巫"],
        }
        self.assertEqual(self.request("POST", "/api/games", invalid)["status"], 400)
        invalid["god_roles"] = ["女巫"]
        invalid["player_count"] = 5
        self.assertEqual(self.request("POST", "/api/games", invalid)["status"], 400)
        game = self.create()
        path = f"/api/games/{game['game_id']}/join"
        self.assertEqual(self.request("POST", path, {"nickname": " Alice "})["status"], 201)
        self.assertEqual(self.request("POST", path, {"nickname": "alice"})["status"], 409)

    def test_simultaneous_joins_never_overdraw(self):
        game = self.create()
        path = f"/api/games/{game['game_id']}/join"
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(lambda i: self.request("POST", path, {"nickname": f"P{i}"}), range(8)))
        self.assertEqual(sum(r["status"] == 201 for r in responses), 5)
        self.assertEqual(sum(r["status"] == 409 for r in responses), 3)
        self.assertEqual(self.request("GET", f"/api/games/{game['game_id']}")["body"]["joined_count"], 5)

    def test_pages_use_same_wsgi_app(self):
        for path in ["/", "/game/abc", "/host/abc", "/static/style.css", "/static/app.js"]:
            self.assertEqual(self.request("GET", path)["status"], 200)


if __name__ == "__main__":
    unittest.main()
