// ── app.js ───────────────────────────────────────────────────────────────────
// 应用入口：状态管理、事件协调、轮询

import { getSessions, createSession, getWorkspace, deepenSession, startFeynmanRequest, completeReview } from './api.js';
import { renderSidebar } from './sidebar.js';
import { openNewSessionModal } from './modal.js';
import { openSettings } from './settings.js';
import {
  renderWorkspace, renderEmpty, refreshCurrentPanel
} from './workspace.js';
import { icon } from './utils.js';

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
  localStorage.setItem('aiterate-theme', next);
  if (window.syncHljsTheme) syncHljsTheme(next);
  const btn = document.getElementById('themeToggleBtn');
  if (btn) btn.innerHTML = next === 'mono' ? icon('sun') : icon('moon');
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
      if (payload?.session?.status !== 'preparing') stopPolling();
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
  if (status === 'preparing') startPolling(payload.session.id);
}

async function selectSession(sessionId, { pushHistory = true } = {}) {
  stopPolling();
  state.selectedSessionId = sessionId;
  state.currentFeynmanGroupId = null;
  renderSidebar(state.sessions, sessionId, selectSession);
  setNotice('');
  // 移动端：选择后自动收起抽屉
  const sidebar = document.getElementById('sessionSidebar');
  const overlay = document.getElementById('sidebarOverlay');
  if (sidebar?.classList.contains('expanded')) {
    sidebar.classList.remove('expanded');
    overlay?.classList.remove('active');
  }
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
  btn.innerHTML = text;
}

async function submitDeepAction(actionType) {
  if (!state.selectedSessionId) return;
  const inputId = actionType === 'take' ? 'takeInput' : 'questionInput';
  const btnId = actionType === 'take' ? 'submitTakeBtn' : 'submitQuestionBtn';
  const idleText = actionType === 'take' ? `${icon('edit')} 提交理解` : `${icon('bulb')} 提交追问`;
  const content = (document.getElementById(inputId)?.value || '').trim();
  if (!content) return;

  setBtn(btnId, true, `${icon('clock')} 处理中...`);
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
  setBtn('startFeynmanBtn', true, `${icon('clock')} 生成费曼题...`);
  try {
    await startFeynmanRequest(state.selectedSessionId);
    await refreshCurrentWorkspace();
    setNotice('费曼题已生成，开始费曼检验。');
  } catch (err) {
    setNotice(`启动费曼失败：${err.message}`, 'error');
  } finally {
    setBtn('startFeynmanBtn', false, `${icon('check')} 我觉得差不多了，开始费曼`);
  }
}

async function submitFeynman() {
  if (!state.selectedSessionId || !state.currentFeynmanGroupId) return;
  const answers = Array.from(document.querySelectorAll('.review-answer')).map(el => el.value.trim());
  if (answers.some(a => !a)) { alert('请填写所有费曼答案'); return; }

  setBtn('submitFeynmanBtn', true, `${icon('clock')} 评分中...`);
  try {
    const data = await completeReview(state.selectedSessionId, state.currentFeynmanGroupId, answers);
    await refreshCurrentWorkspace();
    setNotice(data.passed ? '费曼检验通过，学习完成！🎉' : '费曼未通过，已退回深化阶段。');
  } catch (err) {
    setNotice(`提交失败：${err.message}`, 'error');
  } finally {
    setBtn('submitFeynmanBtn', false, `${icon('chart')} 提交答案`);
  }
}

// ── new session ───────────────────────────────────────────────────────────────

