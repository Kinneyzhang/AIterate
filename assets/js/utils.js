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

const DOMPURIFY_ALLOWED = [
  // 块级
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'p', 'br', 'hr', 'pre', 'blockquote',
  // 内联
  'strong', 'em', 'b', 'i', 'u', 's', 'del', 'ins',
  'a', 'code', 'img', 'span', 'div',
  // 列表
  'ul', 'ol', 'li',
  // 表格
  'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td',
  // 上标/下标
  'sup', 'sub',
];

const DOMPURIFY_ATTRS = [
  // 链接
  'href', 'title', 'target', 'rel',
  // 图片
  'src', 'alt', 'width', 'height',
  // 代码高亮标记
  'class',
];

export function renderMarkdown(text) {
  if (!window.marked) return escapeHtml(text);
  const raw = marked.parse(String(text || ''));
  if (!window.DOMPurify) return raw;
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: DOMPURIFY_ALLOWED,
    ALLOWED_ATTR: DOMPURIFY_ATTRS,
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|[^a-z]|[a-z+.-]+(?:[^a-z+.-:]|$))/i,
  });
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
