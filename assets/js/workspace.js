// ── workspace.js ─────────────────────────────────────────────────────────────
// 三 panel tab 布局：学习 / 深化 / 费曼

import { escapeHtml, renderMarkdown, formatDate, getStageMeta } from './utils.js';

// ── 当前激活 tab ───────────────────────────────────────────────────────────────
let _activeTab = 'learn'; // 'learn' | 'deepen' | 'review'
let _payload = null;
let _reviewRoundId = null;
// 每个 session 最后访问的 tab，切换时保持
const _sessionTabMemory = new Map();

// ── helpers ───────────────────────────────────────────────────────────────────

function stageBadge(status) {
  const { label, cls } = getStageMeta(status);
  return `<span class="stage-badge ${cls}">${label}</span>`;
}

// ── tab 切换逻辑 ───────────────────────────────────────────────────────────────

export function setPhase(phase) {
  // 根据后端状态自动跳转到合适 tab
  if (phase === 'feynman' || phase === 'completed') {
    _activeTab = 'review';
  } else if (phase === 'deepening' || phase === 'revising') {
    _activeTab = 'deepen';
  } else {
    _activeTab = 'learn';
  }
}

export function switchTab(tab) {
  _activeTab = tab;
  // 记住这个 session 的 tab 选择
  const sid = _payload?.session?.id;
  if (sid) _sessionTabMemory.set(sid, tab);
  renderTabs();
  renderPanel();
}

function renderTabs() {
  const session = _payload?.session;
  const status = session?.status || 'idle';
  // 各 tab 是否可用
  const canDeepen = !['processing', 'idle'].includes(status);
  const canReview = ['feynman', 'completed'].includes(status)
    || !!(_payload?.rounds?.some(r => r.type === 'feynman'));

  ['learn', 'deepen', 'review'].forEach(tab => {
    const el = document.getElementById(`tab-${tab}`);
    if (!el) return;
    el.classList.toggle('active', tab === _activeTab);
    if (tab === 'deepen') el.disabled = !canDeepen;
    if (tab === 'review') el.disabled = !canReview;
  });
}

// ── panel 内容构建 ─────────────────────────────────────────────────────────────

function buildLearnPanel() {
  const session = _payload?.session;
  if (!session) return '';

  const aiText = session.material || session.material;
  const typeLabel = session.type === 'viewpoint' ? '观点' : '问题';
  const scoreHtml = session.score
    ? `<span>评分 ${session.score}/100</span>` : '';

  const answerHtml = aiText
    ? `<div class="panel-section">
        <div class="ps-label">AI 回答</div>
        <div class="ps-body md-body">${renderMarkdown(aiText)}</div>
       </div>`
    : `<div class="panel-empty">
        <span class="muted">AI 正在后台回答，稍后刷新查看…</span>
       </div>`;

  // 原始问题：优先显示 content（新格式完整问题），兼容存量（只有 title）
  // 存量数据 content 为空或和 title 相同，直接用 title
  const rawQuestion = (session.content && session.content.trim() && session.content !== session.title)
    ? session.content
    : session.title;
  const questionHtml = rawQuestion
    ? `<div class="original-question">${escapeHtml(rawQuestion)}</div>` : '';

  return `
    <div class="panel-header">
      <div class="ph-title">${escapeHtml(session.title || '未命名')}</div>
      <div class="ph-meta">
        ${stageBadge(session.status)}
        <span>${typeLabel}</span>
        <span>${formatDate(session.created_at)}</span>
        ${scoreHtml}
      </div>
    </div>
    ${questionHtml}
    ${answerHtml}`;
}

