// ── api.js ── Phase 4.3: Cookie-based auth ─────────────────────────────────

const BASE = '';

async function request(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...opts.headers };
  // Cookie handles auth now; header fallback removed
  const resp = await fetch(BASE + path, { ...opts, headers });
  const raw = await resp.text();
  let data;
  try { data = JSON.parse(raw); } catch { data = { detail: raw }; }
  if (!resp.ok) {
    if (resp.status === 401 && path !== '/api/auth/status' && path !== '/api/auth/login') {
      // Redirect to login on 401
      document.dispatchEvent(new CustomEvent('aiterate:unauthorized'));
    }
    throw new Error(data.detail || raw);
  }
  return data;
}

export const api = {
  // Auth
  login: (token) => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ token }) }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  checkAuth: () => request('/api/auth/status'),

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
  completeReview: (rid) => request(`/api/review/${rid}/complete`, { method: 'POST', body: '{}' }),
  skipReview: (rid) => request(`/api/review/${rid}/skip`, { method: 'POST' }),
  submitReview: (rid, content) => request(`/api/review/${rid}/submit`, { method: 'POST', body: JSON.stringify({ content }) }),
  saveDbConfig: (payload) => request('/api/db-config', { method: 'PUT', body: JSON.stringify(payload) }),
};
