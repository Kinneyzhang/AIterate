// ── api.js ───────────────────────────────────────────────────────────────────
// 所有后端 fetch 调用封装

async function request(url, options = {}) {
  const resp = await fetch(url, options);
  if (!resp.ok) {
    const raw = await resp.text();
    let msg;
    try {
      const data = JSON.parse(raw);
      msg = data.detail || JSON.stringify(data);
    } catch {
      msg = raw;
    }
    throw new Error(msg);
  }
  return resp.json();
}

export async function getSessions(limit = 100) {
  return request(`/api/sessions?limit=${limit}`);
}

export async function createSession(title, content, entryType, webSearch = false) {
  return request('/api/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, type: entryType, web_search: webSearch }),
  });
}

export async function getWorkspace(sessionId) {
  return request(`/api/sessions/${sessionId}/workspace`);
}

export async function deepenSession(sessionId, actionType, content) {
  return request(`/api/sessions/${sessionId}/deepen`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action_type: actionType, content }),
  });
}

export async function startFeynmanRequest(sessionId) {
  return request(`/api/sessions/${sessionId}/start-feynman`, { method: 'POST' });
}

export async function completeReview(sessionId, roundId, answers) {
  return request(`/api/sessions/${sessionId}/complete-feynman`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ round_id: roundId, answers }),
  });
}

export async function getSettings() {
  return request('/api/settings');
}

export async function saveSettings(data) {
  return request('/api/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function getReady() {
  return request('/api/ready');
}