function openNewSession() {
  openNewSessionModal(async (title, content, entryType, webSearch, nodeId) => {
    const data = await createSession(title, content, entryType, webSearch, nodeId);
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
    const sidebar = document.getElementById('sessionSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const expanded = sidebar?.classList.toggle('expanded');
    if (overlay) overlay.classList.toggle('active', expanded);
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
  selectSession,
  submitDeepAction,
  startFeynman,
  submitFeynman,
  showKnowledgeTree: async () => {
    const { getKnowledgeTree, request } = await import('./api.js');
    try {
      const [treeData, progressData] = await Promise.all([
        getKnowledgeTree(),
        request('/api/knowledge-tree/progress'),
      ]);
      const tree = treeData.tree || [];
      const progress = progressData.progress || [];
      const progMap = {};
      for (const p of progress) progMap[p.node_id] = p;

      // 域名 → 图标映射
      const domainIcons = {
        '计算机': 'monitor',
        '写作': 'edit',
        '心理学': 'brain',
        '哲学': 'atom',
      };

      function statusDotCls(p) {
        const total = p?.total_sessions || 0;
        const completed = p?.completed_sessions || 0;
        const active = p?.active_sessions || 0;
        if (completed === total && total > 0) return 'kt-dot-mastered';
        if (active > 0) return 'kt-dot-learning';
        if (total > 0) return 'kt-dot-review';
        return 'kt-dot-untouched';
      }

      // 统计域下有多少节点被触碰过
      function touchedCount(node) {
        const p = progMap[node.id];
        let count = (p?.total_sessions || 0) > 0 ? 1 : 0;
        if (node.children) {
          for (const c of node.children) count += touchedCount(c);
        }
        return count;
      }

      function renderChild(node, depth) {
        const p = progMap[node.id];
        const total = p?.total_sessions || 0;
        const hasProgress = total > 0;
        const hasChildren = node.children?.length > 0;
        const dotCls = hasProgress ? statusDotCls(p) : 'kt-dot-untouched';

        const childrenHtml = hasChildren
          ? node.children.map(c => renderChild(c, depth + 1)).join('')
          : '';

        // 深层无进度无子节点：不展示
        if (!hasProgress && !hasChildren && depth > 1) return '';

        const indent = (depth - 1) * 20;

        return `
          <div class="kt-child" style="padding-left:${indent}px">
            <div class="kt-child-row">
              <span class="kt-dot ${dotCls}"></span>
              <span class="kt-child-title">${node.title || node.id}</span>
            </div>
            ${childrenHtml}
          </div>`;
      }

      function renderDomain(node) {
        const iconName = domainIcons[node.title] || 'book';
        const hasChildren = node.children?.length > 0;
        const touched = touchedCount(node);

        const childrenHtml = hasChildren
          ? node.children.map(c => renderChild(c, 1)).join('')
          : '';

        return `
          <div class="kt-domain-card">
            <div class="kt-domain-header" onclick="
              const card = this.parentElement;
              const body = card.querySelector('.kt-domain-body');
              const arrow = card.querySelector('.kt-arrow');
              body.style.display = body.style.display === 'none' ? 'block' : 'none';
              arrow.textContent = body.style.display === 'none' ? '▶' : '▼';
            ">
              <span class="kt-arrow">▶</span>
              <span class="kt-domain-icon">${icon(iconName)}</span>
              <span class="kt-domain-title">${node.title}</span>
              ${touched > 0 ? `<span class="kt-domain-touched">${touched} 个知识点</span>` : ''}
            </div>
            <div class="kt-domain-body" style="display:none">
              ${childrenHtml || '<div class="kt-child-empty">暂无子节点</div>'}
            </div>
          </div>`;
      }

      const html = tree.map(n => renderDomain(n)).join('');

      const existing = document.getElementById('knowledgeTreeModal');
      if (existing) existing.remove();
      const el = document.createElement('div');
      el.id = 'knowledgeTreeModal';
      el.className = 'modal-overlay';
      el.innerHTML = `
        <div class="modal-box knowledge-tree-modal" role="dialog" style="max-width:540px; max-height:85vh;">
          <div class="modal-header">
            <div class="modal-title">${icon('compass')} 知识地图</div>
            <button class="modal-close" id="ktCloseBtn">✕</button>
          </div>
          <div class="modal-body kt-modal-body">
            <div class="kt-legend">
              <span><span class="kt-dot kt-dot-mastered"></span> 已掌握</span>
              <span><span class="kt-dot kt-dot-learning"></span> 学习中</span>
              <span><span class="kt-dot kt-dot-review"></span> 待复习</span>
              <span><span class="kt-dot kt-dot-untouched"></span> 未触及</span>
            </div>
            <div class="kt-tree">${html || '<div class="muted">还没有绑定知识节点的 session</div>'}</div>
          </div>
        </div>`;
      document.body.appendChild(el);
      document.getElementById('ktCloseBtn').addEventListener('click', () => el.remove());
      el.addEventListener('click', e => { if (e.target === el) el.remove(); });
      document.addEventListener('keydown', function esc(e) {
        if (e.key === 'Escape') { el.remove(); document.removeEventListener('keydown', esc); }
      });
    } catch (err) {
      console.error('knowledge tree error', err);
    }
  },
  showCommandCenter: async () => {
    const { request } = await import('./api.js');
    try {
      const data = await request('/api/command-center');

      // 渲染辅助函数
      const sessionLink = (s) => `<a class="cmd-link" href="#" onclick="event.preventDefault();window.app.selectSession(${s.id});document.getElementById('commandCenterModal')?.remove()">${s.title || '未命名'}</a>`;
      const scoreBadge = (s) => s.score ? ` <span class="cmd-score">${s.score}分</span>` : '';
      const nodeTag = (s) => s.knowledge_node_id ? ` <span class="cmd-node">${s.knowledge_node_id.split('.').pop()}</span>` : '';

      // 1. 费曼未完成
      const feynmanHtml = data.feynman_pending?.length
        ? data.feynman_pending.map(s => `<div class="cmd-item">${icon('zap')} ${sessionLink(s)}${scoreBadge(s)}${nodeTag(s)}</div>`).join('')
        : `<div class="cmd-empty">没有未完成的费曼检验 ${icon('check')}</div>`;

      // 2. 今日复习
      const reviewHtml = data.review_due?.length
        ? data.review_due.map(r => {
            const overdue = r.review_date < new Date().toISOString().split('T')[0] ? ' <span class="cmd-overdue">逾期</span>' : '';
            const round = r.review_round > 0 ? `第${r.review_round+1}次` : '首次';
            return `<div class="cmd-item">${icon('refresh')} ${round}${overdue} — ${sessionLink(r)}${scoreBadge(r)}${nodeTag(r)}
              <button class="btn btn-sm cmd-done-btn" data-rid="${r.review_id}">✓完成</button></div>`;
          }).join('')
        : `<div class="cmd-empty">今天没有到期的复习</div>`;

      // 3. 失败/待修正
      const failedHtml = data.failed_sessions?.length
        ? data.failed_sessions.map(s => `<div class="cmd-item">${icon('xmark')} ${sessionLink(s)}${scoreBadge(s)}${nodeTag(s)}</div>`).join('')
        : `<div class="cmd-empty">没有失败的 session ${icon('check')}</div>`;

      // 4. 学习中
      const activeHtml = data.active_sessions?.length
        ? data.active_sessions.map(s => `<div class="cmd-item">${icon('book')} ${sessionLink(s)}${scoreBadge(s)}${nodeTag(s)}</div>`).join('')
        : '<div class="cmd-empty">没有进行中的 session</div>';

      // 5. 推荐节点
      const nodeHtml = data.suggested_nodes?.length
        ? data.suggested_nodes.map(n => {
            const progress = n.total ? `${n.done}/${n.total} 完成` : '';
            const name = n.knowledge_node_id ? n.knowledge_node_id.split('.').pop() : '未绑定';
            return `<div class="cmd-item">${icon('target')} ${name} <span class="cmd-node">${n.knowledge_node_id}</span> ${progress ? `<span class="cmd-progress">${progress}</span>` : ''}</div>`;
          }).join('')
        : '<div class="cmd-empty">暂无推荐</div>';

      const existing = document.getElementById('commandCenterModal');
      if (existing) existing.remove();
      const el = document.createElement('div');
      el.id = 'commandCenterModal';
      el.className = 'modal-overlay';
      el.innerHTML = `
        <div class="modal-box command-center-modal" role="dialog" style="max-width:560px; max-height:85vh;">
          <div class="modal-header">
            <div class="modal-title">${icon('target')} 指挥中心</div>
            <button class="modal-close" id="ccCloseBtn">✕</button>
          </div>
          <div class="modal-body cc-body">
            <div class="cc-section">
              <div class="cc-section-title">${icon('zap')} 待完成费曼</div>
              ${feynmanHtml}
            </div>
            <div class="cc-section">
              <div class="cc-section-title">${icon('refresh')} 今日复习</div>
              ${reviewHtml}
            </div>
            <div class="cc-section">
              <div class="cc-section-title">${icon('xmark')} 待修正</div>
              ${failedHtml}
            </div>
            <div class="cc-section">
              <div class="cc-section-title">${icon('book')} 进行中</div>
              ${activeHtml}
            </div>
            <div class="cc-section">
              <div class="cc-section-title">${icon('target')} 推荐继续</div>
              ${nodeHtml}
            </div>
          </div>
        </div>`;
      document.body.appendChild(el);
      document.getElementById('ccCloseBtn').addEventListener('click', () => el.remove());
      el.addEventListener('click', e => { if (e.target === el) el.remove(); });
      document.addEventListener('keydown', function esc(e) {
        if (e.key === 'Escape') { el.remove(); document.removeEventListener('keydown', esc); }
      });

      // "完成"按钮事件
      el.querySelectorAll('.cmd-done-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const rid = btn.dataset.rid;
          btn.disabled = true;
          btn.textContent = '…';
          try {
            await request(`/api/review/${rid}/complete`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
            btn.textContent = '✓已标记';
            btn.classList.add('cmd-done');
          } catch (err) {
            btn.textContent = '失败';
            btn.disabled = false;
            console.error('complete review error', err);
          }
        });
      });
    } catch (err) {
      console.error('command center error', err);
    }
  },
};

boot();
