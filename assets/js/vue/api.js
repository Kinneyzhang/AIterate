// ── api.js ── 复用原有 API 层 ────────────────────────────────────────────

const BASE = '';

async function request(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...opts.headers };
  if (window.AITERATE_TOKEN && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(opts.method || 'GET')) {
    headers['X-Admin-Token'] = window.AITERATE_TOKEN;
  }
  const resp = await fetch(BASE + path, { ...opts, headers });
  const raw = await resp.text();
  let data;
  try { data = JSON.parse(raw); } catch { data = { detail: raw }; }
  if (!resp.ok) throw new Error(data.detail || raw);
  return data;
}

export const api = {
  getSessions: () => request('/api/sessions'),
  createSession: (title, content, entryType, webSearch, nodeId) =>
    request('/api/sessions', { method: 'POST', body: JSON.stringify({ title, content, type: entryType, web_search: webSearch, knowledge_node_id: nodeId }) }),
  getWorkspace: (id) => request(`/api/sessions/${id}/workspace`),
  deepenSession: (id, action, text) =>
    request(`/api/sessions/${id}/deepen`, { method: 'POST', body: JSON.stringify({ action, text }) }),
  startFeynman: (id) => request(`/api/sessions/${id}/start-feynman`, { method: 'POST' }),
  completeFeynman: (id, groupId, answers) =>
    request(`/api/sessions/${id}/complete-feynman`, { method: 'POST', body: JSON.stringify({ group_id: groupId, answers }) }),
  getSettings: () => request('/api/settings'),
  saveSettings: (payload) => request('/api/settings', { method: 'PATCH', body: JSON.stringify(payload) }),
  getReady: () => request('/api/ready'),
  getKnowledgeTree: () => request('/api/knowledge-tree'),
  getKnowledgeProgress: () => request('/api/knowledge-tree/progress'),
  getCommandCenter: () => request('/api/command-center'),
  completeReview: (rid) => request(`/api/review/${rid}/complete`, { method: 'POST', body: '{}' }),
  saveDbConfig: (payload) => request('/api/db-config', { method: 'PUT', body: JSON.stringify(payload) }),
};
