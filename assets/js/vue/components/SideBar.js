// ── SideBar.js ── 精确复刻原版 sidebar ───────────────────────────────────

import { defineComponent, computed, ref, nextTick, onMounted, onUnmounted } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { store, getStageMeta, formatDate } from '../store.js';
import { api } from '../api.js';
import { icon } from '../icons.js';
import InboxComposer from './InboxComposer.js';

export default defineComponent({
  components: { InboxComposer },
  props: { sessions: Array, selectedId: Number, expanded: Boolean },
  emits: ['select', 'share', 'rename', 'pin', 'delete'],

  setup(props, { emit }) {
    const router = useRouter();
    const route = useRoute();
    const stats = computed(() => {
      // 全局 stats 由 AppRoot 的自动刷新维护；fallback 到当前列表统计
      if (store.stats?.total_sessions > 0) {
        return {
          total: store.stats.total_sessions,
          active: store.stats.total_sessions - (store.stats.completed_sessions || 0),
          completed: store.stats.completed_sessions || 0,
        };
      }
      const s = props.sessions || [];
      const completed = s.filter(x => x.status === 'completed').length;
      const active = s.filter(x => ['preparing','learning','deepening','revising','feynman'].includes(x.status)).length;
      return { total: s.length, active, completed };
    });

    const inboxPendingCount = computed(() => {
      return (store.inboxItems || []).filter(x => ['pending', 'generating', 'ready', 'error'].includes(x.status)).length;
    });

    const sortedSessions = computed(() => {
      return [...(props.sessions || [])].sort((a, b) => {
        if (!!a.pinned_at !== !!b.pinned_at) return a.pinned_at ? -1 : 1;
        if (a.pinned_at && b.pinned_at) return String(b.pinned_at).localeCompare(String(a.pinned_at));
        const da = a.updated_at || a.created_at || '';
        const db = b.updated_at || b.created_at || '';
        return db.localeCompare(da);
      });
    });

    const menu = ref({ open: false, x: 0, y: 0, session: null });
    const menuStyle = computed(() => ({ left: `${menu.value.x}px`, top: `${menu.value.y}px` }));
    const editingId = ref(null);
    const editingTitle = ref('');

    function closeMenu() {
      menu.value = { open: false, x: 0, y: 0, session: null };
    }

    function openMenu(s, event) {
      event.preventDefault();
      event.stopPropagation();
      const vw = window.innerWidth || 320;
      const vh = window.innerHeight || 480;
      const width = 148;
      const height = 220;
      const x = Math.min(event.clientX, vw - width - 8);
      const y = Math.min(event.clientY, vh - height - 8);
      menu.value = { open: true, x: Math.max(8, x), y: Math.max(8, y), session: s };
    }

    async function startEditing(s) {
      closeMenu();
      editingId.value = Number(s.id);
      editingTitle.value = s.title || '';
      await nextTick();
      const input = document.querySelector(`.session-rename-input[data-sid="${s.id}"]`);
      if (input) {
        input.focus();
        input.select();
      }
    }

    function cancelEditing() {
      editingId.value = null;
      editingTitle.value = '';
    }

    function commitEditing(s) {
      if (Number(editingId.value) !== Number(s.id)) return;
      const next = editingTitle.value.trim();
      const previous = s.title || '';
      cancelEditing();
      if (next === previous) return;
      emit('rename', { session: s, title: next, previousTitle: previous });
    }

    function runAction(action) {
      const s = menu.value.session;
      if (!s) return;
      if (action === 'rename') {
        startEditing(s);
        return;
      }
      closeMenu();
      emit(action, s);
    }

    function onSelect(id) {
      if (editingId.value) return;
      emit('select', id);
    }

    function prefetch(id) {
      api.prefetchWorkspace(id);
    }

    function goHome() {
      store.sidebarExpanded = false;
      router.push({ name: 'home' });
    }

    function openNewSession() {
      store.sidebarExpanded = false;
      router.push({ name: 'new-session' });
    }

    function goInbox() {
      store.sidebarExpanded = false;
      router.push({ name: 'inbox' });
    }

    function onDocumentKeydown(event) {
      if (event.key === 'Escape') {
        closeMenu();
        cancelEditing();
      }
    }

    onMounted(() => {
      document.addEventListener('click', closeMenu);
      document.addEventListener('keydown', onDocumentKeydown);
    });
    onUnmounted(() => {
      document.removeEventListener('click', closeMenu);
      document.removeEventListener('keydown', onDocumentKeydown);
    });

    return {
      stats, inboxPendingCount, sortedSessions, menu, menuStyle, editingId, editingTitle,
      onSelect, openMenu, closeMenu, runAction, prefetch, goHome, openNewSession, goInbox,
      getStageMeta, formatDate, icon, route,
      commitEditing, cancelEditing,
    };
  },

  template: `
    <aside :class="['sidebar', { expanded }]" id="sessionSidebar">
      <div class="sidebar-quick-actions" aria-label="快捷入口">
        <button type="button"
                :class="['sidebar-quick-btn', { active: route.name === 'home' }]"
                title="推进"
                @click="goHome">
          <span v-html="icon('target')"></span><span>推进</span>
          <em v-if="stats.active > 0">{{ stats.active }}</em>
        </button>
        <button type="button"
                :class="['sidebar-quick-btn', { active: route.name === 'inbox' || route.name === 'inbox-item' }]"
                title="收集箱"
                @click="goInbox">
          <span v-html="icon('clip')"></span><span>收集</span>
          <em v-if="inboxPendingCount > 0" class="is-muted">{{ inboxPendingCount }}</em>
        </button>
        <button type="button"
                :class="['sidebar-quick-btn', { active: route.name === 'new-session' }]"
                title="提问"
                @click="openNewSession">
          <span v-html="icon('edit')"></span><span>提问</span>
        </button>
      </div>
      <InboxComposer />
      <div class="sidebar-head">
        <div class="sidebar-head-row">
          <div class="sidebar-title">会话 </div>
          <span id="sessionStats" class="sidebar-stat">{{ stats.total }} 个 · 进行中 {{ stats.active }} · 完成 {{ stats.completed }} </span>
        </div>
      </div>
      <div class="session-list" id="sessionList">
        <div v-if="!sortedSessions.length" class="sidebar-empty">暂无会话</div>
        <div v-for="s in sortedSessions" :key="s.id"
             :class="['session-item', { active: s.id === selectedId, pinned: !!s.pinned_at, editing: editingId === s.id }]"
             :data-sid="s.id"
             tabindex="0"
             @mouseenter="prefetch(s.id)"
             @focus="prefetch(s.id)"
             @click="onSelect(s.id)"
             @keydown.enter="onSelect(s.id)"
             @keydown.space.prevent="onSelect(s.id)">
          <div class="session-item-row">
            <span :class="['stage-badge', getStageMeta(s.status).cls]">{{ getStageMeta(s.status).label }}</span>
            <span v-if="s.pinned_at" class="session-pin-mark">置顶</span>
            <input v-if="editingId === s.id"
                   class="session-rename-input"
                   :data-sid="s.id"
                   v-model="editingTitle"
                   @click.stop
                   @keydown.stop
                   @keydown.enter.prevent="commitEditing(s)"
                   @keydown.esc.prevent="cancelEditing"
                   @blur="commitEditing(s)" />
            <span v-else class="session-item-title">{{ s.title || '未命名' }}</span>
            <button class="session-menu-trigger"
                    type="button"
                    title="session 操作"
                    aria-label="session 操作"
                    @click.stop="openMenu(s, $event)">⋯</button>
          </div>
        </div>
      </div>
      <div v-if="menu.open" class="session-context-menu" :style="menuStyle" @click.stop>
        <button type="button" class="session-menu-action" @click="runAction('share')">分享</button>
        <button type="button" class="session-menu-action" @click="runAction('rename')">重命名</button>
        <button type="button" class="session-menu-action" @click="runAction('pin')">{{ menu.session?.pinned_at ? '取消置顶' : '置顶' }}</button>
        <button type="button" class="session-menu-action danger" @click="runAction('delete')">删除</button>
      </div>
      <div class="sidebar-resizer" id="sidebarResizer"></div>
    </aside>
  `,
});
