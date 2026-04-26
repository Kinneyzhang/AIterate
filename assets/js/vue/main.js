// ── main.js ── Vue3 应用入口 ─────────────────────────────────────────────

import { createApp } from 'vue';
import { createRouter, createWebHashHistory } from 'vue-router';
import { setNotice } from './store.js';
import AppRoot from './components/AppRoot.js';

// ── 路由结构 ─────────────────────────────────────────────────────────────────
//
//   /                        首页（无选中 session）
//   /session/:id             重定向 → /session/:id/learn
//   /session/:id/learn       session 学习面板
//   /session/:id/deepen      session 深化面板
//   /session/:id/review      session 费曼/复盘面板
//
//   /new                     新建 session（overlay 页面）
//   /knowledge-tree          知识地图（overlay 页面）
//   /command-center          指挥中心（overlay 页面）
//   /settings                设置，重定向 → /settings/basic
//   /settings/basic          设置 - AI 基础
//   /settings/roles          设置 - 分功能模型
//   /settings/tavily         设置 - 联网搜索
//   /settings/database       设置 - 数据库
//   /settings/learn          设置 - 学习参数
//
// ── 路由用的空占位组件（vue-router 4 要求每条 route 必须有 component）──
const EmptyView = { template: '<div></div>' };

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/',                         name: 'home',             component: EmptyView },

    // session panels
    { path: '/session/:id',              redirect: to => ({ name: 'session-learn', params: to.params }) },
    { path: '/session/:id/learn',        name: 'session-learn',   component: EmptyView, props: true },
    { path: '/session/:id/deepen',       name: 'session-deepen',  component: EmptyView, props: true },
    { path: '/session/:id/review',       name: 'session-review',  component: EmptyView, props: true },

    // overlay pages (独立功能页，不叫 modal)
    { path: '/new',                      name: 'new-session',      component: EmptyView },
    { path: '/knowledge-tree',           name: 'knowledge-tree',   component: EmptyView },
    { path: '/command-center',           name: 'command-center',   component: EmptyView },

    // settings with inner tabs
    { path: '/settings',                 redirect: { name: 'settings-basic' } },
    { path: '/settings/basic',           name: 'settings-basic',   component: EmptyView },
    { path: '/settings/roles',           name: 'settings-roles',   component: EmptyView },
    { path: '/settings/tavily',          name: 'settings-tavily',  component: EmptyView },
    { path: '/settings/database',        name: 'settings-database',component: EmptyView },
    { path: '/settings/learn',           name: 'settings-learn',   component: EmptyView },
  ],
});

// ── App ─────────────────────────────────────────────────────────────────────
const app = createApp(AppRoot);

app.config.errorHandler = (err) => {
  console.error('Vue error:', err);
  setNotice(err.message || '未知错误', 'error');
};

app.use(router);
app.mount('#app');

window.__vueApp = app;
