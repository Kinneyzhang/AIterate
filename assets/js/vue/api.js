// ── api.js ── Phase 4.3: Cookie-based auth ─────────────────────────────────

const BASE = '';

const workspaceCache = new Map();
const workspaceInflight = new Map();
let workspaceCacheVersion = 0;
let commandCenterCache = null;
let commandCenterInflight = null;
let knowledgeMasteryCache = null;
let knowledgeMasteryInflight = null;
let derivedCacheVersion = 0;
const STATIC_CACHE_TTL = 120_000;

function now() { return Date.now(); }
function isFresh(entry, ttl = STATIC_CACHE_TTL) {
  return entry && (now() - entry.ts) < ttl;
}

function cacheEntry(data) {
  return { data, ts: now() };
}

function invalidateWorkspace(id) {
  workspaceCacheVersion += 1;
  if (id === undefined || id === null) {
    workspaceCache.clear();
    workspaceInflight.clear();
  } else {
    const key = Number(id);
    workspaceCache.delete(key);
    workspaceInflight.delete(key);
  }
}

function invalidateDerived() {
  derivedCacheVersion += 1;
  commandCenterCache = null;
  commandCenterInflight = null;
  knowledgeMasteryCache = null;
  knowledgeMasteryInflight = null;
}

async function request(path, opts = {}) {
  const headers = { ...opts.headers };
  if (opts.body !== undefined && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }
  if (window.AITERATE_TOKEN && !headers['X-Admin-Token']) {
    headers['X-Admin-Token'] = window.AITERATE_TOKEN;
  }
  let resp;
  try {
    resp = await fetch(BASE + path, { ...opts, headers, credentials: 'same-origin' });
  } catch (err) {
    const e = new Error(`网络请求失败：${err.message || err}`);
    e.cause = err;
    throw e;
  }

  const raw = await resp.text();
  let data = {};
  if (raw) {
    try { data = JSON.parse(raw); } catch { data = { detail: raw }; }
  }
  if (!resp.ok) {
    if (resp.status === 401 && path !== '/api/auth/status' && path !== '/api/auth/login') {
      // Redirect to login on 401
      document.dispatchEvent(new CustomEvent('aiterate:unauthorized'));
    }
    const msg = data.detail || raw || resp.statusText || `HTTP ${resp.status}`;
    const e = new Error(msg);
    e.status = resp.status;
    e.detail = data.detail;
    throw e;
  }
  return data;
}

async function getWorkspaceCached(id, opts = {}) {
  const key = Number(id);
  if (opts.force) invalidateWorkspace(key);
  if (!opts.force && workspaceCache.has(key)) return workspaceCache.get(key).data;
  if (!opts.force && workspaceInflight.has(key)) return workspaceInflight.get(key);
  const version = workspaceCacheVersion;
  const p = request(`/api/sessions/${key}/workspace`)
    .then(data => {
      if (version === workspaceCacheVersion) workspaceCache.set(key, cacheEntry(data));
      return data;
    })
    .finally(() => {
      if (workspaceInflight.get(key) === p) workspaceInflight.delete(key);
    });
  workspaceInflight.set(key, p);
  return p;
}

function prefetchWorkspace(id) {
  const key = Number(id);
  if (!key || workspaceCache.has(key) || workspaceInflight.has(key)) return;
  getWorkspaceCached(key).catch(() => {});
}

function prefetchWorkspaces(ids, limit = 12) {
  const queue = [...new Set((ids || []).map(Number).filter(Boolean))].slice(0, limit);
  let i = 0;
  const pump = () => {
    if (i >= queue.length) return;
    prefetchWorkspace(queue[i++]);
    setTimeout(pump, 60);
  };
  if (window.requestIdleCallback) requestIdleCallback(pump, { timeout: 600 });
  else setTimeout(pump, 120);
}

