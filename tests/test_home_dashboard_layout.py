from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT_JS = ROOT / "assets/js/vue/components/AppRoot.js"
HOME_DASHBOARD_JS = ROOT / "assets/js/vue/components/HomeDashboard.js"
HOME_RAIL_JS = ROOT / "assets/js/vue/components/HomeRail.js"
APP_CSS = ROOT / "assets/app.css"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_home_dashboard_has_right_rail_in_shell_third_column():
    app = _text(APP_ROOT_JS)
    rail = _text(HOME_RAIL_JS)
    css = _text(APP_CSS)

    assert "import HomeRail from './HomeRail.js'" in app
    assert "HomeRail" in app
    assert '<HomeRail v-if="backgroundIsHomeRoute"' in app
    assert 'class="home-rail"' in rail
    assert '今日概览' in rail and '下一步' in rail and '推进原则' in rail
    assert '快捷动作' not in rail and 'openNewSession' not in rail
    assert '.home-rail {' in css
    assert 'border-left: 1px solid var(--border' in css
    assert 'background: var(--bg-sidebar' in css
    assert '@media (max-width: 1100px)' in css and '.home-rail { display: none; }' in css


def test_home_dashboard_surfaces_learning_assets_as_clear_visible_entry_point():
    src = _text(HOME_DASHBOARD_JS)
    assert 'activeContext' in src
    assert 'api.getLearningBrief' in src
    assert 'api.getEntries' in src
    assert 'api.getThreads' in src
    assert 'api.getLearningAgents' in src
    assert 'home-active-context' in src
    assert '学习资产' in src
    assert '今日该看什么' in src
    assert '素材' in src and '主题' in src and '协作者' in src
    assert '回顾我对 X 的理解' in src
    assert '主动学习上下文' not in src
    assert '今日主动简报' not in src
    assert '我怎么看 X' not in src


def test_home_dashboard_focus_items_have_real_navigation_targets():
    src = _text(HOME_DASHBOARD_JS)
    assert "item?.target?.type === 'inbox_item'" in src
    assert "name: 'inbox-item'" in src
    assert 'setNotice' in src and '还没有可打开的页面' in src


def test_overlay_keeps_previous_background_route():
    app = _text(APP_ROOT_JS)

    assert 'backgroundRouteName = computed' in app
    assert "if (!isOverlay.value) return route.name" in app
    assert "lastNonOverlayRoute.value?.name || 'home'" in app
    assert 'backgroundIsHomeRoute' in app and 'backgroundIsInboxRoute' in app
    assert '<HomeDashboard v-else-if="backgroundIsHomeRoute"' in app
    assert '<Workspace v-else @refresh="refreshAll(false)"' in app
    assert '<InboxPanel v-if="backgroundIsInboxRoute"' in app
