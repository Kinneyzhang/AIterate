// ── AppDialog.js ── 应用统一确认弹窗 ─────────────────────────────────────

import { defineComponent, onMounted, onUnmounted } from 'vue';
import { store, closeAppDialog } from '../store.js';

export default defineComponent({
  setup() {
    function approveDialog() { closeAppDialog(true); }
    function cancelDialog() { closeAppDialog(false); }

    function onKeydown(event) {
      if (!store.appDialog.visible) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        cancelDialog();
      }
      if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        approveDialog();
      }
    }

    onMounted(() => document.addEventListener('keydown', onKeydown));
    onUnmounted(() => document.removeEventListener('keydown', onKeydown));

    return { store, approveDialog, cancelDialog };
  },

  template: `
    <div v-if="store.appDialog.visible" class="modal-overlay app-dialog-overlay" @click.self="cancelDialog">
      <section :class="['modal-box', 'app-dialog', 'app-dialog-' + (store.appDialog.tone || 'default')]" role="dialog" aria-modal="true" aria-labelledby="appDialogTitle">
        <header class="modal-header app-dialog-header">
          <div id="appDialogTitle" class="modal-title">{{ store.appDialog.title || '确认操作' }}</div>
          <button type="button" class="modal-close" aria-label="关闭" @click="cancelDialog">+</button>
        </header>
        <div class="modal-body app-dialog-body">
          <p class="app-dialog-message">{{ store.appDialog.message }}</p>
          <p v-if="store.appDialog.details" class="app-dialog-details">{{ store.appDialog.details }}</p>
        </div>
        <footer class="modal-footer app-dialog-footer">
          <button type="button" class="btn btn-ghost" @click="cancelDialog">{{ store.appDialog.cancelText || '取消' }}</button>
          <button type="button" :class="['btn', store.appDialog.tone === 'danger' ? 'btn-danger' : 'btn-primary']" @click="approveDialog">{{ store.appDialog.confirmText || '确定' }}</button>
        </footer>
      </section>
    </div>
  `,
});
