// ── AppRoot.js ── 根组件，整体布局 ───────────────────────────────────────

import { defineComponent } from 'vue';
import { store, currentSession, setNotice } from '../store.js';
import { api } from '../api.js';
import TopBar from './TopBar.js';
import SideBar from './SideBar.js';
import Workspace from './Workspace.js';
import NewSessionModal from './modals/NewSessionModal.js';
import SettingsModal from './modals/SettingsModal.js';
import KnowledgeTreeModal from './modals/KnowledgeTreeModal.js';
import CommandCenterModal from './modals/CommandCenterModal.js';

export default defineComponent({
  components: { TopBar, SideBar, Workspace, NewSessionModal, SettingsModal, KnowledgeTreeModal, CommandCenterModal },
  
  data: () => ({ store }),
  
  methods: {
    async selectSession(id) {
      store.selectedSessionId = id;
      store.sidebarExpanded = false;
      store.workspace = null;
      setNotice('');
      try {
        store.workspace = await api.getWorkspace(id);
        const g = store.workspace?.current_review_group;
        store.currentFeynmanGroupId = (g?.length > 0) ? (g[0].group_id ?? g[0].id) : null;
        if (store.workspace?.session?.status === 'preparing') this.startPolling(id);
        else this.stopPolling();
      } catch (err) {
        setNotice(`加载失败：${err.message}`, 'error');
      }
    },
    
    async refreshAll(showNotice) {
      store.sessions = await api.getSessions();
      if (store.selectedSessionId) {
        store.workspace = await api.getWorkspace(store.selectedSessionId);
        const g = store.workspace?.current_review_group;
        store.currentFeynmanGroupId = (g?.length > 0) ? (g[0].group_id ?? g[0].id) : null;
      }
      if (showNotice) setNotice('已刷新。');
    },
    
    startPolling(sessionId) {
      this.stopPolling();
      store.pollTimer = setInterval(async () => {
        if (store.selectedSessionId !== sessionId) { this.stopPolling(); return; }
        try {
          store.workspace = await api.getWorkspace(sessionId);
          store.sessions = await api.getSessions();
          if (store.workspace?.session?.status !== 'preparing') this.stopPolling();
        } catch (err) {
          console.error('poll failed', err);
        }
      }, 3000);
    },
    
    stopPolling() {
      if (store.pollTimer) { clearInterval(store.pollTimer); store.pollTimer = null; }
    },
  },
  
  template: `
    <div class="app-shell">
      <TopBar @open-new-session="store.showNewSession = true"
              @open-settings="store.showSettings = true"
              @open-knowledge-tree="store.showKnowledgeTree = true"
              @open-command-center="store.showCommandCenter = true"
              @toggle-sidebar="store.sidebarExpanded = !store.sidebarExpanded"
              @refresh="refreshAll(true)" />
      <div class="workspace-shell">
        <SideBar :sessions="store.sessions"
                 :selected-id="store.selectedSessionId"
                 :expanded="store.sidebarExpanded"
                 @select="selectSession"
                 @close="store.sidebarExpanded = false" />
        <Workspace @refresh="refreshAll(false)" />
      </div>
      <div v-if="store.notice.text" :class="['notice-bar', 'visible', store.notice.type === 'error' ? 'notice-error' : '']">
        {{ store.notice.text }}
      </div>
      <NewSessionModal v-if="store.showNewSession" @close="store.showNewSession = false" @created="refreshAll(false); store.showNewSession = false" />
      <SettingsModal v-if="store.showSettings" @close="store.showSettings = false" />
      <KnowledgeTreeModal v-if="store.showKnowledgeTree" @close="store.showKnowledgeTree = false" />
      <CommandCenterModal v-if="store.showCommandCenter" @close="store.showCommandCenter = false" @select-session="selectSession" />
    </div>
  `,
});
