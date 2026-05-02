// ── InboxComposer.js ── 左侧常驻收集箱输入 ───────────────────────────────

import { defineComponent, ref } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { setNotice } from '../store.js';

export default defineComponent({
  emits: ['created'],

  setup(props, { emit }) {
    const router = useRouter();
    const content = ref('');
    const submitting = ref(false);

    async function submit() {
      const text = content.value.trim();
      if (!text || submitting.value) return;
      submitting.value = true;
      try {
        const created = await api.createInboxItem(text, 'text');
        content.value = '';
        emit('created', created);
        setNotice('已保存。');
      } catch (err) {
        setNotice(`收集失败：${err.message}`, 'error');
      } finally {
        submitting.value = false;
      }
    }

    function handleKeydown(event) {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        submit();
      }
    }

    return { content, submitting, submit, handleKeydown };
  },

  template: `
    <section class="inbox-composer">
      <div class="inbox-composer-head">
        <span class="inbox-label">收集箱</span>
        <span class="inbox-shortcut">⌘/Ctrl Enter</span>
      </div>
      <textarea
        class="inbox-input"
        v-model="content"
        rows="1"
        placeholder="记录一个词、想法、摘录..."
        :disabled="submitting"
        @keydown="handleKeydown"></textarea>
      <div class="inbox-actions-row">
        <span class="inbox-hint">纯记录，不自动生成问题</span>
        <button type="button" class="btn btn-sm inbox-submit" :disabled="!content.trim() || submitting" @click="submit">
          {{ submitting ? '保存中' : '收集' }}
        </button>
      </div>
    </section>
  `,
});
