// ── AppRoot.js ── 根组件 ─────────────────────────────────────────────────

import { defineComponent, watch, computed, ref, onMounted, onUnmounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { store, setNotice, askConfirm } from '../store.js';
import { api } from '../api.js';
import TopBar from './TopBar.js';
import SideBar from './SideBar.js';
import Workspace from './Workspace.js';
import HomeDashboard from './HomeDashboard.js';
import HomeRail from './HomeRail.js';
import ContextRail from './ContextRail.js';
import InboxPanel from './InboxPanel.js';
import NewSessionModal from './modals/NewSessionModal.js';
import SettingsModal from './modals/SettingsModal.js';
import KnowledgeTreeModal from './modals/KnowledgeTreeModal.js';
import CommandCenterModal from './modals/CommandCenterModal.js';
import SessionShareModal from './modals/SessionShareModal.js';
import LoginModal from './modals/LoginModal.js';
import AppDialog from './AppDialog.js';

export default defineComponent({
  components: { TopBar, SideBar, Workspace, ContextRail, HomeDashboard, HomeRail, InboxPanel, NewSessionModal, SettingsModal, KnowledgeTreeModal, CommandCenterModal, SessionShareModal, LoginModal, AppDialog },

  setup() {
    const router = useRouter();
    const route  = useRoute();
    const authenticated = ref(false);
    const checking = ref(true);
    const shareSessionId = ref(null);

    // ── overlay 页面判断 ───────────────────────────────────────────
    const OVERLAY_ROUTES = ['new-session', 'knowledge-tree', 'command-center', 'settings-basic', 'settings-roles', 'settings-tavily', 'settings-database', 'settings-learn'];
    const isOverlayRouteName = name => OVERLAY_ROUTES.includes(name);
    const isOverlay = computed(() => isOverlayRouteName(route.name));
    const lastNonOverlayRoute = ref(null);
    let pollBusy = false;
    let workspaceLoadSeq = 0;
    const pendingSessionOps = new Map();

    function routeNameForStatus(status) {
      if (status === 'feynman' || status === 'completed') return 'session-review';
      if (status === 'deepening' || status === 'revising') return 'session-deepen';
      return 'session-learn';
    }

    const isInboxRoute = computed(() => route.name === 'inbox' || route.name === 'inbox-item');
    const isHomeRoute = computed(() => route.name === 'home');
    const backgroundRouteName = computed(() => {
      if (!isOverlay.value) return route.name;
      return lastNonOverlayRoute.value?.name || 'home';
    });
    const backgroundIsInboxRoute = computed(() => backgroundRouteName.value === 'inbox' || backgroundRouteName.value === 'inbox-item');
    const backgroundIsHomeRoute = computed(() => backgroundRouteName.value === 'home');

    function updateCurrentFeynmanGroup() {
      const g = store.workspace?.current_review_group;
      store.currentFeynmanGroupId = (g?.length > 0) ? (g[0].group_id ?? g[0].id) : null;
    }

    function hasPreparingSessions() {
      return (store.sessions || []).some(s => s.status === 'preparing');
    }

    function warmCaches(sessions) {
      const ids = (sessions || []).map(s => s.id);
      api.prefetchWorkspaces(ids, 24);
      api.prefetchCommandCenter();
      api.prefetchKnowledgeMastery();
    }

    async function loadSessionsAfterAuth() {
      try {
        const [sessions, stats, inboxItems] = await Promise.all([api.getSessions(), api.getStats().catch(() => null), api.getInboxItems(200).catch(() => [])]);
        if (stats) store.stats = stats;
        store.inboxItems = inboxItems || [];
        setSessionsFromServer(sessions);
        if (hasPreparingSessions()) startBackgroundRefresh();
      } catch (err) {
        console.error('Failed to load sessions', err);
        setNotice(`加载会话失败：${err.message}`, 'error');
      }
    }

    // ── Auth check on mount ─────────────────────────────────────────
    onMounted(async () => {
      try {
        const status = await api.checkAuth();
        authenticated.value = status.authenticated;
        if (status.authenticated) await loadSessionsAfterAuth();
      } catch {
        authenticated.value = false;
      } finally {
        checking.value = false;
      }
    });

    // Listen for 401 from api.js
    function onUnauthorized() {
      authenticated.value = false;
      store.sessions = [];
      store.stats = { total_sessions: 0, completed_sessions: 0, active_sessions: 0 };
      store.inboxItems = [];
      store.workspace = null;
      store.selectedSessionId = null;
      store.currentFeynmanGroupId = null;
      stopPolling();
    }
    document.addEventListener('aiterate:unauthorized', onUnauthorized);
    onUnmounted(() => {
      document.removeEventListener('aiterate:unauthorized', onUnauthorized);
      stopPolling();
    });

    watch(
      () => route.fullPath,
      () => {
        if (route.name && !isOverlayRouteName(route.name)) {
          lastNonOverlayRoute.value = {
            name: route.name,
            params: { ...route.params },
            query: { ...route.query },
            hash: route.hash,
          };
        }
      },
      { immediate: true }
    );

    // ── 路由变化 → 加载 session 数据 ────────────────────────────────
    watch(
      () => [route.name, route.params.id],
      async ([name, id], oldVal) => {
        const isSessionRoute = ['session-learn', 'session-deepen', 'session-review'].includes(name);
        if (!isSessionRoute) {
          if (!isOverlay.value) {
            workspaceLoadSeq++;
            store.selectedSessionId = null;
            store.workspace = null;
            store.currentFeynmanGroupId = null;
          }
          return;
        }
        if (!id) {
          if (!isOverlay.value) {
            workspaceLoadSeq++;
            store.selectedSessionId = null;
            store.workspace = null;
            stopPolling();
          }
          return;
        }
        const numId = Number(id);
        if (numId === store.selectedSessionId && store.workspace) return;
        const seq = ++workspaceLoadSeq;
        setNotice('');
        store.sidebarExpanded = false;
        try {
          const workspace = await api.getWorkspace(numId);
          if (seq !== workspaceLoadSeq) return;
          store.selectedSessionId = numId;
          store.workspace = workspace;
          updateCurrentFeynmanGroup();
          if (store.workspace?.session?.status === 'preparing' || hasPreparingSessions()) startBackgroundRefresh();
          else stopPolling();
        } catch (err) {
          setNotice(`加载失败：${err.message}`, 'error');
        }
      },
      { immediate: true }
    );

    // ── Background auto-refresh ───────────────────────────────────────
    async function refreshRuntime() {
      const [sessions, stats, inboxItems] = await Promise.all([api.getSessions(), api.getStats().catch(() => null), api.getInboxItems(200).catch(() => [])]);
      api.getCommandCenter({ force: true }).catch(() => null);
      if (stats) store.stats = stats;
      store.inboxItems = inboxItems || [];
      setSessionsFromServer(sessions);
      if (store.selectedSessionId) {
        store.workspace = await api.getWorkspace(store.selectedSessionId, { force: true });
        const pending = pendingSessionOps.get(Number(store.selectedSessionId));
        if (pending?.patch && store.workspace?.session) {
          store.workspace.session = { ...store.workspace.session, ...pending.patch };
        }
        updateCurrentFeynmanGroup();
      }
      store.runtimeTick += 1;
    }

    async function pollBackgroundOnce() {
      if (pollBusy) return;
      pollBusy = true;
      try {
        const jobs = await api.getJobsStatus().catch(() => ({ pending: 0, running: 0 }));
        await refreshRuntime();
        const keepPolling = (jobs.pending || 0) > 0 || (jobs.running || 0) > 0 || hasPreparingSessions();
        if (!keepPolling) stopPolling();
      } catch (err) {
        console.error('background refresh failed', err);
      } finally {
        pollBusy = false;
      }
    }

    function startBackgroundRefresh() {
      if (!store.pollTimer) {
        store.pollTimer = setInterval(pollBackgroundOnce, 2000);
      }
      pollBackgroundOnce();
    }

    function stopPolling() {
      if (store.pollTimer) { clearInterval(store.pollTimer); store.pollTimer = null; }
    }

    // ── 刷新 ─────────────────────────────────────────────────────────
    async function refreshAll(showNotice) {
      await refreshRuntime();
      if (hasPreparingSessions()) startBackgroundRefresh();
      if (showNotice) setNotice('已刷新。');
    }

    // ── 选 session ─────────────────────────────────────────────────
    function selectSession(id) {
      const numId = Number(id);
      if (numId === store.selectedSessionId && store.workspace) return;
      const session = (store.sessions || []).find(s => Number(s.id) === numId);
      router.push({ name: routeNameForStatus(session?.status), params: { id } });
    }

    // ── 关闭 overlay ────────────────────────────────────────────────
    function closeOverlay() {
      const target = lastNonOverlayRoute.value;
      if (target?.name && !isOverlayRouteName(target.name)) {
        router.push(target);
      } else if (store.selectedSessionId) {
        router.push({ name: 'session-learn', params: { id: store.selectedSessionId } });
      } else {
        router.push({ name: 'home' });
      }
    }

    async function closeOverlayAndRefresh() {
      try {
        await refreshAll(false);
      } finally {
        closeOverlay();
      }
    }

    async function handleSessionCreated(payload) {
      try {
        const [sessions, stats, inboxItems] = await Promise.all([api.getSessions(), api.getStats().catch(() => null), api.getInboxItems(200).catch(() => [])]);
        if (stats) store.stats = stats;
        store.inboxItems = inboxItems || [];
        setSessionsFromServer(sessions);
        // 只刷新侧栏与统计，不切换当前 selectedSession/workspace。
        // 新建 modal 是 overlay；提交后背景应继续停留在用户原来的 session/panel。
        startBackgroundRefresh();
      } catch (err) {
        console.error('created session refresh failed', err);
        setNotice(`已提交，但刷新列表失败：${err.message}`, 'error');
      }
    }

    function applyPendingSessionOps(sessions) {
      return (sessions || []).reduce((acc, session) => {
        const op = pendingSessionOps.get(Number(session.id));
        if (op?.type === 'delete') return acc;
        acc.push(op?.patch ? { ...session, ...op.patch } : session);
        return acc;
      }, []);
    }

    function setSessionsFromServer(sessions) {
      store.sessions = applyPendingSessionOps(sessions);
      syncStatsFromSessions();
      warmCaches(store.sessions);
    }

    function syncStatsFromSessions() {
      const sessions = store.sessions || [];
      const completed = sessions.filter(s => s.status === 'completed').length;
      store.stats = {
        ...(store.stats || {}),
        total_sessions: sessions.length,
        completed_sessions: completed,
        active_sessions: sessions.length - completed,
      };
    }

    function removeSessionLocal(id) {
      const sid = Number(id);
      const nextSessions = (store.sessions || []).filter(s => Number(s.id) !== sid);
      store.sessions.splice(0, store.sessions.length, ...nextSessions);
      syncStatsFromSessions();
    }

    function replaceSessionLocal(id, patchOrSession) {
      const sid = Number(id);
      store.sessions = (store.sessions || []).map(s => Number(s.id) === sid ? { ...s, ...patchOrSession } : s);
      if (Number(store.selectedSessionId) === sid && store.workspace?.session) {
        store.workspace.session = { ...store.workspace.session, ...patchOrSession };
      }
    }

    async function handleShareSession(session) {
      store.sidebarExpanded = false;
      shareSessionId.value = Number(session.id);
    }

    function handleRenameSession(payload) {
      const session = payload.session;
      const title = payload.title.trim();
      const previousTitle = payload.previousTitle ?? session.title ?? '';
      if (!title) {
        setNotice('标题不能为空。', 'error');
        return;
      }

      pendingSessionOps.set(Number(session.id), { type: 'rename', patch: { title } });
      replaceSessionLocal(session.id, { title });
      api.renameSession(session.id, title)
        .then(result => {
          pendingSessionOps.delete(Number(session.id));
          if (result?.session) replaceSessionLocal(session.id, result.session);
        })
        .catch(err => {
          pendingSessionOps.delete(Number(session.id));
          replaceSessionLocal(session.id, { title: previousTitle });
          setNotice(`重命名失败：${err.message}`, 'error');
        });
    }

    function handlePinSession(session) {
      const sid = Number(session.id);
      const previousPinnedAt = session.pinned_at || null;
      const previousUpdatedAt = session.updated_at || null;
      const nextPinned = !previousPinnedAt;
      const optimisticPinnedAt = nextPinned ? new Date().toISOString() : null;
      const optimisticPatch = { pinned_at: optimisticPinnedAt, updated_at: previousUpdatedAt };

      pendingSessionOps.set(sid, { type: 'pin', patch: optimisticPatch });
      replaceSessionLocal(sid, optimisticPatch);
      api.pinSession(sid, nextPinned)
        .then(result => {
          pendingSessionOps.delete(sid);
          if (result?.session) replaceSessionLocal(sid, result.session);
        })
        .catch(err => {
          pendingSessionOps.delete(sid);
          replaceSessionLocal(sid, { pinned_at: previousPinnedAt, updated_at: previousUpdatedAt });
          setNotice(`${nextPinned ? '置顶' : '取消置顶'}失败：${err.message}`, 'error');
        });
    }

    async function handleDeleteSession(session) {
      const ok = await askConfirm({
        title: '删除学习会话',
        message: `删除「${session.title || '未命名'}」？`,
        details: '会同时删除这个 session 的学习、深化和费曼记录。',
        confirmText: '删除',
        cancelText: '取消',
        tone: 'danger',
      });
      if (!ok) return;

      const sid = Number(session.id);
      const previousSessions = [...(store.sessions || [])];
      const previousStats = { ...(store.stats || {}) };
      const wasSelected = Number(store.selectedSessionId) === sid;
      const previousWorkspace = wasSelected ? store.workspace : null;

      pendingSessionOps.set(sid, { type: 'delete' });
      removeSessionLocal(sid);
      if (wasSelected) {
        workspaceLoadSeq++;
        store.selectedSessionId = null;
        store.workspace = null;
        store.currentFeynmanGroupId = null;
        router.push({ name: 'home' });
      }

      api.deleteSession(sid)
        .then(() => {
          pendingSessionOps.delete(sid);
          removeSessionLocal(sid);
        })
        .catch(err => {
          pendingSessionOps.delete(sid);
          store.sessions = previousSessions;
          store.stats = previousStats;
          if (wasSelected) {
            store.selectedSessionId = sid;
            store.workspace = previousWorkspace;
            updateCurrentFeynmanGroup();
            router.push({ name: routeNameForStatus(previousWorkspace?.session?.status), params: { id: sid } });
          }
          setNotice(`删除失败：${err.message}`, 'error');
        });
    }

    async function handleAuthenticated() {
      authenticated.value = true;
      await loadSessionsAfterAuth();
    }

    return { store, route, router, refreshAll, selectSession, closeOverlay, closeOverlayAndRefresh, handleSessionCreated,
      handleShareSession, handleRenameSession, handlePinSession, handleDeleteSession, shareSessionId, isOverlay, isInboxRoute, isHomeRoute,
      backgroundIsInboxRoute, backgroundIsHomeRoute,
      authenticated, checking, handleAuthenticated };
  },

  mounted() {
    this.initSidebarResize();
  },

  updated() {
    this.initSidebarResize();
  },

  methods: {
    initSidebarResize() {
      const resizer = document.getElementById('sidebarResizer');
      const shell   = document.querySelector('.workspace-shell');
      if (!resizer || !shell) return;

      const MIN = 180, MAX = 520;
      const saved = localStorage.getItem('sidebar-width');
      if (saved) shell.style.setProperty('--sidebar-width', saved + 'px');
      if (resizer.dataset.resizeBound === '1') return;
      resizer.dataset.resizeBound = '1';

      resizer.addEventListener('mousedown', e => {
        e.preventDefault();
        const sidebar = document.getElementById('sessionSidebar');
        if (!sidebar) return;
        const startX = e.clientX;
        const startW = sidebar.getBoundingClientRect().width;
        resizer.classList.add('dragging');
        document.body.style.cursor     = 'col-resize';
        document.body.style.userSelect = 'none';

        const onMove = e => {
          const w = Math.min(MAX, Math.max(MIN, startW + e.clientX - startX));
          shell.style.setProperty('--sidebar-width', w + 'px');
        };
        const onUp = () => {
          resizer.classList.remove('dragging');
          document.body.style.cursor     = '';
          document.body.style.userSelect = '';
          const currentSidebar = document.getElementById('sessionSidebar');
          if (currentSidebar) {
            const w = currentSidebar.getBoundingClientRect().width;
            localStorage.setItem('sidebar-width', Math.round(w));
          }
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup',  onUp);
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup',  onUp);
      });
    },

    toggleSidebar() {
      store.sidebarExpanded = !store.sidebarExpanded;
    },
  },

  template: `
    <!-- ── Loading / Login ─────────────────────────────────────────────── -->
    <template v-if="!authenticated">
      <div v-if="checking" class="login-overlay" style="display:flex;align-items:center;justify-content:center">
        <div style="opacity:0.4;font-size:15px">加载中…</div>
      </div>
      <LoginModal v-else @authenticated="handleAuthenticated" />
    </template>

    <!-- ── Authenticated app ────────────────────────────────────────────── -->
    <template v-else>
    <!-- ── topbar ──────────────────────────────────────────────────────── -->
    <TopBar @toggle-sidebar="toggleSidebar" />

    <div id="noticeBar"
         :class="['notice-bar', store.notice.text ? 'visible' : '', 'notice-' + (store.notice.type || 'info')]">
      {{ store.notice.text }}
    </div>

    <!-- ── sidebar overlay (mobile) ────────────────────────────────────── -->
    <div class="sidebar-overlay"
         :class="{ active: store.sidebarExpanded }"
         id="sidebarOverlay"
         @click="toggleSidebar"></div>

    <!-- ── main layout ──────────────────────────────────────────────────── -->
    <div :class="['workspace-shell', { 'inbox-mode': backgroundIsInboxRoute }]">
      <SideBar :sessions="store.sessions"
               :selected-id="store.selectedSessionId"
               :expanded="store.sidebarExpanded"
               @select="selectSession"
               @share="handleShareSession"
               @rename="handleRenameSession"
               @pin="handlePinSession"
               @delete="handleDeleteSession" />
      <main class="main-pane">
        <InboxPanel v-if="backgroundIsInboxRoute" @refresh="refreshAll(false)" />
        <HomeDashboard v-else-if="backgroundIsHomeRoute" />
        <Workspace v-else @refresh="refreshAll(false)" />
      </main>
      <HomeRail v-if="backgroundIsHomeRoute" />
      <ContextRail v-else-if="!backgroundIsInboxRoute" @refresh="refreshAll(false)" />
    </div>

    <!-- ── overlay 页面（独立功能，路由控制） ───────────────────────── -->
    <NewSessionModal
      v-if="route.name === 'new-session'"
      @close="closeOverlay"
      @created="handleSessionCreated" />

    <SettingsModal
      v-if="['settings-basic','settings-roles','settings-tavily','settings-database','settings-learn'].includes(route.name)"
      @close="closeOverlay" />

    <KnowledgeTreeModal
      v-if="route.name === 'knowledge-tree'"
      @close="closeOverlay" />

    <CommandCenterModal
      v-if="route.name === 'command-center'"
      @close="closeOverlay"
      @select-session="id => { router.push({ name: 'session-learn', params: { id } }); }" />

    <SessionShareModal
      v-if="shareSessionId"
      :session-id="shareSessionId"
      @close="shareSessionId = null" />

    <AppDialog />
    </template>
  `,
});
