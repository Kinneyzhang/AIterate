// ── SideBar.js ── 精确复刻原版 sidebar ───────────────────────────────────

import { defineComponent, computed } from 'vue';
import { store, getStageMeta, formatDate } from '../store.js';
import { api } from '../api.js';

export default defineComponent({
  props: { sessions: Array, selectedId: Number, expanded: Boolean },
  emits: ['select'],

  setup(props, { emit }) {
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

    const sortedSessions = computed(() => {
      return [...(props.sessions || [])].sort((a, b) => {
        const da = a.updated_at || a.created_at || '';
        const db = b.updated_at || b.created_at || '';
        return db.localeCompare(da);
      });
    });

    function onSelect(id) {
      emit('select', id);
    }

    function prefetch(id) {
      api.prefetchWorkspace(id);
    }

    return { stats, sortedSessions, onSelect, prefetch, getStageMeta, formatDate };
  },

  template: `
    <aside :class="['sidebar', { expanded }]" id="sessionSidebar">
      <div class="sidebar-head">
        <div class="sidebar-head-row">
          <div class="sidebar-title">会话 </div>
          <span id="sessionStats" class="sidebar-stat">{{ stats.total }} 个 · 进行中 {{ stats.active }} · 完成 {{ stats.completed }} </span>
        </div>
      </div>
      <div class="session-list" id="sessionList">
        <div v-if="!sortedSessions.length" class="sidebar-empty">暂无会话</div>
        <div v-for="s in sortedSessions" :key="s.id"
             :class="['session-item', { active: s.id === selectedId }]"
             :data-sid="s.id"
             tabindex="0"
             @mouseenter="prefetch(s.id)"
             @focus="prefetch(s.id)"
             @click="onSelect(s.id)"
             @keydown.enter="onSelect(s.id)"
             @keydown.space.prevent="onSelect(s.id)">
          <div class="session-item-row">
            <span :class="['stage-badge', getStageMeta(s.status).cls]">{{ getStageMeta(s.status).label }}</span>
            <span class="session-item-title">{{ s.title || '未命名' }}</span>
          </div>
        </div>
      </div>
      <div class="sidebar-resizer" id="sidebarResizer"></div>
    </aside>
  `,
});