async function getCommandCenterCached(opts = {}) {
  if (opts.force) invalidateDerived();
  if (!opts.force && isFresh(commandCenterCache)) return commandCenterCache.data;
  if (!opts.force && commandCenterInflight) return commandCenterInflight;
  const version = derivedCacheVersion;
  const p = request('/api/command-center')
    .then(data => {
      if (version === derivedCacheVersion) commandCenterCache = cacheEntry(data);
      return data;
    })
    .finally(() => {
      if (commandCenterInflight === p) commandCenterInflight = null;
    });
  commandCenterInflight = p;
  return commandCenterInflight;
}

function prefetchCommandCenter() {
  if (isFresh(commandCenterCache) || commandCenterInflight) return;
  getCommandCenterCached().catch(() => {});
}

async function getKnowledgeMasteryCached(opts = {}) {
  if (opts.force) invalidateDerived();
  if (!opts.force && isFresh(knowledgeMasteryCache)) return knowledgeMasteryCache.data;
  if (!opts.force && knowledgeMasteryInflight) return knowledgeMasteryInflight;
  const version = derivedCacheVersion;
  const p = request('/api/knowledge-tree/mastery')
    .then(data => {
      if (version === derivedCacheVersion) knowledgeMasteryCache = cacheEntry(data);
      return data;
    })
    .finally(() => {
      if (knowledgeMasteryInflight === p) knowledgeMasteryInflight = null;
    });
  knowledgeMasteryInflight = p;
  return knowledgeMasteryInflight;
}

function prefetchKnowledgeMastery() {
  if (isFresh(knowledgeMasteryCache) || knowledgeMasteryInflight) return;
  getKnowledgeMasteryCached().catch(() => {});
}

