from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT_JS = ROOT / "assets/js/vue/components/AppRoot.js"
WORKSPACE_JS = ROOT / "assets/js/vue/components/Workspace.js"
CONTEXT_RAIL_JS = ROOT / "assets/js/vue/components/ContextRail.js"
APP_CSS = ROOT / "assets/app.css"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_context_rail_is_top_level_shell_column_not_inside_workspace_panel():
    app = _text(APP_ROOT_JS)
    workspace = _text(WORKSPACE_JS)
    assert "import ContextRail from './ContextRail.js'" in app
    assert "components: { TopBar, SideBar, Workspace, ContextRail" in app
    assert '<ContextRail' in app
    assert '@refresh="refreshAll(false)"' in app
    assert 'class="context-rail"' not in workspace
    assert 'class="workspace-body"' not in workspace


def test_context_rail_component_has_expected_cards_and_reuses_workspace_state():
    src = _text(CONTEXT_RAIL_JS)
    assert 'class="context-rail"' in src
    assert 'context-card context-stage-card' in src
    assert 'context-card context-gaps-card' in src
    assert 'context-card context-actions-card' in src
    assert 'context-card context-nav-card' in src
    assert 'contextScore' in src
    assert 'unresolvedGaps.slice(0, 5)' in src
    assert "switchTab('deepen')" in src
    assert "switchTab('review')" in src
    assert 'fillGapAsQuestion' in src
    assert 'class="context-gap-text"' in src


def test_context_rail_css_is_third_shell_column_and_mobile_fallback():
    css = _text(APP_CSS)
    assert 'grid-template-columns: var(--sidebar-width, 260px) minmax(0, 1fr) 300px;' in css
    assert '.context-rail {' in css
    assert '.context-card {' in css
    assert 'background: var(--bg-sidebar' in css
    assert '@media (max-width: 1100px)' in css
    assert 'grid-template-columns: var(--sidebar-width, 260px) minmax(0, 1fr);' in css
    assert '.context-rail { display: none;' in css


def test_learning_page_keeps_write_first_input_available_while_ai_answer_generates():
    src = _text(WORKSPACE_JS)
    assert "['preparing', 'learning'].includes(currentSession.value?.status)" in src
    assert "AI 回答生成中，可先写" in src
    assert ":disabled=\"submitting || currentSession.status === 'preparing'\"" in src
    assert src.index("write-first-section") < src.index("currentSession.material")


def test_context_gap_long_text_wraps_and_rail_uses_continuous_sidebar_style():
    css = _text(APP_CSS)
    assert '.context-card-title {' in css
    assert 'font-family: var(--font-sans' in css
    assert 'background: transparent;' in css
    assert 'border: 0;' in css
    assert 'border-radius: 0;' in css
    assert '.context-card + .context-card {' in css
    assert 'border-top: 1px solid var(--border' in css
    assert '.context-gap-item {' in css
    assert 'white-space: normal;' in css
    assert '.context-gap-text {' in css
    assert 'overflow-wrap: anywhere;' in css
    assert 'word-break: break-word;' in css
