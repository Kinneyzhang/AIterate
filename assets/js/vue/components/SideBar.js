// ── SideBar.js ── 精确复刻原版 sidebar ───────────────────────────────────

import { defineComponent, computed, ref, onMounted } from 'vue';
import { store, getStageMeta, formatDate } from '../store.js';

export default defineComponent({
  props: { sessions: Array, selectedId: Number, expanded: Boolean },
  emits: ['select'],

  setup(props, { emit }) {
    const globalStats = ref({ total_sessions: 0, completed_sessions: 0, active_sessions: 0 });

    const stats = computed(() => {
      // 优先用全局 stats（更准确），fallback 到列表统计
      if (globalStats.value.total_sessions > 0) {
        return {
          total: globalStats.value.total_sessions,
          active: globalStats.value.total_sessions - (globalStats.value.completed_sessions || 0),
          completed: globalStats.value.completed_sessions || 0,
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

    async function loadGlobalStats() {
      try {
        const resp = await fetch('/api/stats');
        globalStats.value = await resp.json();
      } catch (_) { /* fallback to list stats */ }
    }

    onMounted(loadGlobalStats);

    function onSelect(id) {
      emit('select', id);
    }

    return { stats, sortedSessions, onSelect, getStageMeta, formatDate };
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
        <div v-if="!sortedSessions.length" class="sidebar-empty">加载中…</div>
        <div v-for="s in sortedSessions" :key="s.id"
             :class="['session-item', { active: s.id === selectedId }]"
             :data-sid="s.id"
             tabindex="0"
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