export const api = {
    // Auth
    login: (token) => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ token }) }),
    logout: () => request('/api/auth/logout', { method: 'POST' }),
    checkAuth: () => request('/api/auth/status'),
    getStats: () => request('/api/stats'),

    // Sessions
  getSessions: () => request('/api/sessions'),
  createSession: async (title, content, entryType, webSearch, nodeId) => {
    invalidateWorkspace();
    invalidateDerived();
    return request('/api/sessions', { method: 'POST', body: JSON.stringify({ title, content, type: entryType, web_search: webSearch, knowledge_node_id: nodeId }) });
  },
  renameSession: async (id, title) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/title`, { method: 'PATCH', body: JSON.stringify({ title }) });
  },
  pinSession: async (id, pinned) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/pin`, { method: 'POST', body: JSON.stringify({ pinned }) });
  },
  deleteSession: async (id) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}`, { method: 'DELETE' });
  },
  getSessionShare: (id) => request(`/api/sessions/${id}/share`),
  getWorkspace: getWorkspaceCached,
  prefetchWorkspace,
  prefetchWorkspaces,
  invalidateWorkspace,
  deepenSession: async (id, action_type, content) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/deepen`, { method: 'POST', body: JSON.stringify({ action_type, content }) });
  },
  startFeynman: async (id) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/start-feynman`, { method: 'POST' });
  },
  completeFeynman: async (id, groupId, answers) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/complete-feynman`, { method: 'POST', body: JSON.stringify({ group_id: groupId, answers }) });
  },
  completeSession: async (id) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/complete`, { method: 'POST' });
  },
  regenerateAnswer: async (id) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/regenerate-answer`, { method: 'POST' });
  },
  regeneratePress: async (id, roundId) => {
    invalidateWorkspace(id);
    return request(`/api/sessions/${id}/regenerate-press`, { method: 'POST', body: JSON.stringify({ round_id: roundId }) });
  },
  regenerateFeynman: async (id) => {
    invalidateWorkspace(id);
    invalidateDerived();
    return request(`/api/sessions/${id}/regenerate-feynman`, { method: 'POST' });
  },
  getSettings: () => request('/api/settings'),
  saveSettings: (payload) => request('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) }),
  getReady: () => request('/api/ready'),
  getKnowledgeTree: () => request('/api/knowledge-tree'),
  getKnowledgeProgress: () => request('/api/knowledge-tree/progress'),
  getKnowledgeMastery: getKnowledgeMasteryCached,
  prefetchKnowledgeMastery,
  getRecommendedNodes: () => request('/api/knowledge-tree/recommend'),
  getCommandCenter: getCommandCenterCached,
  prefetchCommandCenter,
  getJobsStatus: () => request('/api/jobs/status'),

  // Inbox
  getInboxItems: (limit = 50) => request(`/api/inbox?limit=${encodeURIComponent(limit)}`),
  extractInboxUrl: (url) => request('/api/inbox/extract-url', { method: 'POST', body: JSON.stringify({ url }) }),
  createInboxItem: async (content, sourceType = 'text') => {
    invalidateDerived();
    return request('/api/inbox', { method: 'POST', body: JSON.stringify({ content, source_type: sourceType }) });
  },
  getInboxItem: (id) => request(`/api/inbox/${id}`),
  regenerateInboxQuestions: (id, direction = null) => request(`/api/inbox/${id}/regenerate`, {
    method: 'POST',
    body: JSON.stringify({ direction }),
  }),
  generateInboxQuestions: (id) => request(`/api/inbox/${id}/generate`, { method: 'POST' }),
  archiveInboxItem: (id) => request(`/api/inbox/${id}/archive`, { method: 'POST' }),
  deleteInboxItem: (id) => request(`/api/inbox/${id}`, { method: 'DELETE' }),
  clearInboxHistory: () => request('/api/inbox/history', { method: 'DELETE' }),
  selectInboxQuestion: async (id, payload = {}) => {
    invalidateWorkspace();
    invalidateDerived();
    return request(`/api/inbox/questions/${id}/select`, { method: 'POST', body: JSON.stringify(payload) });
  },
  ignoreInboxQuestion: (id) => request(`/api/inbox/questions/${id}/ignore`, { method: 'POST' }),

  // Recommendations
  getInboxRecommendations: () => request('/api/inbox/recommendations'),
  refreshInboxRecommendations: () => request('/api/inbox/recommendations/refresh', { method: 'POST' }),
  selectInboxRecommendation: async (id, payload = {}) => {
    invalidateWorkspace();
    invalidateDerived();
    return request(`/api/inbox/recommendations/${id}/select`, { method: 'POST', body: JSON.stringify(payload) });
  },
  ignoreInboxRecommendation: (id) => request(`/api/inbox/recommendations/${id}/ignore`, { method: 'POST' }),

  getDbConfig: () => request('/api/db-config'),
  completeReview: async (rid) => {
    invalidateWorkspace();
    invalidateDerived();
    return request(`/api/review/${rid}/complete`, { method: 'POST', body: '{}' });
  },
  skipReview: async (rid) => {
    invalidateWorkspace();
    invalidateDerived();
    return request(`/api/review/${rid}/skip`, { method: 'POST' });
  },
  submitReview: async (rid, content) => {
    invalidateWorkspace();
    invalidateDerived();
    return request(`/api/review/${rid}/submit`, { method: 'POST', body: JSON.stringify({ content }) });
  },
  saveDbConfig: (payload) => request('/api/db-config', { method: 'PUT', body: JSON.stringify(payload) }),
  // #1: knowledge node auto-suggest
  suggestKnowledgeNodes: (sid) => request(`/api/sessions/${sid}/suggest-knowledge-nodes`, { method: 'POST' }),
  ignoreKnowledgeNodeSuggestion: async (sid) => {
    invalidateWorkspace(sid);
    return request(`/api/sessions/${sid}/knowledge-node-suggestion/ignore`, { method: 'POST' });
  },
  bindKnowledgeNode: async (sid, nodeId) => {
    invalidateWorkspace(sid);
    return request(`/api/sessions/${sid}/knowledge-node`, { method: 'PATCH', body: JSON.stringify({ knowledge_node_id: nodeId }) });
  },
};
