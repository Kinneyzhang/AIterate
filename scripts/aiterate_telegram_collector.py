#!/usr/bin/env python3
"""AIIterate Telegram 收集守护进程。

读取 AIIterate 设置中的 inbox_sources.telegram_sources，轮询 Telegram 来源，
把新消息推送到 AIIterate Inbox。

配置通过环境变量提供，避免把 Telegram API credentials / proxy 密码提交到 Git：
- TELEGRAM_API_ID：Telegram API ID（必填）
- TELEGRAM_API_HASH：Telegram API Hash（必填）
- TELEGRAM_SESSION：Telethon session 路径，默认 ./data/tg_session_summary
- TELEGRAM_PROXY：可选，形如 socks5://user:pass@host:port
- AITERATE_BASE_URL：默认 http://127.0.0.1:7070
- AITERATE_ADMIN_TOKEN：可选；不设置时从 AIIterate DB settings 读取
- AITERATE_COLLECTOR_STATE_DIR：默认 ./data/telegram_collector_state

用法：
  python scripts/aiterate_telegram_collector.py [--once] [--interval 60]
  kill -HUP <pid>  # 重载 Telegram 来源列表
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import socks
from telethon import TelegramClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import aiterate_db  # noqa: E402


# ── Config ──────────────────────────────────────────────────

def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"[collector] Missing required environment variable: {name}")
    return value


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return Path(raw).expanduser()


def _parse_proxy(raw: str | None):
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"socks5", "socks5h"}:
        raise SystemExit(f"[collector] Unsupported TELEGRAM_PROXY scheme: {parsed.scheme}")
    if not parsed.hostname or not parsed.port:
        raise SystemExit("[collector] TELEGRAM_PROXY must include host and port")
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    return (socks.SOCKS5, parsed.hostname, parsed.port, True, username, password)


API_ID = int(_required_env("TELEGRAM_API_ID"))
API_HASH = _required_env("TELEGRAM_API_HASH")
SESSION = str(_env_path("TELEGRAM_SESSION", PROJECT_ROOT / "data" / "tg_session_summary"))
PROXY = _parse_proxy(os.environ.get("TELEGRAM_PROXY"))
AITERATE_BASE_URL = os.environ.get("AITERATE_BASE_URL", "http://127.0.0.1:7070").rstrip("/")
AITERATE_INBOX_URL = f"{AITERATE_BASE_URL}/api/inbox"
AITERATE_SESSIONS_URL = f"{AITERATE_BASE_URL}/api/sessions"
STATE_DIR = _env_path("AITERATE_COLLECTOR_STATE_DIR", PROJECT_ROOT / "data" / "telegram_collector_state")
STATE_DIR.mkdir(parents=True, exist_ok=True)

# ── State ───────────────────────────────────────────────────
reload_flag = False
running = True


def get_admin_token() -> str:
    token = os.environ.get("AITERATE_ADMIN_TOKEN", "").strip()
    if token:
        return token
    return aiterate_db.get_settings().get("admin_token", "")


def get_sources() -> list[dict]:
    settings = aiterate_db.get_settings()
    raw = (settings.get("inbox_sources") or {}).get("telegram_sources") or []
    return [s for s in raw if s.get("source")]


async def resolve_source(client: TelegramClient, source: str, cache: dict):
    """解析 Telegram 来源为 (canonical_key, entity)。

    支持 username / @username / 数字 ID / https://t.me/username / https://t.me/+invite。
    canonical_key 用于状态文件命名，应稳定不变。
    entity 传给 Telethon iter_messages()。
    """
    source = source.strip()
    if source in cache:
        return cache[source]

    if source.lstrip("-").isdigit():
        eid = int(source)
        result = (str(eid), eid)
        cache[source] = result
        return result

    m = re.match(r"https?://t\.me/(.+)", source)
    if m:
        path = m.group(1)
        if path.startswith("+") or path.startswith("joinchat/"):
            try:
                entity = await client.get_entity(source)
                eid = entity.id
                result = (str(eid), eid)
                cache[source] = result
                print(f"[collector] Resolved invite → chat_id={eid}", flush=True)
                return result
            except Exception as e:
                print(f"[collector] Failed to resolve invite {source}: {e}", flush=True)
                result = (source, None)
                cache[source] = result
                return result

        username = path.split("/")[0].split("?")[0]
        result = (username, username)
        cache[source] = result
        return result

    if source.startswith("@"):
        username = source[1:]
        result = (username, username)
        cache[source] = result
        return result

    result = (source, source)
    cache[source] = result
    return result


def state_file(source: str) -> Path:
    safe = (
        str(source)
        .replace("/", "_")
        .replace("@", "")
        .replace("https:", "")
        .replace("-", "m")
    )
    return STATE_DIR / f"{safe}.json"


def load_state(source: str) -> dict:
    sf = state_file(source)
    if sf.exists():
        try:
            return json.loads(sf.read_text())
        except Exception as e:
            print(f"[collector] Failed to read state {sf}: {e}", flush=True)
    return {"last_id": 0, "last_run": None}


def save_state(source: str, state: dict) -> None:
    state_file(source).write_text(json.dumps(state, ensure_ascii=False))


def _post_json(url: str, payload: dict, *, timeout: int = 10) -> bool:
    token = get_admin_token()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "x-admin-token": token},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if 200 <= resp.status < 300:
                return True
            print(f"[collector] AIIterate returned HTTP {resp.status} for {url}", flush=True)
            return False
    except Exception as e:
        print(f"[collector] Failed to post to AIIterate: {type(e).__name__}: {e}", flush=True)
        return False


def is_direct_session_question(text: str) -> bool:
    """Only explicit Chinese/English question-mark endings become sessions."""
    stripped = (text or "").strip()
    return bool(stripped) and stripped[-1] in {"?", "？"}


def format_telegram_content(content: str, source_label: str) -> str:
    body = f"[{source_label}] {content}"
    if len(body) > 5000:
        body = body[:4997] + "..."
    return body


def create_question_session(content: str, source_label: str) -> bool:
    return _post_json(
        AITERATE_SESSIONS_URL,
        {
            "content": content,
            "type": "question",
            "web_search": False,
        },
        timeout=15,
    )


def push_to_inbox(content: str, source_label: str) -> bool:
    return _post_json(
        AITERATE_INBOX_URL,
        {
            "content": content,
            "source_type": f"telegram:{source_label}",
        },
    )


def dispatch_telegram_message(message_text: str, source_label: str) -> str:
    """Route explicit questions to sessions; everything else to inbox."""
    content = format_telegram_content(message_text, source_label)
    if is_direct_session_question(message_text):
        return "session" if create_question_session(content, source_label) else "failed"
    return "inbox" if push_to_inbox(content, source_label) else "failed"


# ── Signal handlers ─────────────────────────────────────────
def on_sighup(signum, frame):
    global reload_flag
    reload_flag = True
    print("[collector] SIGHUP — will reload sources on next poll", flush=True)


def on_sigterm(signum, frame):
    global running
    running = False
    print("[collector] SIGTERM — shutting down", flush=True)


signal.signal(signal.SIGHUP, on_sighup)
signal.signal(signal.SIGTERM, on_sigterm)


# ── Main loop ───────────────────────────────────────────────
async def main(once: bool = False, interval: int = 60):
    global reload_flag, running

    sources = get_sources()
    if not sources:
        print("[collector] No telegram_sources configured — waiting...", flush=True)
        if once:
            return

    client = TelegramClient(SESSION, API_ID, API_HASH, proxy=PROXY)
    await client.start()
    me = await client.get_me()
    print(f"[collector] Connected as @{me.username}", flush=True)

    entity_cache = {}

    if once:
        await fetch_round(client, sources, entity_cache)
        await client.disconnect()
        return

    print(f"[collector] Watching {len(sources)} sources, poll interval {interval}s", flush=True)
    while running:
        if reload_flag:
            sources = get_sources()
            entity_cache.clear()
            reload_flag = False
            print(f"[collector] Reloaded — now watching {len(sources)} sources", flush=True)

        await fetch_round(client, sources, entity_cache)
        for _ in range(max(1, interval)):
            if not running or reload_flag:
                break
            await asyncio.sleep(1)

    await client.disconnect()
    print("[collector] Stopped.", flush=True)


async def fetch_round(client: TelegramClient, sources: list[dict], entity_cache: dict) -> None:
    cst = timezone(timedelta(hours=8))
    for src in sources:
        label = src.get("label", src["source"])
        source = src["source"]

        canonical, entity = await resolve_source(client, source, entity_cache)
        if entity is None:
            print(f"[collector] Skipping {label} (unresolved: {source})", flush=True)
            continue

        state = load_state(canonical)
        last_id = state.get("last_id", 0)
        new_last_id = last_id
        captured = 0

        try:
            async for msg in client.iter_messages(entity, limit=20):
                if msg.id <= last_id:
                    break
                if not msg.text:
                    continue
                if msg.id > new_last_id:
                    new_last_id = msg.id

                route = dispatch_telegram_message(msg.text, label)
                if route != "failed":
                    captured += 1

        except Exception as e:
            print(f"[collector] Error on {label}: {type(e).__name__}: {e}", flush=True)
            continue

        if captured:
            print(f"[collector] {label}: {captured} new routed", flush=True)
            save_state(canonical, {"last_id": new_last_id, "last_run": datetime.now(cst).isoformat()})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIIterate Telegram inbox collector")
    parser.add_argument("--once", action="store_true", help="只拉一轮就退出")
    parser.add_argument("--interval", type=int, default=60, help="轮询间隔秒数，默认 60")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(main(once=args.once, interval=args.interval))
