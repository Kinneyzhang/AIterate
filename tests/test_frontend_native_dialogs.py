"""Frontend dialog regression tests."""

from pathlib import Path
import re


NATIVE_DIALOG_RE = re.compile(r"\b(?:window\.)?(?:alert|confirm|prompt)\s*\(")


def test_vue_frontend_does_not_use_native_browser_dialogs():
    """Business UI must use styled app modals/notices, not browser-native dialogs."""
    root = Path(__file__).resolve().parents[1] / "assets" / "js"
    offenders = []
    for path in sorted(root.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if NATIVE_DIALOG_RE.search(line):
                offenders.append(f"{path.relative_to(root.parent.parent)}:{lineno}: {line.strip()}")
    assert not offenders, "Native browser dialogs found:\n" + "\n".join(offenders)


def test_app_root_mounts_right_side_notice_and_app_dialog():
    """Notices and confirmations must be app-styled surfaces, not inline/native UI."""
    root = Path(__file__).resolve().parents[1]
    app_root = (root / "assets" / "js" / "vue" / "components" / "AppRoot.js").read_text(encoding="utf-8")
    assert "'notice-' + (store.notice.type || 'info')" in app_root
    assert "<AppDialog />" in app_root


def test_inbox_generation_status_uses_side_notice_not_inline_banner():
    """The AI generation progress message should be routed to the right-side notice."""
    root = Path(__file__).resolve().parents[1]
    inbox = (root / "assets" / "js" / "vue" / "components" / "InboxPanel.js").read_text(encoding="utf-8")
    assert "function syncGenerationNotice" in inbox
    assert "setNotice('AI 正在把这条素材加工成候选问题…')" in inbox
    assert "class=\"inbox-generating\"" not in inbox
    assert "<div v-if=\"['pending','generating'].includes(item.status)\"" not in inbox
