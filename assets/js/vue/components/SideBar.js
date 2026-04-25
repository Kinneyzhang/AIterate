// ── SideBar.js ─────────────────────────────────────────────────────────────

import { defineComponent, computed } from 'vue';
import { store, getStageMeta, formatDate } from '../store.js';

export default defineComponent({
  props: { sessions: Array, selectedId: Number, expanded: Boolean },
  emits: ['select', 'close'],
  
  setup(props, { emit }) {
    const stats = computed(() => {
      const s = props.sessions || [];
      const completed = s.filter(x => x.status === 'completed').length;
      const active = s.filter(x => x.status !== 'completed' && x.status !== 'error').length;
      return { total: s.length, active, completed };
    });
    
    function stageClass(status) {
      return getStageMeta(status).cls || '';
    }
    
    function stageLabel(status) {
      return getStageMeta(status).label || '';
    }
    
    return { stats, stageClass, stageLabel, formatDate, emit };
  },
  
  template: `
    <div :class="['session-sidebar', { expanded }]" id="sessionSidebar">
      <div class="sidebar-overlay" :class="{ active: expanded }" @click="$emit('close')"></div>
      <div class="sidebar-header">
        <span class="sidebar-title">会话</span>
        <span class="sidebar-stat">{{ stats.total }} 个 · 进行中 {{ stats.active }} · 完成 {{ stats.completed }}</span>
      </div>
      <div class="sidebar-list">
        <div v-for="s in sessions" :key="s.id"
             :class="['session-item', { active: s.id === selectedId }]"
             @click="$emit('select', s.id)">
          <span class="session-stage" :class="stageClass(s.status)">{{ stageLabel(s.status) }}</span>
          <span class="session-title">{{ s.title || '未命名' }}</span>
          <span class="session-date">{{ formatDate(s.updated_at || s.created_at) }}</span>
        </div>
      </div>
    </div>
    <div class="sidebar-resizer" id="sidebarResizer"></div>
  `,
});
