// ── app.js ───────────────────────────────────────────────────────────────────
// 应用入口：状态管理、事件协调、轮询

import { getSessions, createSession, getWorkspace, deepenSession, startFeynmanRequest, completeReview } from './api.js';
import { renderSidebar } from './sidebar.js';
import { openNewSessionModal } from './modal.js';
import { openSettings } from './settings.js';
import {
  renderWorkspace, renderEmpty, refreshCurrentPanel
} from './workspace.js';

// ── state ─────────────────────────────────────────────────────────────────────

const state = {
  selectedSessionId: null,
  currentReviewRoundId: null,
  sessions: [],
  pollTimer: null,
};

// ── notice ────────────────────────────────────────────────────────────────────

function setNotice(msg, type = 'info') {
  const bar = document.getElementById('noticeBar');
  if (!bar) return;
  if (!msg) { bar.className = 'notice-bar'; bar.textContent = ''; return; }
  bar.textContent = msg;
  bar.className = `notice-bar visible${type === 'error' ? ' notice-error' : ''}`;
}

// ── theme ─────────────────────────────────────────────────────────────────────

function toggleTheme() {
  const cur = document.documentElement.dataset.theme || 'night';
  const next = cur === 'night' ? 'mono' : 'night';
  document.documentElement.dataset.theme = next;
  // 切换预加载的两套 CSS（disabled 方式，无重新加载，无抖动）
  const main = document.getElementById('themeStylesheet');
  const alt  = document.getElementById('themeStylesheetAlt');
  if (main && alt) {
    // 找到指向 next 主题的那个 link，enable 它；另一个 disable
    // 不改 href，避免触发 CSS 重新加载导致抖动
    const mainIsNext = main.href.includes(`/${next}.css`);
    main.disabled = !mainIsNext;
    alt.disabled  =  mainIsNext;
  }
  localStorage.setItem('learn-system-theme', next);
  if (window.syncHljsTheme) syncHljsTheme(next);
  const btn = document.getElementById('themeToggleBtn');
  if (btn) btn.textContent = next === 'mono' ? '☀️' : '🌙';
}

// ── polling ───────────────────────────────────────────────────────────────────

function stopPolling() {
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
}

function startPolling(sessionId) {
  stopPolling();
  state.pollTimer = setInterval(async () => {
    if (state.selectedSessionId !== sessionId) { stopPolling(); return; }
    try {
      const payload = await getWorkspace(sessionId);
      renderWorkspaceWithState(payload);
      await loadSessions();
      if (payload?.session?.status !== 'processing') stopPolling();
    } catch (err) {
      console.error('poll failed', err);
    }
  }, 3000);
}

// ── session list ──────────────────────────────────────────────────────────────

async function loadSessions() {
  const sessions = await getSessions();
  state.sessions = sessions;
  renderSidebar(sessions, state.selectedSessionId, selectSession);
  return sessions;
}

// ── workspace ─────────────────────────────────────────────────────────────────

function renderWorkspaceWithState(payload) {
  if (!payload?.session) { renderEmpty(); return; }
  const { status } = payload.session;
  const group = payload.current_review_group || [];
  state.currentFeynmanGroupId = group.length > 0 ? (group[0].group_id ?? group[0].id) : null;
  renderWorkspace(payload, state.currentFeynmanGroupId);
  if (status === 'processing') startPolling(payload.session.id);
}

async function selectSession(sessionId, { pushHistory = true } = {}) {
  stopPolling();
  state.selectedSessionId = sessionId;
  state.currentFeynmanGroupId = null;
  renderSidebar(state.sessions, sessionId, selectSession);
  setNotice('');
  if (pushHistory) {
    history.pushState({ sessionId }, '', `#session/${sessionId}`);
  }
  try {
    const payload = await getWorkspace(sessionId);
    renderWorkspaceWithState(payload);
  } catch (err) {
    setNotice(`加载失败：${err.message}`, 'error');
  }
}

async function refreshCurrentWorkspace() {
  if (!state.selectedSessionId) { renderEmpty('先从左侧选一个 session'); return; }
  try {
    const payload = await getWorkspace(state.selectedSessionId);
    renderWorkspaceWithState(payload);
    await loadSessions();
  } catch (err) {
    setNotice(`刷新失败：${err.message}`, 'error');
  }
}

// ── deep actions ──────────────────────────────────────────────────────────────

function setBtn(id, disabled, text) {
  const btn = document.getElementById(id);
  if (!btn) return;
  btn.disabled = disabled;
  btn.textContent = text;
}

