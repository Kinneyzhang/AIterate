// ── CommandCenterModal.js ──────────────────────────────────────────────────

import { defineComponent, ref, onMounted } from 'vue';
import { api } from '../../api.js';
import { icon } from '../../icons.js';
import { setNotice } from '../../store.js';

export default defineComponent({
  emits: ['close', 'select-session'],
  
  setup(props, { emit }) {
    const data = ref({});
    
    onMounted(async () => {
      try { data.value = await api.getCommandCenter(); } catch (err) {
        console.error('command center error', err);
      }
    });
    
    async function completeReview(rid, btn) {
      btn.disabled = true;
      btn.textContent = '…';
      try {
        await api.completeReview(rid);
        btn.textContent = '✓已标记';
        btn.classList.add('cmd-done');
      } catch {
        btn.textContent = '失败';
        btn.disabled = false;
      }
    }
    
    function sessionHtml(s) {
      const title = s.title || '未命名';
      const score = s.score ? ` <span class="cmd-score">${s.score}分</span>` : '';
      const node = s.knowledge_node_id ? ` <span class="cmd-node">${s.knowledge_node_id.split('.').pop()}</span>` : '';
      return `${score}${node}`;
    }
    
    return { data, completeReview, sessionHtml, icon, emit };
  },
  
  template: `
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box command-center-modal" role="dialog" style="max-width:560px; max-height:85vh;">
        <div class="modal-header">
          <div class="modal-title" v-html="icon('target') + ' 指挥中心'"></div>
          <button class="modal-close" @click="$emit('close')">✕</button>
        </div>
        <div class="modal-body cc-body">
          <!-- Feynman pending -->
          <div class="cc-section">
            <div class="cc-section-title" v-html="icon('zap') + ' 待完成费曼'"></div>
            <template v-if="data.feynman_pending?.length">
              <div v-for="s in data.feynman_pending" :key="s.id" class="cmd-item">
                <span v-html="icon('zap')"></span>
                <a class="cmd-link" href="#" @click.prevent="$emit('select-session', s.id); $emit('close')">{{ s.title || '未命名' }}</a>
                <span v-if="s.score" class="cmd-score">{{ s.score }}分</span>
                <span v-if="s.knowledge_node_id" class="cmd-node">{{ s.knowledge_node_id.split('.').pop() }}</span>
              </div>
            </template>
            <div v-else class="cmd-empty">没有未完成的费曼检验 <span v-html="icon('check')"></span></div>
          </div>
          
          <!-- Review due -->
          <div class="cc-section">
            <div class="cc-section-title" v-html="icon('refresh') + ' 今日复习'"></div>
            <template v-if="data.review_due?.length">
              <div v-for="r in data.review_due" :key="r.review_id" class="cmd-item">
                <span v-html="icon('refresh')"></span>
                {{ r.review_round > 0 ? '第'+(r.review_round+1)+'次' : '首次' }}
                <span v-if="r.review_date < new Date().toISOString().split('T')[0]" class="cmd-overdue">逾期</span>
                — <a class="cmd-link" href="#" @click.prevent="$emit('select-session', r.id); $emit('close')">{{ r.title || '未命名' }}</a>
                <span v-if="r.score" class="cmd-score">{{ r.score }}分</span>
                <button class="btn btn-sm cmd-done-btn" @click="completeReview(r.review_id, $event.target)">✓完成</button>
              </div>
            </template>
            <div v-else class="cmd-empty">今天没有到期的复习</div>
          </div>
          
          <!-- Failed -->
          <div class="cc-section">
            <div class="cc-section-title" v-html="icon('xmark') + ' 待修正'"></div>
            <template v-if="data.failed_sessions?.length">
              <div v-for="s in data.failed_sessions" :key="s.id" class="cmd-item">
                <span v-html="icon('xmark')"></span>
                <a class="cmd-link" href="#" @click.prevent="$emit('select-session', s.id); $emit('close')">{{ s.title || '未命名' }}</a>
                <span v-if="s.score" class="cmd-score">{{ s.score }}分</span>
              </div>
            </template>
            <div v-else class="cmd-empty">没有失败的 session <span v-html="icon('check')"></span></div>
          </div>
          
          <!-- Active -->
          <div class="cc-section">
            <div class="cc-section-title" v-html="icon('book') + ' 进行中'"></div>
            <template v-if="data.active_sessions?.length">
              <div v-for="s in data.active_sessions" :key="s.id" class="cmd-item">
                <span v-html="icon('book')"></span>
                <a class="cmd-link" href="#" @click.prevent="$emit('select-session', s.id); $emit('close')">{{ s.title || '未命名' }}</a>
                <span v-if="s.score" class="cmd-score">{{ s.score }}分</span>
              </div>
            </template>
            <div v-else class="cmd-empty">没有进行中的 session</div>
          </div>
        </div>
      </div>
    </div>
  `,
});
