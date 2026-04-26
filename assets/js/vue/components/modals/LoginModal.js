// ── LoginModal.js ── Phase 4.3: Login overlay ──────────────────────────────

import { defineComponent, ref } from 'vue';
import { api } from '../../api.js';

export default defineComponent({
  emits: ['authenticated'],

  setup(props, { emit }) {
    const token = ref(window.AITERATE_TOKEN || '');
    const submitting = ref(false);
    const error = ref('');

    async function login() {
      const t = token.value.trim();
      if (!t) { error.value = '请输入 Token'; return; }
      submitting.value = true;
      error.value = '';
      try {
        await api.login(t);
        emit('authenticated');
      } catch (err) {
        error.value = err.message || '登录失败';
      } finally {
        submitting.value = false;
      }
    }

    function onKeydown(e) {
      if (e.key === 'Enter') login();
    }

    return { token, submitting, error, login, onKeydown };
  },

  template: `
    <div class="login-overlay">
      <div class="login-card">
        <div class="login-logo">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 18h6"/><path d="M10 22h4"/>
            <path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/>
          </svg>
        </div>
        <h2 class="login-title">AIIterate</h2>
        <p class="login-desc">个人学习操作系统</p>
        <div class="login-field">
          <label class="login-label">Admin Token</label>
          <input
            class="login-input"
            type="password"
            v-model="token"
            placeholder="输入 Admin Token"
            @keydown="onKeydown"
            autofocus
          />
        </div>
        <div v-if="error" class="login-error">{{ error }}</div>
        <button
          class="btn btn-primary btn-block"
          :disabled="submitting"
          @click="login"
        >{{ submitting ? '登录中…' : '登录' }}</button>
      </div>
    </div>
  `,
});
