// ── HomeDashboard.js ── 日拱一卒首页 ─────────────────────────────────────

import { defineComponent, ref, onMounted, watch } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { icon } from '../icons.js';
import { store, setNotice } from '../store.js';

export default defineComponent({
  setup() {
    const router = useRouter();
    const data = ref({});
    const health = ref({
      stale_preparing: 0,
      error_sessions: 0,
      parse_failures: 0,
      no_knowledge_node: 0,
      low_score: 0,
    });
    const loading = ref(false);
    const ready = ref(false);
    const error = ref('');
    const activeContext = ref({ brief: null, entries: [], threads: [], agents: [] });
    const activeQuery = ref('');
    const activeSynthesis = ref(null);
    const activeSynthesisLoading = ref(false);

    async function loadDashboard(force = false, showLoading = false) {
      let loadingTimer = null;
      if (showLoading) loadingTimer = setTimeout(() => { loading.value = true; }, 120);
      try {
        const [commandCenter, brief, entries, threads, agents] = await Promise.all([
          api.getCommandCenter(force ? { force: true } : {}),
          api.getLearningBrief('daily').catch(() => null),
          api.getEntries({ limit: 20 }).catch(() => []),
          api.getThreads(20).catch(() => []),
          api.getLearningAgents().catch(() => []),
        ]);
        data.value = commandCenter;
        activeContext.value = { brief, entries: entries || [], threads: threads || [], agents: agents || [] };
        health.value = data.value.health || {};
        ready.value = true;
        error.value = '';
      } catch (err) {
        console.error('home dashboard error', err);
        error.value = err.message || '日拱一卒加载失败';
        setNotice(`日拱一卒加载失败：${error.value}`, 'error');
      } finally {
        if (loadingTimer) clearTimeout(loadingTimer);
        loading.value = false;
      }
    }

    onMounted(() => loadDashboard(false, true));

    watch(() => store.runtimeTick, tick => {
      if (tick > 0) loadDashboard(true, false);
    });

    function gotoSession(id, panel) {
      const name = panel === 'review' ? 'session-review'
                 : panel === 'deepen' ? 'session-deepen'
                 : 'session-learn';
      router.push({ name, params: { id } });
    }

    function openFocus(item) {
      if (item?.type === 'session' && item.id) gotoSession(item.id, 'learn');
      if (item?.type === 'gap' && item.provenance?.[0]?.id) {
        const gap = item.provenance[0];
        if (gap.session_id) gotoSession(gap.session_id, 'deepen');
      }
    }

    async function runActiveSynthesis() {
      const query = activeQuery.value.trim();
      if (!query) return;
      activeSynthesisLoading.value = true;
      activeSynthesis.value = null;
      try {
        activeSynthesis.value = await api.synthesizePersonalUnderstanding(query);
      } catch (err) {
        setNotice(`主动查询失败：${err.message}`, 'error');
      } finally {
        activeSynthesisLoading.value = false;
      }
    }

    // #3: flashcard quick review
    const flashcard = ref(null);  // { review_id, session_id, title }
    const fcAnswer = ref('');
    const fcSubmitting = ref(false);
    const fcDone = ref(null);     // { score, feedback }

    function openFlashcard(review) {
      flashcard.value = { review_id: review.review_id, session_id: review.session_id, title: review.title };
      fcAnswer.value = '';
      fcDone.value = null;
    }

    function closeFlashcard() { flashcard.value = null; fcAnswer.value = ''; fcDone.value = null; }

    async function submitFlashcard() {
      if (!fcAnswer.value.trim() || !flashcard.value) return;
      fcSubmitting.value = true;
      try {
        const result = await api.submitReview(flashcard.value.review_id, fcAnswer.value.trim());
        fcDone.value = { score: result.score, feedback: result.feedback };
      } catch (err) {
        setNotice(`复习提交失败：${err.message}`, 'error');
      } finally {
        fcSubmitting.value = false;
      }
    }

    const STATUS_LABEL = {
      preparing:  { text: '准备中', cls: 'stage-preparing' },
      learning:   { text: '学习中', cls: 'stage-learning'  },
      deepening:  { text: '深化中', cls: 'stage-deepening' },
      revising:   { text: '巩固中', cls: 'stage-revising'  },
      feynman:    { text: '费曼中', cls: 'stage-feynman'   },
    };
    function statusLabel(status) { return STATUS_LABEL[status] || { text: status, cls: '' }; }

    const SEVERITY_LABEL = {
      high: '高',
      medium: '中',
      low: '低',
      critical: '严重',
    };
    function severityLabel(severity) {
      return SEVERITY_LABEL[severity] || SEVERITY_LABEL[String(severity || '').toLowerCase()] || '中';
    }

    function localDateKey(d = new Date()) {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    }
    const today = localDateKey();

    return {
      data, health, loading, ready, error, icon, gotoSession,
      activeContext, activeQuery, activeSynthesis, activeSynthesisLoading, openFocus, runActiveSynthesis,
      flashcard, fcAnswer, fcSubmitting, fcDone, openFlashcard, closeFlashcard, submitFlashcard,
      statusLabel, severityLabel, today,
    };
  },

  template: `
    <div class="home-dashboard panel-content">
      <div class="home-hero">
        <div>
          <div class="home-kicker">AITERATE</div>
          <h1>日拱一卒</h1>
          <p>每天推进一点，把问题走成真正掌握的知识。</p>
        </div>
      </div>

      <div v-if="!ready && loading" class="cmd-empty home-loading">加载中…</div>
      <div v-else-if="error" class="cmd-empty notice-error">加载失败：{{ error }}</div>

      <template v-else-if="ready">
        <section class="home-section home-active-context">
          <div class="home-section-title" v-html="icon('bulb') + ' 主动学习上下文'"></div>
          <div class="cmd-item">
            <span class="cmd-badge cmd-badge-review">Entries</span>
            <span class="cmd-link">{{ activeContext.entries.length }} 条素材已成为长期学习资产</span>
          </div>
          <div class="cmd-item">
            <span class="cmd-badge cmd-badge-review">Threads</span>
            <span class="cmd-link">{{ activeContext.threads.length }} 个持续主题</span>
          </div>
          <div class="cmd-item">
            <span class="cmd-badge cmd-badge-review">Agents</span>
            <span class="cmd-link">{{ activeContext.agents.filter(a => a.enabled).length }} 个学习协作者待命</span>
          </div>
          <template v-if="activeContext.brief?.suggested_focus?.length">
            <div class="home-section-title small" v-html="icon('zap') + ' 今日主动简报'"></div>
            <button v-for="item in activeContext.brief.suggested_focus.slice(0, 3)" :key="'focus-'+item.type+'-'+item.id" type="button" class="cmd-item btn" @click="openFocus(item)">
              <span class="cmd-badge cmd-badge-gap">{{ item.type }}</span>
              <span class="cmd-link">{{ item.title }}</span>
              <span class="cmd-score">可追溯</span>
            </button>
          </template>
          <div class="cmd-item home-synthesis-row">
            <span class="cmd-badge cmd-badge-feynman">我怎么看 X</span>
            <input type="text" v-model="activeQuery" placeholder="输入概念，比如 MVCC" @keydown.enter="runActiveSynthesis" />
            <button type="button" class="btn btn-primary btn-sm" :disabled="activeSynthesisLoading || !activeQuery.trim()" @click="runActiveSynthesis">
              {{ activeSynthesisLoading ? '查询中…' : '综合' }}
            </button>
          </div>
          <div v-if="activeSynthesis" class="cmd-empty">{{ activeSynthesis.answer }}</div>
        </section>

        <section class="home-section">
          <div class="home-section-title home-urgent" v-html="icon('zap') + ' 先推进这个'"></div>
          <template v-if="(data.feynman_pending?.length || 0) + (data.review_due?.filter(r => r.review_date < today).length || 0) > 0">
            <div v-for="r in data.review_due?.filter(r => r.review_date < today)" :key="'urgent-'+r.review_id" class="cmd-item cmd-item-urgent">
              <span class="cmd-badge cmd-badge-overdue">逾期复习</span>
              <a class="cmd-link" href="#" @click.prevent="gotoSession(r.session_id, 'review')">{{ r.title || '未命名' }}</a>
              <span v-if="r.display_score > 0" class="cmd-score">{{ r.display_score }}分</span>
              <a class="cmd-link" href="#" @click.prevent="openFlashcard(r)">快速复习 →</a>
            </div>
            <div v-for="s in data.feynman_pending" :key="'feyn-'+s.id" class="cmd-item cmd-item-urgent">
              <span class="cmd-badge cmd-badge-feynman">待费曼</span>
              <a class="cmd-link" href="#" @click.prevent="gotoSession(s.id, 'review')">{{ s.title || '未命名' }}</a>
              <span v-if="s.score" class="cmd-score">{{ s.score }}分</span>
            </div>
          </template>
          <div v-else class="cmd-empty">今天没有卡住的闭环 <span v-html="icon('check')"></span></div>
        </section>

        <section class="home-section">
          <div class="home-section-title" v-html="icon('book') + ' 正在推进'"></div>
          <template v-if="(data.active_sessions?.length || 0) + (data.review_due?.filter(r => r.review_date >= today).length || 0) > 0">
            <div v-for="r in data.review_due?.filter(r => r.review_date >= today)" :key="'today-'+r.review_id" class="cmd-item">
              <span class="cmd-badge cmd-badge-review">{{ r.review_round > 0 ? '第'+(r.review_round+1)+'轮' : '复习' }}</span>
              <a class="cmd-link" href="#" @click.prevent="gotoSession(r.session_id, 'review')">{{ r.title || '未命名' }}</a>
              <span v-if="r.display_score > 0" class="cmd-score">{{ r.display_score }}分</span>
              <a class="cmd-link" href="#" @click.prevent="openFlashcard(r)">快速复习 →</a>
            </div>
            <div v-for="s in data.active_sessions" :key="'active-'+s.id" class="cmd-item">
              <span :class="['stage-badge', 'cmd-badge-stage', statusLabel(s.status).cls]">{{ statusLabel(s.status).text }}</span>
              <a class="cmd-link" href="#" @click.prevent="gotoSession(s.id, s.status === 'deepening' || s.status === 'revising' ? 'deepen' : 'learn')">{{ s.title || '未命名' }}</a>
              <span v-if="s.score" class="cmd-score">{{ s.score }}分</span>
            </div>
          </template>
          <div v-else class="cmd-empty">暂无进行中的学习</div>
        </section>

        <section class="home-section" v-if="data.top_gaps?.length">
          <div class="home-section-title home-urgent" v-html="icon('clip') + ' 薄弱点'"></div>
          <div v-for="g in data.top_gaps" :key="'gap-'+g.id" class="cmd-item cmd-item-urgent">
            <span class="cmd-badge cmd-badge-gap">{{ severityLabel(g.severity) }}</span>
            <a class="cmd-link" href="#" @click.prevent="gotoSession(g.session_id, 'deepen')">{{ g.text }}</a>
            <span class="cmd-score">{{ g.session_title }}</span>
          </div>
        </section>

        <section class="home-section">
          <div class="home-section-title" v-html="icon('refresh') + ' 未来 7 天复习'"></div>
          <template v-if="data.upcoming_reviews?.length">
            <div v-for="r in data.upcoming_reviews" :key="'up-'+r.review_id" class="cmd-item">
              <span class="cmd-badge cmd-badge-review">{{ r.review_date }}</span>
              <a class="cmd-link" href="#" @click.prevent="gotoSession(r.session_id, 'learn')">{{ r.title || '未命名' }}</a>
              <span class="cmd-score">{{ r.review_round > 0 ? 'R'+(r.review_round+1) : '' }}</span>
            </div>
          </template>
          <div v-else class="cmd-empty">未来 7 天无复习计划</div>
        </section>
      </template>
    </div>
      <!-- #3: flashcard modal -->
      <div v-if="flashcard" class="flashcard-overlay" @click.self="closeFlashcard">
        <div class="flashcard-card">
          <div class="flashcard-header">
            <span>{{ flashcard.title }}</span>
            <button class="modal-close" @click="closeFlashcard">+</button>
          </div>
          <div v-if="!fcDone" class="flashcard-body">
            <div class="ps-hint muted small mb8">用自己的话重新解释这个概念（3-5分钟）</div>
            <textarea v-model="fcAnswer" rows="6" placeholder="不看材料，靠自己的理解来解释…"></textarea>
            <button class="btn btn-primary btn-block mt8" :disabled="fcSubmitting" @click="submitFlashcard">
              {{ fcSubmitting ? '提交中…' : '提交解释' }}
            </button>
          </div>
          <div v-else class="flashcard-body">
            <div class="flashcard-result">
              <span :class="['final-score-num', fcDone.score >= 60 ? 'pass' : 'fail']">{{ fcDone.score }}/100</span>
              <div class="md-body mt8" v-html="fcDone.feedback"></div>
            </div>
            <button class="btn btn-block mt8" @click="closeFlashcard">关闭</button>
          </div>
        </div>
      </div>
  `,
});
