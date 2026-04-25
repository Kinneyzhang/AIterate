// ── AppRoot.js ── 根组件 ─────────────────────────────────────────────────

import { defineComponent, watch, computed, ref, onMounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { store, setNotice } from '../store.js?v=027';
import { api } from '../api.js?v=027';
import TopBar from './TopBar.js?v=027';
import SideBar from './SideBar.js?v=027';
import Workspace from './Workspace.js?v=027';
import NewSessionModal from './modals/NewSessionModal.js?v=027';
import SettingsModal from './modals/SettingsModal.js?v=027';
import KnowledgeTreeModal from './modals/KnowledgeTreeModal.js?v=027';
import CommandCenterModal from './modals/CommandCenterModal.js?v=027';
import LoginModal from './modals/LoginModal.js?v=027';

export default defineComponent({
  components: { TopBar, SideBar, Workspace, NewSessionModal, SettingsModal, KnowledgeTreeModal, CommandCenterModal, LoginModal },

  setup() {
    const router = useRouter();
    const route  = useRoute();
    const authenticated = ref(false);
    const checking = ref(true);

    // ── Auth check on mount ─────────────────────────────────────────
    onMounted(async () => {
      try {
        const status = await api.checkAuth();
        authenticated.value = status.authenticated;
      } catch {
        authenticated.value = false;
      } finally {
        checking.value = false;
      }
    });

    // Listen for 401 from api.js
    function onUnauthorized() {
      authenticated.value = false;
    }
    document.addEventListener('aiterate:unauthorized', onUnauthorized);

    // ── overlay 页面判断 ───────────────────────────────────────────
    const isOverlay = computed(() => ['new-session', 'knowledge-tree', 'command-center', 'settings-basic', 'settings-roles', 'settings-tavily', 'settings-database', 'settings-learn'].includes(route.name));

    // ── 路由变化 → 加载 session 数据 ────────────────────────────────
    watch(
      () => route.params.id,
      async (id, oldId) => {
        if (!id) {
          if (!isOverlay.value) {
            store.selectedSessionId = null;
            store.workspace = null;
            stopPolling();
          }
          return;
        }
        const numId = Number(id);
        if (numId === store.selectedSessionId && store.workspace) return;
        store.selectedSessionId = numId;
        store.workspace = null;
        setNotice('');
        store.sidebarExpanded = false;
        try {
          store.workspace = await api.getWorkspace(numId);
          const g = store.workspace?.current_review_group;
          store.currentFeynmanGroupId = (g?.length > 0) ? (g[0].group_id ?? g[0].id) : null;
          if (store.workspace?.session?.status === 'preparing') startPolling(numId);
          else stopPolling();
        } catch (err) {
          setNotice(`加载失败：${err.message}`, 'error');
        }
      },
      { immediate: true }
    );

    // ── Polling ──────────────────────────────────────────────────────
    function startPolling(sessionId) {
      stopPolling();
      store.pollTimer = setInterval(async () => {
        if (store.selectedSessionId !== sessionId) { stopPolling(); return; }
        try {
          store.workspace = await api.getWorkspace(sessionId);
          store.sessions  = await api.getSessions();
          if (store.workspace?.session?.status !== 'preparing') stopPolling();
        } catch (err) {
          console.error('poll failed', err);
        }
      }, 3000);
    }

    function stopPolling() {
      if (store.pollTimer) { clearInterval(store.pollTimer); store.pollTimer = null; }
    }

    // ── 刷新 ─────────────────────────────────────────────────────────
    async function refreshAll(showNotice) {
      store.sessions = await api.getSessions();
      if (store.selectedSessionId) {
        store.workspace = await api.getWorkspace(store.selectedSessionId);
        const g = store.workspace?.current_review_group;
        store.currentFeynmanGroupId = (g?.length > 0) ? (g[0].group_id ?? g[0].id) : null;
      }
      if (showNotice) setNotice('已刷新。');
    }

    // ── 选 session ─────────────────────────────────────────────────
    function selectSession(id) {
      const numId = Number(id);
      if (numId === store.selectedSessionId && store.workspace) return;
      router.push({ name: 'session-learn', params: { id } });
    }

    // ── 关闭 overlay ────────────────────────────────────────────────
    function closeOverlay() {
      if (window.history.length > 1) {
        router.back();
      } else if (store.selectedSessionId) {
        router.push({ name: 'session-learn', params: { id: store.selectedSessionId } });
      } else {
        router.push({ name: 'home' });
      }
    }

    async function closeOverlayAndRefresh() {
      await refreshAll(false);
      closeOverlay();
    }

    return { store, route, router, refreshAll, selectSession, closeOverlay, closeOverlayAndRefresh, isOverlay,
      authenticated, checking };
  },

  mounted() {
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

      resizer.addEventListener('mousedown', e => {
        e.preventDefault();
        const startX = e.clientX;
        const startW = document.getElementById('sessionSidebar').getBoundingClientRect().width;
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
          const w = document.getElementById('sessionSidebar').getBoundingClientRect().width;
          localStorage.setItem('sidebar-width', Math.round(w));
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
      <LoginModal v-else @authenticated="authenticated = true" />
    </template>

    <!-- ── Authenticated app ────────────────────────────────────────────── -->
    <template v-else>
    <!-- ── topbar ──────────────────────────────────────────────────────── -->
    <TopBar @toggle-sidebar="toggleSidebar" @refresh="refreshAll(true)" />

    <!-- ── sidebar overlay (mobile) ────────────────────────────────────── -->
    <div class="sidebar-overlay"
         :class="{ active: store.sidebarExpanded }"
         id="sidebarOverlay"
         @click="toggleSidebar"></div>

    <!-- ── main layout ──────────────────────────────────────────────────── -->
    <div class="workspace-shell">
      <SideBar :sessions="store.sessions"
               :selected-id="store.selectedSessionId"
               :expanded="store.sidebarExpanded"
               @select="selectSession" />
      <main class="main-pane">
        <div id="noticeBar"
             :class="['notice-bar', store.notice.text ? 'visible' : '', store.notice.type === 'error' ? 'notice-error' : '']">
          {{ store.notice.text }}
        </div>
        <Workspace @refresh="refreshAll(false)" />
      </main>
    </div>

    <!-- ── overlay 页面（独立功能，路由控制） ───────────────────────── -->
    <NewSessionModal
      v-if="route.name === 'new-session'"
      @close="closeOverlay"
      @created="closeOverlayAndRefresh" />

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
    </template>
  `,
});
