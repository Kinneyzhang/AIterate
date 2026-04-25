// ── main.js ── Vue3 应用入口 ─────────────────────────────────────────────

import { createApp } from 'vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import { store, setNotice } from './store.js';
import { api } from './api.js';
import AppRoot from './components/AppRoot.js';

// ── Router ──────────────────────────────────────────────────────────────────
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home' },
    { path: '/session/:id', name: 'session', props: true },
  ],
});

// ── App ─────────────────────────────────────────────────────────────────────
const app = createApp(AppRoot);
app.use(router);
app.mount('#app');

// ── Global error handler ────────────────────────────────────────────────────
app.config.errorHandler = (err) => {
  console.error('Vue error:', err);
  setNotice(err.message || '未知错误', 'error');
};

// ── Load sessions on boot ───────────────────────────────────────────────────
(async () => {
  try {
    store.sessions = await api.getSessions();
  } catch (err) {
    console.error('Failed to load sessions', err);
  }
})();

// ── Expose for HTML onclick fallbacks ───────────────────────────────────────
window.__vueApp = app;
