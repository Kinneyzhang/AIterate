// ── modal.js ─────────────────────────────────────────────────────────────────
// 新建 session 的弹出模态框

import { getReady, getKnowledgeTree } from './api.js';
import { icon } from './utils.js';

export function openNewSessionModal(onSubmit) {
  const existing = document.getElementById('newSessionModal');
  if (existing) existing.remove();

  const el = document.createElement('div');
  el.id = 'newSessionModal';
  el.className = 'modal-overlay';
  el.innerHTML = `
    <div class="modal-box" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
      <div class="modal-header">
        <div class="modal-title" id="modalTitle">提出问题或观点</div>
        <button class="modal-close" aria-label="关闭" id="modalCloseBtn">✕</button>
      </div>
      <div class="modal-body">
        <div id="modalConfigWarning" class="modal-config-warning" style="display:none"></div>
        <div class="type-toggle" id="modalTypeToggle">
          <button class="type-btn active" data-type="question">${icon('search')} 问题</button>
          <button class="type-btn" data-type="viewpoint">${icon('bulb')} 观点</button>
        </div>
        <textarea id="modalContent"
          rows="7" class="modal-textarea"
          placeholder="写下你的问题或观点，可以描述得详细一些…&#10;AI 会自动生成标题并给出回答。"></textarea>
        <div id="modalNodeSuggestions" class="modal-node-suggestions" style="display:none"></div>
        <div class="modal-hint">提交后立即入队，不阻塞你继续提下一个。</div>
      </div>
      <div class="modal-footer">
        <div class="modal-footer-left">
          <button class="btn btn-sm web-search-btn" id="modalWebSearch" title="联网搜索">${icon('globe')} 联网</button>
        </div>
        <div class="modal-footer-right">
          <button class="btn" id="modalCancelBtn">取消</button>
          <button class="btn btn-primary" id="modalSubmitBtn" disabled>${icon('rocket')} 提交</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(el);

  let selectedType = 'question';
  let webSearch = false;
  let ready = { llm: true, tavily: false }; // 乐观默认，异步更新
  let selectedNodeId = null;
  let knowledgeTree = null;

  // ── 检查配置状态 ──
  const submitBtn = document.getElementById('modalSubmitBtn');
  const warningEl = document.getElementById('modalConfigWarning');

  function applyReadyState() {
    if (!ready.llm) {
      submitBtn.disabled = true;
      submitBtn.title = '请先配置大模型';
      warningEl.style.display = 'flex';
      warningEl.innerHTML = `${icon('warn')} 尚未配置大模型，<a class="modal-config-link" id="goToSettings">前往设置</a> 后再提交。`;
      document.getElementById('goToSettings')?.addEventListener('click', () => {
        el.remove();
        window.app?.openSettings?.();
      });
    } else {
      submitBtn.disabled = false;
      submitBtn.title = '';
      warningEl.style.display = 'none';
    }
  }

  getReady().then(r => {
    ready = r;
    applyReadyState();
  }).catch(() => {
    // 网络错误：乐观放行（服务本身有问题时不卡住用户）
    ready = { llm: true, tavily: false };
    applyReadyState();
  });

  el.querySelectorAll('.type-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      selectedType = btn.dataset.type;
      el.querySelectorAll('.type-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('modalContent').placeholder =
        selectedType === 'question'
          ? '写下你的问题，可以描述得详细一些…\nAI 会自动生成标题并给出回答。'
          : '写下你的观点，可以展开说说…\nAI 会自动生成标题并进行分析。';
    });
  });

  const close = () => el.remove();
  document.getElementById('modalCloseBtn').addEventListener('click', close);
  document.getElementById('modalCancelBtn').addEventListener('click', close);
  el.addEventListener('click', e => { if (e.target === el) close(); });

  const webSearchBtn = document.getElementById('modalWebSearch');
  webSearchBtn.addEventListener('click', () => {
    if (!webSearch && !ready.tavily) {
      // 弹出内嵌提示，不 alert
      const hint = document.createElement('div');
      hint.className = 'modal-tavily-hint';
      hint.innerHTML = `${icon('warn')} 联网搜索需要 Tavily API Key，<a class="modal-config-link" id="goToTavily">前往设置</a> 填写。`;
      const existing = el.querySelector('.modal-tavily-hint');
      if (existing) existing.remove();
      webSearchBtn.parentElement.insertAdjacentElement('afterend', hint);
      document.getElementById('goToTavily')?.addEventListener('click', () => {
        el.remove();
        window.app?.openSettings?.();
      });
      setTimeout(() => hint.remove(), 5000);
      return;
    }
    webSearch = !webSearch;
    webSearchBtn.classList.toggle('active', webSearch);
  });

  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
  });

  // ── 知识节点建议（输入时自动推荐）──
  const contentInput = document.getElementById('modalContent');
  let suggestTimer = null;
  const suggestEl = document.getElementById('modalNodeSuggestions');

  function renderNodeSuggestions(nodes) {
    if (!nodes?.length) { suggestEl.style.display = 'none'; return; }
    suggestEl.innerHTML = `
      <div class="node-suggest-label">${icon('tag')} 推荐知识节点（可选）</div>
      <div class="node-suggest-list">
        ${nodes.slice(0, 4).map(n => `
          <button class="node-suggest-item ${n.id === selectedNodeId ? 'selected' : ''}"
            data-node-id="${n.id}">${n.path} <span class="kn-score">${n.score}</span></button>
        `).join('')}
      </div>`;
    suggestEl.style.display = 'block';

    suggestEl.querySelectorAll('.node-suggest-item').forEach(btn => {
      btn.addEventListener('click', () => {
        selectedNodeId = selectedNodeId === btn.dataset.nodeId ? null : btn.dataset.nodeId;
        renderNodeSuggestions(nodes);
      });
    });
  }

  // 简单的客户端关键词匹配（不需要 API，更快）
  function clientSuggestNodes(query) {
    if (!knowledgeTree || !query || query.length < 3) return [];
    const ql = query.toLowerCase();
    const words = ql.split(/\s+/).filter(w => w.length > 1);
    if (!words.length) return [];
    const scored = [];
    function walk(nodes, path = '') {
      for (const n of nodes) {
        let s = 0;
        const t = (n.title || '').toLowerCase();
        const kws = (n.keywords || []).map(k => k.toLowerCase());
        for (const w of words) {
          if (t.includes(w)) s += 3;
          for (const kw of kws) if (kw.includes(w) || w.includes(kw)) s += 2;
        }
        if (ql.includes(t) || t.includes(ql)) s += 5;
        if (s > 0) scored.push({ id: n.id, title: n.title, path: (path ? path + '/' : '') + n.title, score: s });
        walk(n.children || [], path ? path + '/' + n.title : n.title);
      }
    }
    walk(knowledgeTree);
    return scored.sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
  }

  contentInput.addEventListener('input', () => {
    clearTimeout(suggestTimer);
    selectedNodeId = null; // reset on new input
    suggestTimer = setTimeout(() => {
      const val = contentInput.value.trim();
      if (!val || val.length < 3) { suggestEl.style.display = 'none'; return; }
      const suggestions = clientSuggestNodes(val);
      renderNodeSuggestions(suggestions.slice(0, 4));
    }, 500);
  });

  // 预加载知识树
  getKnowledgeTree().then(r => { knowledgeTree = r.tree || []; }).catch(() => {});

  submitBtn.addEventListener('click', async () => {
    const content = document.getElementById('modalContent').value.trim();
    if (!content) {
      document.getElementById('modalContent').focus();
      return;
    }
    submitBtn.disabled = true;
    submitBtn.innerHTML = `${icon('clock')} 提交中...`;
    try {
      await onSubmit('', content, selectedType, webSearch, selectedNodeId);
      close();
    } finally {
      submitBtn.disabled = false;
      submitBtn.innerHTML = `${icon('rocket')} 提交`;
      applyReadyState(); // 如果 LLM 未配置，恢复禁用
    }
  });

  setTimeout(() => document.getElementById('modalContent')?.focus(), 50);
}
