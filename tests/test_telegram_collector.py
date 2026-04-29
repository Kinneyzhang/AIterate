"""Telegram collector routing tests."""

import importlib.util
import sys
from pathlib import Path


def load_collector(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_API_ID", "123456")
    monkeypatch.setenv("TELEGRAM_API_HASH", "test_hash")
    monkeypatch.setenv("TELEGRAM_SESSION", str(tmp_path / "tg_session"))
    monkeypatch.setenv("AITERATE_COLLECTOR_STATE_DIR", str(tmp_path / "state"))
    module_path = Path(__file__).parent.parent / "scripts" / "aiterate_telegram_collector.py"
    module_name = f"aiterate_telegram_collector_test_{tmp_path.name}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_explicit_question_detection_requires_question_mark_at_end(tmp_path, monkeypatch):
    collector = load_collector(monkeypatch, tmp_path)

    assert collector.is_direct_session_question("Redis 是什么？") is True
    assert collector.is_direct_session_question("What is Redis?") is True
    assert collector.is_direct_session_question("What is Redis?   ") is True
    assert collector.is_direct_session_question("Redis 是什么") is False
    assert collector.is_direct_session_question("What is Redis?!") is False
    assert collector.is_direct_session_question("看这个链接 https://example.com/?a=1") is False


def test_dispatch_routes_questions_to_sessions_and_non_questions_to_inbox(tmp_path, monkeypatch):
    collector = load_collector(monkeypatch, tmp_path)
    created = []
    inboxed = []

    monkeypatch.setattr(collector, "create_question_session", lambda content, label: created.append((content, label)) or True)
    monkeypatch.setattr(collector, "push_to_inbox", lambda content, label: inboxed.append((content, label)) or True)

    assert collector.dispatch_telegram_message("Redis 是什么？", "Emacs轻聊") == "session"
    assert created and "Redis 是什么？" in created[0][0]
    assert created[0][1] == "Emacs轻聊"
    assert inboxed == []

    assert collector.dispatch_telegram_message("Redis 很快", "Emacs轻聊") == "inbox"
    assert inboxed and "Redis 很快" in inboxed[0][0]
