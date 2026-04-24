// ── utils.js ─────────────────────────────────────────────────────────────────
// 纯函数工具：转义、渲染、格式化、阶段元数据

export function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function renderMarkdown(text) {
  return window.marked ? marked.parse(String(text || '')) : escapeHtml(text);
}

export function formatDate(value) {
  if (!value) return '未知时间';
  return String(value).replace('T', ' ').slice(0, 16);
}

export const STAGE_META = {
  processing: { label: '回答中',  cls: 'stage-processing' },
  answered:   { label: '待深化',  cls: 'stage-deepening'  },
  iterating:  { label: '深化中',  cls: 'stage-deepening'  },
  reviewing:  { label: '费曼中',  cls: 'stage-reviewing'  },
  completed:  { label: '已完成',  cls: 'stage-completed'  },
  failed:     { label: '失败',    cls: 'stage-failed'     },
};

export function getStageMeta(status) {
  return STAGE_META[status] || { label: '未开始', cls: 'stage-idle' };
}
