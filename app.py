"""Single-port, dependency-free Werewolf role draw service."""

from __future__ import annotations

import json
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs
from wsgiref.simple_server import make_server


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("WEREWOLF_DB_PATH", str(ROOT / "werewolf.sqlite3")))
GOD_ROLES = ("预言家", "女巫", "猎人", "白痴", "守卫", "丘比特")
MAX_PLAYERS = 30
LOGGER = logging.getLogger("werewolf")
LOGGER.setLevel(getattr(logging, os.environ.get("WEREWOLF_LOG_LEVEL", "INFO").upper(), logging.INFO))
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.propagate = False


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 15000")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            host_token TEXT NOT NULL,
            player_count INTEGER NOT NULL,
            wolf_count INTEGER NOT NULL,
            villager_count INTEGER NOT NULL,
            god_roles TEXT NOT NULL,
            white_wolf_king INTEGER NOT NULL,
            deck TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL REFERENCES games(id),
            nickname TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            role TEXT NOT NULL,
            joined_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS players_game_idx ON players(game_id);
    """)
    return db


def json_response(start_response, status, payload, extra_headers=()):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [("Content-Type", "application/json; charset=utf-8"),
               ("Content-Length", str(len(body))),
               ("Cache-Control", "no-store"),
               ("X-Content-Type-Options", "nosniff")]
    headers.extend(extra_headers)
    start_response(f"{status} {HTTPStatus(status).phrase}", headers)
    return [body]


def read_json(environ):
    if not environ.get("CONTENT_TYPE", "").split(";", 1)[0].strip() == "application/json":
        raise ApiError(415, "请使用 JSON 提交数据")
    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except ValueError:
        raise ApiError(400, "请求长度无效") from None
    if length < 1 or length > 4096:
        raise ApiError(400, "请求内容为空或过大")
    try:
        value = json.loads(environ["wsgi.input"].read(length))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ApiError(400, "JSON 格式无效") from None
    if not isinstance(value, dict):
        raise ApiError(400, "请求内容必须是对象")
    return value


def number(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApiError(400, f"{label}须为 {minimum}～{maximum} 的整数")
    return value


def build_deck(data):
    player_count = number(data.get("player_count"), "玩家人数", 3, MAX_PLAYERS)
    wolf_count = number(data.get("wolf_count"), "狼人数", 1, MAX_PLAYERS)
    villager_count = number(data.get("villager_count"), "平民人数", 0, MAX_PLAYERS)
    god_count = number(data.get("god_count"), "神职人数", 0, len(GOD_ROLES))
    gods = data.get("god_roles")
    if not isinstance(gods, list) or any(not isinstance(x, str) for x in gods):
        raise ApiError(400, "请选择神职身份")
    if len(gods) != god_count or len(set(gods)) != len(gods) or any(x not in GOD_ROLES for x in gods):
        raise ApiError(400, "所选神职必须互不重复，且与神职人数一致")
    white = data.get("white_wolf_king", False)
    if type(white) is not bool:
        raise ApiError(400, "白狼王设置无效")
    if wolf_count + villager_count + god_count != player_count:
        raise ApiError(400, "狼人、平民和神职人数之和须等于玩家人数")
    if wolf_count >= player_count:
        raise ApiError(400, "至少需要一名非狼人玩家")
    deck = (["普通狼人"] * (wolf_count - int(white)) +
            (["白狼王"] if white else []) +
            ["平民"] * villager_count + gods)
    secrets.SystemRandom().shuffle(deck)
    return player_count, wolf_count, villager_count, gods, white, deck


def game_summary(game, joined):
    return {
        "id": game["id"], "player_count": game["player_count"],
        "wolf_count": game["wolf_count"], "villager_count": game["villager_count"],
        "god_count": len(json.loads(game["god_roles"])),
        "god_roles": json.loads(game["god_roles"]),
        "white_wolf_king": bool(game["white_wolf_king"]),
        "joined_count": joined, "remaining_count": game["player_count"] - joined,
        "created_at": game["created_at"],
    }


def get_game(db, game_id):
    if not game_id or len(game_id) > 64:
        raise ApiError(404, "该对局不存在")
    game = db.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        raise ApiError(404, "该对局不存在")
    return game


def bearer(environ):
    authorization = environ.get("HTTP_AUTHORIZATION", "")
    if not authorization.startswith("Bearer "):
        raise ApiError(401, "缺少访问令牌")
    token = authorization[7:].strip()
    if not token or len(token) > 128:
        raise ApiError(401, "访问令牌无效")
    return token


def create_game(db, data):
    player_count, wolves, villagers, gods, white, deck = build_deck(data)
    game_id = secrets.token_urlsafe(9)
    host_token = secrets.token_urlsafe(32)
    created_at = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute("""INSERT INTO games
            (id, host_token, player_count, wolf_count, villager_count,
             god_roles, white_wolf_king, deck, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (game_id, host_token, player_count, wolves, villagers,
             json.dumps(gods, ensure_ascii=False), int(white),
             json.dumps(deck, ensure_ascii=False), created_at))
    LOGGER.info("game_created game_id=%s players=%d wolves=%d villagers=%d gods=%d white_wolf_king=%s",
                game_id, player_count, wolves, villagers, len(gods), white)
    return {"game_id": game_id, "host_token": host_token,
            "game": {"player_count": player_count, "wolf_count": wolves,
                     "villager_count": villagers, "god_count": len(gods)}}


