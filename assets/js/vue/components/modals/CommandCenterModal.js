// ── CommandCenterModal.js ──────────────────────────────────────────────────

import { defineComponent, ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../../api.js?v=027';
import { icon } from '../../icons.js?v=027';
import { setNotice } from '../../store.js?v=027';

export default defineComponent({
  emits: ['close'],
  
  setup(props, { emit }) {
    const router = useRouter();
    const data = ref({});
    const health = ref({});
    
    onMounted(async () => {
      try {
        data.value = await api.getCommandCenter();
        health.value = data.value.health || {};
      } catch (err) {
        console.error('command center error', err);
      }
    });
    
    async function completeReview(rid, btn) {
      btn.disabled = true;
      btn.textContent = '…';
      try {
        await api.completeReview(rid);
        btn.textContent = '✓';
        btn.classList.add('cmd-done');
      } catch {
        btn.textContent = '失败';
        btn.disabled = false;
      }
    }
    
    function gotoSession(id, panel) {
      const name = panel === 'review' ? 'session-review'
                 : panel === 'deepen' ? 'session-deepen'
                 : 'session-learn';
      router.push({ name, params: { id } });
    }

    const STATUS_LABEL = {
      preparing:  { text: '准备中', cls: 'stage-preparing' },
      learning:   { text: '学习中', cls: 'stage-learning'  },
      deepening:  { text: '深化中', cls: 'stage-deepening' },
      revising:   { text: '巩固中', cls: 'stage-revising'  },
      feynman:    { text: '费曼中', cls: 'stage-feynman'   },
    };
    function statusLabel(status) { return STATUS_LABEL[status] || { text: status, cls: '' }; }
    const today = new Date().toISOString().split('T')[0];

    return { data, health, completeReview, icon, emit, gotoSession, statusLabel, today };
  },
  
  template: `
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box command-center-modal" role="dialog" style="max-width:560px; max-height:85vh;">
        <div class="modal-header">
          <div class="modal-title" v-html="icon('target') + ' 指挥中心'"></div>
          <button class="modal-close" @click="$emit('close')">✕</button>
        </div>
        <div class="modal-body cc-body">

          <!-- 🔥 必须做：逾期复习 + 待费曼 -->
          <div class="cc-section">
            <div class="cc-section-title cc-urgent" v-html="icon('zap') + ' 必须做'"></div>
            <template v-if="(data.feynman_pending?.length || 0) + (data.review_due?.filter(r => r.review_date < today).length || 0) > 0">
              <div v-for="r in data.review_due?.filter(r => r.review_date < today)" :key="'urgent-'+r.review_id" class="cmd-item cmd-item-urgent">
                <span class="cmd-badge cmd-badge-overdue">逾期复习</span>
                <a class="cmd-link" href="#" @click.prevent="gotoSession(r.session_id, 'learn')">{{ r.title || '未命名' }}</a>
                <span v-if="r.score" class="cmd-score">{{ r.score }}分</span>
                <button class="btn btn-sm cmd-done-btn" @click="completeReview(r.review_id, $event.target)">✓完成</button>
              </div>
              <div v-for="s in data.feynman_pending" :key="'feyn-'+s.id" class="cmd-item cmd-item-urgent">
                <span class="cmd-badge cmd-badge-feynman">待费曼</span>
                <a class="cmd-link" href="#" @click.prevent="gotoSession(s.id, 'review')">{{ s.title || '未命名' }}</a>
                <span v-if="s.score" class="cmd-score">{{ s.score }}分</span>
              </div>
            </template>
            <div v-else class="cmd-empty">全部完成 <span v-html="icon('check')"></span></div>
          </div>

          <!-- 📖 推进中：活跃 session + 今日到期复习 -->
          <div class="cc-section">
            <div class="cc-section-title" v-html="icon('book') + ' 推进中'"></div>
            <template v-if="(data.active_sessions?.length || 0) + (data.review_due?.filter(r => r.review_date >= today).length || 0) > 0">
              <div v-for="r in data.review_due?.filter(r => r.review_date >= today)" :key="'today-'+r.review_id" class="cmd-item">
                <span class="cmd-badge cmd-badge-review">{{ r.review_round > 0 ? '第'+(r.review_round+1)+'轮' : '复习' }}</span>
                <a class="cmd-link" href="#" @click.prevent="gotoSession(r.session_id, 'learn')">{{ r.title || '未命名' }}</a>
                <span v-if="r.score" class="cmd-score">{{ r.score }}分</span>
                <button class="btn btn-sm cmd-done-btn" @click="completeReview(r.review_id, $event.target)">✓完成</button>
              </div>
              <div v-for="s in data.active_sessions" :key="'active-'+s.id" class="cmd-item">
                <span :class="['cmd-badge-stage', statusLabel(s.status).cls]">{{ statusLabel(s.status).text }}</span>
                <a class="cmd-link" href="#" @click.prevent="gotoSession(s.id, s.status === 'deepening' || s.status === 'revising' ? 'deepen' : 'learn')">{{ s.title || '未命名' }}</a>
                <span v-if="s.score" class="cmd-score">{{ s.score }}分</span>
              </div>
            </template>
            <div v-else class="cmd-empty">暂无进行中的任务</div>
          </div>

          <!-- 📅 未来复习 -->
          <div class="cc-section">
            <div class="cc-section-title" v-html="icon('refresh') + ' 未来 7 天复习'"></div>
            <template v-if="data.upcoming_reviews?.length">
              <div v-for="r in data.upcoming_reviews" :key="'up-'+r.review_id" class="cmd-item">
                <span class="cmd-badge cmd-badge-review">{{ r.review_date }}</span>
                <a class="cmd-link" href="#" @click.prevent="gotoSession(r.session_id, 'learn')">{{ r.title || '未命名' }}</a>
                <span class="cmd-score" style="opacity:0.7">{{ r.review_round > 0 ? 'R'+(r.review_round+1) : '' }}</span>
              </div>
            </template>
            <div v-else class="cmd-empty">未来 7 天无复习计划</div>
          </div>

          <!-- 🩺 系统健康 -->
          <div class="cc-section" style="font-size:12px; opacity:0.85; border-top:1px solid var(--border); padding-top:10px;">
            <div class="cc-section-title" v-html="icon('gear') + ' 系统健康'"></div>
            <div style="display:flex; flex-wrap:wrap; gap:8px 16px; padding:4px 0;">
              <span v-if="health.stale_preparing > 0" style="color:var(--warn)">⏳ {{ health.stale_preparing }} 个 stuck</span>
              <span v-if="health.error_sessions > 0" style="color:var(--bad)">❌ {{ health.error_sessions }} 个报错</span>
              <span v-if="health.parse_failures > 0" style="color:var(--warn)">⚠ {{ health.parse_failures }} 次解析失败</span>
              <span v-if="health.no_knowledge_node > 0">{{ health.no_knowledge_node }} 个未绑定知识节点</span>
              <span v-if="health.low_score > 0">{{ health.low_score }} 个低分完成</span>
              <span v-if="health.stale_preparing + health.error_sessions + health.parse_failures === 0" style="color:var(--good)" v-html="icon('check') + ' 一切正常'"></span>
            </div>
          </div>

        </div>
      </div>
    </div>
  `,
});