async function submitDeepAction(actionType) {
  if (!state.selectedSessionId) return;
  const inputId = actionType === 'take' ? 'takeInput' : 'questionInput';
  const btnId = actionType === 'take' ? 'submitTakeBtn' : 'submitQuestionBtn';
  const idleText = actionType === 'take' ? '提交理解' : '提交追问';
  const content = (document.getElementById(inputId)?.value || '').trim();
  if (!content) return;

  setBtn(btnId, true, '⏳ 处理中...');
  try {
    await deepenSession(state.selectedSessionId, actionType, content);
    document.getElementById(inputId).value = '';
    await refreshCurrentWorkspace();
    setNotice(actionType === 'take' ? '理解评估完成，可继续迭代。' : '追问回答已返回。');
  } catch (err) {
    setNotice(`提交失败：${err.message}`, 'error');
  } finally {
    setBtn(btnId, false, idleText);
  }
}

async function startFeynman() {
  if (!state.selectedSessionId) return;
  setBtn('startFeynmanBtn', true, '⏳ 生成费曼题...');
  try {
    await startFeynmanRequest(state.selectedSessionId);
    await refreshCurrentWorkspace();
    setNotice('费曼题已生成，开始费曼检验。');
  } catch (err) {
    setNotice(`启动费曼失败：${err.message}`, 'error');
  } finally {
    setBtn('startFeynmanBtn', false, '✅ 我觉得差不多了，开始费曼');
  }
}

async function submitFeynman() {
  if (!state.selectedSessionId || !state.currentFeynmanGroupId) return;
  const answers = Array.from(document.querySelectorAll('.review-answer')).map(el => el.value.trim());
  if (answers.some(a => !a)) { alert('请填写所有费曼答案'); return; }

  setBtn('submitFeynmanBtn', true, '⏳ 评分中...');
  try {
    const data = await completeReview(state.selectedSessionId, state.currentFeynmanGroupId, answers);
    await refreshCurrentWorkspace();
    setNotice(data.passed ? '费曼检验通过，学习完成！🎉' : '费曼未通过，已退回深化阶段。');
  } catch (err) {
    setNotice(`提交失败：${err.message}`, 'error');
  } finally {
    setBtn('submitFeynmanBtn', false, '📊 提交答案');
  }
}

// ── new session ───────────────────────────────────────────────────────────────

function openNewSession() {
  openNewSessionModal(async (title, content, entryType, webSearch) => {
    const data = await createSession(title, content, entryType, webSearch);
    setNotice(`新 session #${data.session_id} 已入队，左侧可查看进度。`);
    const sessions = await loadSessions();
    // auto-select new session
    const newSid = data.session_id;
    if (newSid) await selectSession(newSid);
  });
}

// ── sidebar resize ────────────────────────────────────────────────────────────

function initSidebarResize() {
  const resizer = document.getElementById('sidebarResizer');
  const shell = document.querySelector('.workspace-shell');
  if (!resizer || !shell) return;

  const MIN = 180, MAX = 520;
  const saved = localStorage.getItem('sidebar-width');
  if (saved) shell.style.setProperty('--sidebar-width', saved + 'px');

  let startX, startW;

  resizer.addEventListener('mousedown', e => {
    e.preventDefault();
    startX = e.clientX;
    startW = document.getElementById('sessionSidebar').getBoundingClientRect().width;
    resizer.classList.add('dragging');
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = e => {
      const w = Math.min(MAX, Math.max(MIN, startW + e.clientX - startX));
      shell.style.setProperty('--sidebar-width', w + 'px');
    };
    const onUp = () => {
      resizer.classList.remove('dragging');
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      const w = document.getElementById('sessionSidebar').getBoundingClientRect().width;
      localStorage.setItem('sidebar-width', Math.round(w));
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

// ── boot ──────────────────────────────────────────────────────────────────────

async function boot() {
  initSidebarResize();
  // popstate: 前进/后退
  window.addEventListener('popstate', e => {
    const sid = e.state?.sessionId ?? parseHashSessionId();
    if (sid) selectSession(sid, { pushHistory: false });
    else renderEmpty();
  });

  try {
    await loadSessions();
    const sid = parseHashSessionId();
    if (sid) {
      await selectSession(sid, { pushHistory: false });
    } else {
      renderEmpty();
    }
  } catch (err) {
    setNotice(`初始化失败：${err.message}`, 'error');
  }
}

function parseHashSessionId() {
  const m = location.hash.match(/^#session\/(\d+)$/);
  return m ? Number(m[1]) : null;
}

// ── exports (called from inline HTML) ────────────────────────────────────────
window.app = {
  toggleTheme,
  openNewSession,
  openSettings,
  toggleSidebar: () => {
    document.getElementById('sessionSidebar')?.classList.toggle('expanded');
  },
  switchTab: (tab) => {
    const { switchTab } = window.__workspaceModule || {};
    // workspace.js 的 switchTab 通过 import 拿到
    import('./workspace.js').then(m => m.switchTab(tab));
  },
  refreshAll: async (showNotice) => {
    await loadSessions();
    if (state.selectedSessionId) await refreshCurrentWorkspace();
    if (showNotice) setNotice('已刷新。');
  },
  submitDeepAction,
  startFeynman,
  submitFeynman,
};

boot();