function buildDeepenPanel() {
  const session = _payload?.session;
  const rounds = (_payload?.rounds || []).filter(r => r.type === 'take' || r.type === 'press');
  const status = session?.status;
  const canAct = ['learning', 'deepening', 'revising'].includes(status);
  const canStartReview = canAct;

  // 历史轮次
  const historyHtml = rounds.length ? rounds.map(r => buildDeepenRoundCard(r)).join('') : '';

  // 如果上一轮费曼没过，显示提示
  const reviewResult = _payload?.latest_review_result;
  const resultBanner = reviewResult && status !== 'completed' ? `
    <div class="review-result-banner ${(reviewResult.score || 0) >= 60 ? 'pass' : 'fail'}">
      <span>上一轮费曼 ${reviewResult.score || 0} 分</span>
      <span class="muted small">${(reviewResult.score || 0) >= 60 ? '通过 ✓' : '未通过，继续深化'}</span>
    </div>` : '';

  // 输入区
  const inputArea = canAct ? `
    <div class="deepen-inputs">
      <div class="deepen-col">
        <div class="col-label muted small">❓ 提追问</div>
        <textarea id="questionInput" rows="4"
          placeholder="追问某个细节、反例、边界条件…"></textarea>
        <button class="btn btn-primary btn-block mt8" id="submitQuestionBtn"
          onclick="window.app.submitDeepAction('press')">提交追问</button>
      </div>
      <div class="deepen-col">
        <div class="col-label muted small">✍️ 写理解</div>
        <textarea id="takeInput" rows="4"
          placeholder="用自己的话说说你对 AI 回答的理解，有没有偏差 AI 会告诉你…"></textarea>
        <button class="btn btn-primary btn-block mt8" id="submitTakeBtn"
          onclick="window.app.submitDeepAction('take')">提交理解</button>
      </div>
    </div>
    <button class="btn btn-success btn-block mt12" id="startFeynmanBtn"
      onclick="window.app.startFeynman()">✅ 差不多了，开始费曼检验</button>` : '';

  const noHistory = !historyHtml && !canAct
    ? `<div class="panel-empty muted">暂无深化记录</div>` : '';

  return `
    ${resultBanner}
    ${historyHtml ? `<div class="deepen-history">${historyHtml}</div>` : noHistory}
    ${inputArea}`;
}

function buildDeepenRoundCard(round) {
  if (round.type === 'take') {
    return `
      <div class="round-card round-take">
        <div class="round-label">💡 理解</div>
        <div class="round-user">${escapeHtml(round.input || '')}</div>
        <div class="round-ai md-body">${renderMarkdown(round.output || '')}</div>
        ${round.score ? `<div class="round-score">评分 ${round.score}/100</div>` : ''}
      </div>`;
  }
  if (round.type === 'press') {
    return `
      <div class="round-card round-press">
        <div class="round-label">❓ 追问</div>
        <div class="round-user">${escapeHtml(round.input || '')}</div>
        <div class="round-ai md-body">${renderMarkdown(round.output || '')}</div>
      </div>`;
  }
  return '';
}

function buildReviewPanel() {
  const session = _payload?.session;
  const status = session?.status;
  const currentGroup = _payload?.current_review_group || [];  // 待答题列表（每题独立 round）

  // 当前待答题组
  const pendingHtml = currentGroup.length > 0 && status === 'feynman' ? `
    <div class="panel-section">
      <div class="ps-label">🧪 费曼检验</div>
      <div class="ps-hint muted small mb12">用自己的话回答，AI 会评估你的掌握程度。</div>
      ${currentGroup.map((r, i) => `
        <div class="review-q">
          <div class="review-q-title">Q${i + 1}. ${escapeHtml(r.input || '')}</div>
          <textarea class="review-answer" rows="4"
            placeholder="用自己的话回答…">${escapeHtml(r.output || '')}</textarea>
        </div>`).join('')}
      <button class="btn btn-primary btn-block mt8" id="submitFeynmanBtn"
        onclick="window.app.submitFeynman()">📊 提交答案</button>
    </div>` : '';

  // 已完成费曼历史（按 group_id 聚合）
  const allRounds = _payload?.rounds || [];
  const doneFeynman = allRounds.filter(r => r.type === 'feynman' && r.status === 'completed');
  const byGroup = {};
  for (const r of doneFeynman) {
    const gid = r.group_id ?? r.id;
    (byGroup[gid] = byGroup[gid] || []).push(r);
  }
  const historyHtml = Object.values(byGroup).map(grp => {
    const sorted = grp.sort((a, b) => a.seq - b.seq);
    const groupScore = sorted.reduce((s, r) => s + (r.score || 0), 0);
    const avgScore = Math.round(groupScore / sorted.length);
    return `
      <div class="round-card round-review">
        <div class="round-label">🧪 费曼记录 · ${avgScore}/100</div>
        <div class="qa-list">
          ${sorted.map((r, i) => {
            const scoreTag = r.score != null
              ? `<span class="item-score ${r.score >= 60 ? 'pass' : 'fail'}">${r.score}分</span>` : '';
            const comment = r.score_comment
              ? `<div class="item-comment muted small">${escapeHtml(r.score_comment)}</div>` : '';
            return `
            <div class="qa-pair">
              <div class="qa-q">Q${i + 1} ${escapeHtml(r.input || '')} ${scoreTag}</div>
              <div class="qa-a">${escapeHtml(r.output || '（未作答）')}</div>
              ${comment}
            </div>`;
          }).join('')}
        </div>
      </div>`;
  }).join('');

  // 已完成总结
  const finalResult = _payload?.latest_review_result;
  const completedHtml = status === 'completed' && finalResult ? `
    <div class="panel-section completed-summary">
      <div class="final-score-row">
        <span class="final-score-num">${session.score || 0}/100</span>
        <span class="stage-badge stage-completed">已完成</span>
      </div>
    </div>` : '';

  const noReview = !pendingHtml && !historyHtml && !completedHtml
    ? `<div class="panel-empty muted">完成深化阶段后可开始费曼检验</div>` : '';

  return `
    ${completedHtml}
    ${pendingHtml}
    ${historyHtml ? `<div class="deepen-history">${historyHtml}</div>` : ''}
    ${noReview}`;
}

