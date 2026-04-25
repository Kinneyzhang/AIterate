// ── TopBar.js ──────────────────────────────────────────────────────────────

import { defineComponent } from 'vue';
import { store } from '../store.js';
import { icon } from '../icons.js';

export default defineComponent({
  emits: ['open-new-session', 'open-settings', 'open-knowledge-tree', 'open-command-center', 'toggle-sidebar', 'refresh'],
  
  methods: {
    toggleTheme() {
      const next = store.theme === 'night' ? 'mono' : 'night';
      store.theme = next;
      document.documentElement.dataset.theme = next;
      localStorage.setItem('aiterate-theme', next);
      if (window.syncHljsTheme) window.syncHljsTheme(next);
    },
  },
  
  template: `
    <header class="topbar">
      <button class="btn sidebar-toggle" id="sidebarToggle" title="折叠/展开" @click="$emit('toggle-sidebar')" v-html="icon('menu')"></button>
      <div class="topbar-title" v-html="icon('sparkle') + ' AIterate'"></div>
      <div class="topbar-actions">
        <button class="btn btn-sm" title="知识地图" @click="$emit('open-knowledge-tree')" v-html="icon('compass')"></button>
        <button class="btn btn-sm" title="指挥中心" @click="$emit('open-command-center')" v-html="icon('target')"></button>
        <button class="btn btn-sm" title="设置" @click="$emit('open-settings')" v-html="icon('gear')"></button>
        <button class="btn btn-icon" title="新建问题/观点" @click="$emit('open-new-session')">＋</button>
        <button class="btn btn-sm" title="切换主题" @click="toggleTheme" v-html="store.theme === 'mono' ? icon('sun') : icon('moon')"></button>
      </div>
    </header>
  `,
});
