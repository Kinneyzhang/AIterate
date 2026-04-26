// ── store.js ── 全局响应式状态 ───────────────────────────────────────────

import { reactive, computed } from 'vue';

export const store = reactive({
  // sessions
  sessions: [],
  selectedSessionId: null,
  
  // workspace
  workspace: null,       // { session, rounds, take_evaluations, ... }
  currentFeynmanGroupId: null,
  
  // modals
  showNewSession: false,
  showSettings: false,
  showKnowledgeTree: false,
  showCommandCenter: false,
  
  // UI
  theme: localStorage.getItem('aiterate-theme') || 'night',
  notice: { text: '', type: 'info' },
  sidebarExpanded: false,
  loading: false,
  
  // polling
  pollTimer: null,
});

// computed
export const currentSession = computed(() => {
  if (!store.workspace?.session) return null;
  return store.workspace.session;
});

export const currentRounds = computed(() => {
  return store.workspace?.rounds || [];
});

export const feynmanGroup = computed(() => {
  return store.workspace?.current_review_group || [];
});

export const unresolvedGaps = computed(() => {
  return store.workspace?.unresolved_gaps || [];
});

export const reviewReport = computed(() => {
  return store.workspace?.review_report || null;
});

export const knowledgeNode = computed(() => {
  return store.workspace?.knowledge_node || null;
});

// helpers
export function setNotice(text, type = 'info') {
  store.notice = { text, type };
  if (text) setTimeout(() => { store.notice = { text: '', type: 'info' }; }, 5000);
}

export function formatDate(ts) {
  if (!ts) return '';
  const d = new Date(ts);
  if (isNaN(d)) return ts;
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function escapeHtml(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function renderMarkdown(md) {
  if (typeof marked === 'undefined') return escapeHtml(md);
  const raw = marked.parse(String(md || ''));
  if (typeof DOMPurify !== 'undefined') {
    const allowed = ['h1','h2','h3','h4','h5','h6','p','br','hr','pre','blockquote','strong','em','b','i','u','s','del','ins','a','code','img','span','div','ul','ol','li','table','thead','tbody','tfoot','tr','th','td','sup','sub'];
    return DOMPurify.sanitize(raw, { ALLOWED_TAGS: allowed, ALLOWED_ATTR: ['href','title','target','rel','src','alt','width','height','class','id'] });
  }
  // Fail closed: if the sanitizer did not load, never inject raw HTML/AI output.
  return escapeHtml(md).replace(/\n/g, '<br>');
}

const STAGE_META = {
  idle: { label: '未开始', cls: 'stage-idle' },
  preparing: { label: '准备中', cls: 'stage-preparing' },
  learning: { label: '学习中', cls: 'stage-learning' },
  deepening: { label: '深化中', cls: 'stage-deepening' },
  revising: { label: '巩固中', cls: 'stage-revising' },
  feynman: { label: '费曼中', cls: 'stage-feynman' },
  completed: { label: '已完成', cls: 'stage-completed' },
  error: { label: '失败', cls: 'stage-failed' },
};

export function getStageMeta(status) {
  return STAGE_META[status] || { label: '未开始', cls: 'stage-idle' };
}
