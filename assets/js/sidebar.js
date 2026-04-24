// ── sidebar.js ───────────────────────────────────────────────────────────────
// 左侧会话列表的渲染与交互

import { escapeHtml, formatDate, getStageMeta } from './utils.js';

export function renderSidebar(sessions, selectedId, onSelect) {
  const list = document.getElementById('sessionList');
  const stats = document.getElementById('sessionStats');

  if (!sessions.length) {
    stats.textContent = '暂无 session';
    list.innerHTML = '<div class="sidebar-empty">点击右上角 ＋ 新建第一个</div>';
    return;
  }

  const activeCount = sessions.filter(s =>
    ['processing', 'answered', 'iterating', 'reviewing'].includes(s.status)
  ).length;
  const doneCount = sessions.filter(s => s.status === 'completed').length;
  stats.textContent = `${sessions.length} 个 · 进行中 ${activeCount} · 完成 ${doneCount} `;

  list.innerHTML = sessions.map(s => {
    const { label, cls } = getStageMeta(s.status);
    const active = s.id === selectedId ? ' active' : '';
    const preview = s.material || s.content || '';
    const scoreHtml = s.score
      ? `<span class="score-dot">${s.score}/5</span>` : '';
    return `
      <div class="session-item${active}" data-sid="${s.id}" tabindex="0">
        <div class="session-item-row">
          <span class="stage-badge ${cls}">${label}</span>
          <span class="session-item-title">${escapeHtml(s.title || '未命名')}</span>
        </div>
      </div>`;
  }).join('');

  list.querySelectorAll('.session-item').forEach(el => {
    el.addEventListener('click', () => onSelect(Number(el.dataset.sid)));
    el.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') onSelect(Number(el.dataset.sid));
    });
  });
}
