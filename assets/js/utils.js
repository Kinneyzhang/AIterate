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
  preparing:  { label: '准备中',  cls: 'stage-preparing'  },
  learning:   { label: '学习中',  cls: 'stage-learning'   },
  deepening:  { label: '深化中',  cls: 'stage-deepening'  },
  revising:   { label: '巩固中',  cls: 'stage-revising'   },
  feynman:    { label: '费曼中',  cls: 'stage-feynman'    },
  completed:  { label: '已完成',  cls: 'stage-completed'  },
  error:      { label: '失败',    cls: 'stage-failed'     },
};

export function getStageMeta(status) {
  return STAGE_META[status] || { label: '未开始', cls: 'stage-idle' };
}
