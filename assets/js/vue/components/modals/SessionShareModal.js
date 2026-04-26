import { defineComponent, ref, onMounted, nextTick } from 'vue';
import { api } from '../../api.js';
import { escapeHtml, renderMarkdown, formatDate, setNotice } from '../../store.js';

export default defineComponent({
  props: { sessionId: { type: Number, required: true } },
  emits: ['close'],

  setup(props) {
    const loading = ref(true);
    const data = ref(null);
    const error = ref('');

    async function load() {
      loading.value = true;
      error.value = '';
      try {
        data.value = await api.getSessionShare(props.sessionId);
        await nextTick();
        if (window.hljs) requestAnimationFrame(() => hljs.highlightAll());
      } catch (err) {
        error.value = err.message || String(err);
      } finally {
        loading.value = false;
      }
    }

    function roundLabel(type) {
      return type === 'take' ? '学习理解' : '深化追问';
    }

    function scoreText(score) {
      return score === null || score === undefined ? '' : `${score}/100`;
    }

    async function copyLink() {
      const url = `${location.origin}${location.pathname}${location.search}#/session/${props.sessionId}/learn`;
      try {
        await navigator.clipboard.writeText(url);
        setNotice('已复制 session 链接。');
      } catch (err) {
        setNotice(`复制失败：${err.message || err}`, 'error');
      }
    }

    onMounted(load);

    return { loading, data, error, load, copyLink, escapeHtml, renderMarkdown, formatDate, roundLabel, scoreText };
  },

  template: `
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box session-share-page">
        <div class="modal-header">
          <div>
            <h2>分享学习汇总</h2>
            <div v-if="data?.session" class="share-subtitle">
              {{ data.session.title || '未命名' }} · {{ formatDate(data.generated_at) }}
            </div>
          </div>
          <button class="modal-close" @click="$emit('close')" title="关闭">×</button>
        </div>

        <div v-if="loading" class="session-share-body share-loading">生成汇总中…</div>
        <div v-else-if="error" class="session-share-body">
          <div class="notice-error share-error">{{ error }}</div>
          <button class="btn" @click="load">重试</button>
        </div>

        <div v-else-if="data" class="session-share-body">
          <section class="share-section">
            <div class="share-section-head">
              <span class="share-section-index">01</span>
              <h3>学习</h3>
            </div>
            <div class="share-question" v-if="data.learn?.question">{{ data.learn.question }}</div>
            <div class="content-block md-body" v-html="renderMarkdown(data.learn?.material || '暂无学习材料。')"></div>
          </section>

          <section class="share-section">
            <div class="share-section-head">
              <span class="share-section-index">02</span>
              <h3>深化</h3>
            </div>
            <div v-if="!data.deepen_rounds?.length" class="share-empty">暂无深化问答。</div>
            <div v-for="round in data.deepen_rounds" :key="round.id" class="share-qa-card">
              <div class="share-qa-meta">
                <span class="round-label">{{ roundLabel(round.type) }}</span>
                <span v-if="scoreText(round.score)" class="share-score">{{ scoreText(round.score) }}</span>
              </div>
              <div class="share-user-text">{{ round.user }}</div>
              <div class="round-ai md-body">
                <div class="ps-label">AI 回答 / 评价</div>
                <div v-html="renderMarkdown(round.ai || '')"></div>
              </div>
            </div>
          </section>

          <section class="share-section">
            <div class="share-section-head">
              <span class="share-section-index">03</span>
              <h3>费曼</h3>
            </div>
            <div v-if="!data.feynman_groups?.length" class="share-empty">暂无费曼检验记录。</div>
            <div v-for="group in data.feynman_groups" :key="group.group_id" class="share-feynman-group">
              <div class="share-group-title">
                第 {{ group.group_id }} 组
                <span v-if="group.average_score !== null && group.average_score !== undefined" class="share-score">平均 {{ group.average_score }}/100</span>
              </div>
              <div v-for="(item, idx) in group.items" :key="item.id" class="share-feynman-item">
                <div class="share-feynman-q">Q{{ idx + 1 }}. {{ item.question }}</div>
                <div class="share-feynman-a">{{ item.answer || '未作答' }}</div>
                <div v-if="item.comment" class="share-feynman-comment">AI 评价：{{ item.comment }}</div>
              </div>
            </div>
          </section>

          <section v-if="data.review_report" class="share-section">
            <div class="share-section-head">
              <span class="share-section-index">04</span>
              <h3>最终复盘</h3>
            </div>
            <div class="share-report-grid">
              <div><span>最终得分</span><strong>{{ data.review_report.final_score ?? data.session.score ?? '-' }}</strong></div>
              <div><span>通过状态</span><strong>{{ data.review_report.passed ? '已通过' : '待巩固' }}</strong></div>
              <div><span>掌握等级</span><strong>{{ data.review_report.mastery_level || '-' }}</strong></div>
            </div>
            <div v-if="data.review_report.final_summary" class="content-block md-body" v-html="renderMarkdown(data.review_report.final_summary)"></div>
          </section>
        </div>

        <div class="modal-footer">
          <button class="btn" @click="copyLink">复制链接</button>
          <button class="btn btn-primary" @click="$emit('close')">完成</button>
        </div>
      </div>
    </div>
  `,
});