// ── 渲染 panel 内容 ────────────────────────────────────────────────────────────

function renderPanel() {
  const el = document.getElementById('panelContent');
  if (!el) return;
  if (!_payload?.session) { el.innerHTML = ''; return; }
  if (_activeTab === 'learn')  el.innerHTML = buildLearnPanel();
  if (_activeTab === 'deepen') el.innerHTML = buildDeepenPanel();
  if (_activeTab === 'review') el.innerHTML = buildReviewPanel();
  // 触发代码高亮
  if (window.hljs) requestAnimationFrame(() => hljs.highlightAll());
}

// ── public: 渲染整个 workspace ────────────────────────────────────────────────

export function renderEmpty(msg) {
  _payload = null;
  _activeTab = 'learn';
  _reviewRoundId = null;
  const panel = document.getElementById('workspacePanel');
  if (!panel) return;
  panel.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">💡</div>
      <h3>${escapeHtml(msg || '从左侧选一个 session，或点 ＋ 新建')}</h3>
      <p>每个问题 / 观点都是独立迭代单元，经过三个阶段走向完成。</p>
    </div>`;
}

export function renderWorkspace(payload, reviewRoundId) {
  _payload = payload;
  _reviewRoundId = reviewRoundId ?? null;

  const panel = document.getElementById('workspacePanel');
  if (!panel) return;

  if (!payload?.session) { renderEmpty(); return; }

  const { status } = payload.session;

  // 设定默认 tab：优先用记忆；否则根据状态推断
  const remembered = _sessionTabMemory.get(payload.session.id);
  if (remembered) {
    _activeTab = remembered;
  } else {
    setPhase(
      status === 'feynman' || status === 'completed' ? 'feynman' :
      status === 'deepening' ? 'deepening' :
      status === 'revising'  ? 'revising'  :
      'learning'
    );
  }

  panel.innerHTML = `
    <div class="ws-tabs">
      <button class="ws-tab" id="tab-learn"   onclick="window.app.switchTab('learn')">📖 学习</button>
      <button class="ws-tab" id="tab-deepen"  onclick="window.app.switchTab('deepen')">🔁 深化</button>
      <button class="ws-tab" id="tab-review"  onclick="window.app.switchTab('review')">🧪 费曼</button>
    </div>
    <div class="panel-content" id="panelContent"></div>`;

  renderTabs();
  renderPanel();
}

// 供 app.js 调用：无需重新 fetch，直接刷新当前 panel
export function refreshCurrentPanel() {
  renderTabs();
  renderPanel();
}