def join_game(db, game_id, data):
    nickname = data.get("nickname")
    if not isinstance(nickname, str):
        raise ApiError(400, "请输入昵称")
    nickname = nickname.strip()
    if not nickname or len(nickname) > 24 or any(ord(c) < 32 for c in nickname):
        raise ApiError(400, "昵称须为 1～24 个可见字符")
    db.execute("BEGIN IMMEDIATE")
    try:
        game = get_game(db, game_id)
        players = db.execute("SELECT nickname FROM players WHERE game_id = ?", (game_id,)).fetchall()
        if any(p["nickname"].casefold() == nickname.casefold() for p in players):
            raise ApiError(409, "该昵称已被使用，请换一个")
        deck = json.loads(game["deck"])
        if not deck:
            raise ApiError(409, "身份已全部抽完")
        role = deck.pop()
        token = secrets.token_urlsafe(32)
        db.execute("UPDATE games SET deck = ? WHERE id = ?",
                   (json.dumps(deck, ensure_ascii=False), game_id))
        db.execute("INSERT INTO players (game_id, nickname, token, role, joined_at) VALUES (?, ?, ?, ?, ?)",
                   (game_id, nickname, token, role, datetime.now(timezone.utc).isoformat()))
        db.commit()
        LOGGER.info("player_joined game_id=%s joined=%d total=%d", game_id, len(players) + 1, game["player_count"])
        return {"nickname": nickname, "role": role, "player_token": token}
    except Exception:
        db.rollback()
        raise


def route_api(environ, method, path):
    parts = path.strip("/").split("/")
    db = connection()
    try:
        if parts == ["api", "games"] and method == "POST":
            return 201, create_game(db, read_json(environ))
        if len(parts) == 3 and parts[:2] == ["api", "games"] and method == "GET":
            game = get_game(db, parts[2])
            joined = db.execute("SELECT COUNT(*) FROM players WHERE game_id = ?", (parts[2],)).fetchone()[0]
            return 200, game_summary(game, joined)
        if len(parts) == 4 and parts[:2] == ["api", "games"]:
            game_id, action = parts[2:]
            if action == "join" and method == "POST":
                return 201, join_game(db, game_id, read_json(environ))
            if action == "me" and method == "GET":
                player = db.execute("SELECT nickname, role FROM players WHERE game_id = ? AND token = ?",
                                    (game_id, bearer(environ))).fetchone()
                if player is None:
                    raise ApiError(401, "个人令牌无效")
                return 200, dict(player)
            if action == "host" and method == "GET":
                game = get_game(db, game_id)
                if not secrets.compare_digest(game["host_token"], bearer(environ)):
                    raise ApiError(403, "主持人密钥无效")
                players = db.execute("SELECT nickname, role, joined_at FROM players WHERE game_id = ? ORDER BY id",
                                     (game_id,)).fetchall()
                return 200, {"game": game_summary(game, len(players)),
                             "players": [dict(p) for p in players]}
        raise ApiError(404, "接口不存在")
    finally:
        db.close()


def static_response(start_response, path):
    files = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/game": ("index.html", "text/html; charset=utf-8"),
        "/host": ("index.html", "text/html; charset=utf-8"),
        "/static/style.css": ("style.css", "text/css; charset=utf-8"),
        "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/static/favicon.svg": ("favicon.svg", "image/svg+xml"),
    }
    if path.startswith("/game/") or path.startswith("/host/"):
        path = "/game" if path.startswith("/game/") else "/host"
    item = files.get(path)
    if item is None:
        return json_response(start_response, 404, {"error": "页面不存在"})
    body = (STATIC / item[0]).read_bytes()
    start_response("200 OK", [("Content-Type", item[1]), ("Content-Length", str(len(body))),
                                 ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff")])
    return [body]


def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    method = environ.get("REQUEST_METHOD", "GET")
    if path.startswith("/api/") or path == "/api":
        try:
            status, payload = route_api(environ, method, path)
        except ApiError as exc:
            LOGGER.info("request_rejected method=%s path=%s status=%d reason=%s", method, path, exc.status, exc.message)
            status, payload = exc.status, {"error": exc.message}
        except sqlite3.Error:
            LOGGER.exception("database_error method=%s path=%s", method, path)
            status, payload = 503, {"error": "数据库暂时不可用，请稍后重试"}
        except Exception:
            LOGGER.exception("server_error method=%s path=%s", method, path)
            status, payload = 500, {"error": "服务器出错，请稍后重试"}
        return json_response(start_response, status, payload)
    if method != "GET":
        return json_response(start_response, 405, {"error": "不支持的请求方法"})
    return static_response(start_response, path)


if __name__ == "__main__":
    host = os.environ.get("WEREWOLF_HOST", "127.0.0.1")
    port = int(os.environ.get("WEREWOLF_PORT", "8000"))
    LOGGER.info("service_started address=http://%s:%d database=%s", host, port, DB_PATH)
    with make_server(host, port, application) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("service_stopped")
