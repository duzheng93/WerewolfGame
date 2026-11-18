# 月下密令：狼人杀身份抽取

一个 Python 程序同时提供页面和接口，身份与对局保存在 SQLite。无需安装 Python 包即可运行。

如果目标服务器的 Python 是自行编译的，且 `python -c 'import sqlite3'` 报 `No module named '_sqlite3'`，可在虚拟环境安装 `pysqlite3-binary`；程序会自动改用该 SQLite 驱动。正常的 Python 安装不需要此依赖。目标服务器的 Gunicorn 需要另行安装。

```bash
PIP_CONFIG_FILE=/dev/null .venv/bin/python -m pip install \
  --index-url https://mirrors.aliyun.com/pypi/simple/ pysqlite3-binary==0.5.4.post2
.venv/bin/python -c 'import pysqlite3; print(pysqlite3.sqlite_version)'
```

## 功能

- 主持人设定玩家、狼人、平民与神职人数，并从预言家、女巫、猎人、白痴、守卫、丘比特中选择神职。每种神职最多一位。
- 可选一位白狼王，占用一个狼人名额；其余狼人均为普通狼人。
- 建局时使用系统安全随机数洗牌。玩家凭分享链接输入昵称并领取一张未发出的身份牌。
- 玩家只能凭个人令牌查看自己的身份；主持人凭专属链接查看昵称与身份。链接中的令牌位于 URL 片段，不会随页面请求发给服务器。
- 同局昵称不区分大小写且不能重复；满员后不可再领取。数据库事务保证同时加入时不会重复发牌。

## 本地启动

```bash
WEREWOLF_DB_PATH=/tmp/werewolf-dev.sqlite3 \
WEREWOLF_HOST=127.0.0.1 \
WEREWOLF_PORT=8000 \
/home/tuke/opencode/wolf_env/bin/python3 app.py
```

打开 `http://127.0.0.1:8000/`。直接运行时默认监听 `127.0.0.1:8000`，数据库默认位于项目目录；在当前 SMB 工作空间调试时，请像上例一样把数据库设在本地磁盘。部署时数据库也应放在服务器本地磁盘，不要放在 SMB 共享目录。

配置项：

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `WEREWOLF_HOST` | `127.0.0.1` | 直接运行时监听地址 |
| `WEREWOLF_PORT` | `8000` | 直接运行时监听端口 |
| `WEREWOLF_DB_PATH` | `./werewolf.sqlite3` | SQLite 数据库文件路径 |
| `WEREWOLF_LOG_LEVEL` | `INFO` | 应用日志级别，如 `DEBUG`、`INFO`、`WARNING` |

直接运行时，请求访问日志和应用日志都输出到终端标准错误。应用日志会记录建局、加入、被拒绝的请求和服务器异常，不记录主持人密钥、玩家令牌或抽到的身份。若使用上述 systemd 服务，可用 `journalctl -u werewolf -f` 查看实时日志。按 `Ctrl+C` 正常停止服务时会输出 `service_stopped`。

玩家和主持人链接使用浏览器当前访问的域名与端口生成。对外使用时请通过实际域名访问首页，并配置 HTTPS；分享链接中的令牌可恢复身份，须当作密码保管。玩家清除浏览器数据后，可通过自己保存的个人链接恢复身份。

## 部署到其他服务器

复制 `app.py`、`static/` 及本项目其他文本文件到服务器，例如 `/opt/werewolf`。创建运行用户和本地数据目录，并确保运行用户可写数据目录。

可直接用 systemd 运行标准库服务器，参考 [`deploy/werewolf.service`](deploy/werewolf.service)。将该文件放到 `/etc/systemd/system/werewolf.service`，按服务器实际路径和用户修改，然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now werewolf
sudo systemctl status werewolf
```

也可使用 Gunicorn 运行同一个 WSGI 应用（Gunicorn 需在目标服务器另行安装）：

```bash
WEREWOLF_DB_PATH=/var/lib/werewolf/werewolf.sqlite3 \
gunicorn --workers 2 --threads 4 --bind 0.0.0.0:8000 app:application
```

Gunicorn 自行设定监听地址和端口，`WEREWOLF_HOST` 与 `WEREWOLF_PORT` 只用于直接执行 `app.py`。生产环境建议在服务前配置 HTTPS 反向代理。SQLite 文件需要备份；复制运行中的数据库时应使用 SQLite 的备份功能或先停止服务。

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 /home/tuke/opencode/wolf_env/bin/python3 -m unittest discover -s tests -v
node --check static/app.js
```

测试覆盖配置校验、身份牌总数与组成、主持人权限、玩家身份读取、重复昵称、满员及同时加入。

## 接口

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/games` | 创建对局；返回对局 ID 和主持人令牌 |
| `GET /api/games/{id}` | 获取公开配置及加入人数 |
| `POST /api/games/{id}/join` | 提交昵称；返回身份与个人令牌 |
| `GET /api/games/{id}/me` | 使用个人 Bearer 令牌查看自己的身份 |
| `GET /api/games/{id}/host` | 使用主持人 Bearer 令牌查看所有玩家身份 |

创建请求示例：

```json
{
  "player_count": 8,
  "wolf_count": 2,
  "villager_count": 3,
  "god_count": 3,
  "god_roles": ["预言家", "女巫", "猎人"],
  "white_wolf_king": false
}
```
