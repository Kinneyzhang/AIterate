// ── store.js ── 全局响应式状态 ───────────────────────────────────────────

import { reactive, computed } from 'vue';

export const store = reactive({
  // sessions
  sessions: [],
  stats: { total_sessions: 0, completed_sessions: 0, active_sessions: 0 },
  inboxItems: [],
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
  deepAutoAction: null,  // 'take' | 'press' — set by ContextRail to auto-open deepen modal
  appDialog: {
    visible: false,
    title: '',
    message: '',
    details: '',
    confirmText: '确定',
    cancelText: '取消',
    tone: 'default',
    resolve: null,
  },
  sidebarExpanded: false,
  loading: false,
  
  // polling / live refresh
  pollTimer: null,
  runtimeTick: 0,
  prefillQuestion: '',   // #5: gap → 追问 预填内容
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
let noticeTimer = null;

export function setNotice(text, type = 'info') {
  if (noticeTimer) {
    clearTimeout(noticeTimer);
    noticeTimer = null;
  }
  store.notice = { text, type };
  if (text) {
    noticeTimer = setTimeout(() => {
      store.notice = { text: '', type: 'info' };
      noticeTimer = null;
    }, 5000);
  }
}

const DEFAULT_DIALOG = {
  visible: false,
  title: '',
  message: '',
  details: '',
  confirmText: '确定',
  cancelText: '取消',
  tone: 'default',
  resolve: null,
};

export function askConfirm(options = {}) {
  const opts = typeof options === 'string' ? { message: options } : options;
  if (store.appDialog?.resolve) store.appDialog.resolve(false);
  return new Promise(resolve => {
    store.appDialog = {
      ...DEFAULT_DIALOG,
      visible: true,
      title: opts.title || '确认操作',
      message: opts.message || '',
      details: opts.details || '',
      confirmText: opts.confirmText || '确定',
      cancelText: opts.cancelText || '取消',
      tone: opts.tone || 'default',
      resolve,
    };
  });
}

export function closeAppDialog(confirmed = false) {
  const resolver = store.appDialog?.resolve;
  store.appDialog = { ...DEFAULT_DIALOG };
  if (resolver) resolver(Boolean(confirmed));
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
