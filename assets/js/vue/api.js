// ── api.js ── Phase 4.3: Cookie-based auth ─────────────────────────────────

const BASE = '';

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

export const api = {
    // Auth
    login: (token) => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ token }) }),
    logout: () => request('/api/auth/logout', { method: 'POST' }),
    checkAuth: () => request('/api/auth/status'),
    getStats: () => request('/api/stats'),

    // Sessions
  getSessions: () => request('/api/sessions'),
  createSession: (title, content, entryType, webSearch, nodeId) =>
    request('/api/sessions', { method: 'POST', body: JSON.stringify({ title, content, type: entryType, web_search: webSearch, knowledge_node_id: nodeId }) }),
  getWorkspace: (id) => request(`/api/sessions/${id}/workspace`),
  deepenSession: (id, action_type, content) =>
    request(`/api/sessions/${id}/deepen`, { method: 'POST', body: JSON.stringify({ action_type, content }) }),
  startFeynman: (id) => request(`/api/sessions/${id}/start-feynman`, { method: 'POST' }),
  completeFeynman: (id, groupId, answers) =>
    request(`/api/sessions/${id}/complete-feynman`, { method: 'POST', body: JSON.stringify({ group_id: groupId, answers }) }),
  getSettings: () => request('/api/settings'),
  saveSettings: (payload) => request('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) }),
  getReady: () => request('/api/ready'),
  getKnowledgeTree: () => request('/api/knowledge-tree'),
  getKnowledgeProgress: () => request('/api/knowledge-tree/progress'),
  getKnowledgeMastery: () => request('/api/knowledge-tree/mastery'),
  getRecommendedNodes: () => request('/api/knowledge-tree/recommend'),
  getCommandCenter: () => request('/api/command-center'),
  getJobsStatus: () => request('/api/jobs/status'),
  getDbConfig: () => request('/api/db-config'),
  completeReview: (rid) => request(`/api/review/${rid}/complete`, { method: 'POST', body: '{}' }),
  skipReview: (rid) => request(`/api/review/${rid}/skip`, { method: 'POST' }),
  submitReview: (rid, content) => request(`/api/review/${rid}/submit`, { method: 'POST', body: JSON.stringify({ content }) }),
  saveDbConfig: (payload) => request('/api/db-config', { method: 'PUT', body: JSON.stringify(payload) }),
};
