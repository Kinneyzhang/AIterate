// ── Workspace.js ── 三节手风琴布局 ─────────────────────────────────────

import { defineComponent, ref, watch, computed } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { store, currentSession, currentRounds, feynmanGroup, unresolvedGaps, reviewReport, knowledgeNode, setNotice, getStageMeta, escapeHtml, renderMarkdown, formatDate } from '../store.js';
import { api } from '../api.js';

export default defineComponent({
  emits: ['refresh'],

  setup(props, { emit }) {
    const router = useRouter();
    const route  = useRoute();
    const takeInput = ref('');
    const questionInput = ref('');
    const feynmanAnswers = ref({});
    const submitting = ref(false);

    // ── Accordion state: which sections are expanded ──────────────────
    const accordion = ref({ learn: true, deepen: false, feynman: false });

    function toggleAccordion(key) {
      const wasOpen = accordion.value[key];
      accordion.value = { learn: false, deepen: false, feynman: false };
      if (!wasOpen) accordion.value[key] = true;
    }

    // ── Session lifecycle ────────────────────────────────────────────

    const canEdit = computed(() => {
      const s = currentSession.value?.status;
      return s && ['learning', 'deepening', 'revising'].includes(s);
    });

    const canFeynman = computed(() => {
      const s = currentSession.value?.status;
      return canEdit.value
        || ['feynman', 'completed'].includes(s)
        || currentRounds.value.some(r => r.type === 'take' || r.type === 'press');
    });

    // Overlay routes
    const OVERLAY_ROUTES = new Set(['new-session','knowledge-tree','command-center',
      'settings-basic','settings-roles','settings-tavily','settings-database','settings-learn']);
    const activeTab = computed(() => {
      if (OVERLAY_ROUTES.has(route.name)) return 'learn';
      return route.name === 'session-deepen' ? 'deepen'
           : route.name === 'session-review'  ? 'review'
           : 'learn';
    });

    // Status → router sync (keep for URL consistency)
    let sessionInitialized = false;
    watch(() => store.selectedSessionId, () => { sessionInitialized = false; });
    watch(() => currentSession.value?.status, (status, prevStatus) => {
      if (!store.selectedSessionId) return;
      if (!status) return;
      const id = store.selectedSessionId;
      if (String(route.params.id) !== String(id)) return;
      const isInit = !prevStatus || !sessionInitialized;
      if (status === prevStatus && !isInit) return;
      sessionInitialized = true;
      if ((status === 'feynman' || status === 'completed') && activeTab.value !== 'review' && activeTab.value !== 'deepen') {
        router.replace({ name: 'session-review', params: { id } });
      } else if ((status === 'deepening' || status === 'revising') && (isInit || activeTab.value === 'learn')) {
        router.replace({ name: 'session-deepen', params: { id } });
      } else if (isInit && (status === 'learning' || status === 'preparing')) {
        router.replace({ name: 'session-learn', params: { id } });
      }
    });

    // ── Take evaluations ─────────────────────────────────────────────
    const takeEvals = computed(() => {
      const map = {};
      for (const e of store.workspace?.take_evaluations || []) {
        if (e?.eval) map[e.id] = e.eval;
      }
      return map;
    });

    const hasUserTake = computed(() => currentRounds.value.some(r => r.type === 'take'));
    const showDeepen = computed(() => !shouldWriteFirst.value && currentSession.value?.material);
    const showFeynman = computed(() => canFeynman.value && hasUserTake.value);
    const doneFeynmanGroups = computed(() => {
      const done = currentRounds.value.filter(r => r.type === 'feynman' && r.status === 'completed');
      const byGroup = {};
      for (const r of done) {
        const gid = r.group_id ?? r.id;
        (byGroup[gid] = byGroup[gid] || []).push(r);
      }
      return Object.values(byGroup).reverse().map(grp => grp.sort((a, b) => a.seq - b.seq));
    });

    // ── Complete session ─────────────────────────────────────────────
    const completingSession = ref(false);
    async function completeSession() {
      const sid = store.selectedSessionId;
      if (!sid || completingSession.value) return;
      completingSession.value = true;
      try {
        await api.completeSession(sid);
        emit('refresh');
        setNotice('学习已结束。');
      } catch (err) {
        setNotice(`结束失败：${err.message}`, 'error');
      } finally { completingSession.value = false; }
    }

    async function reopenSession() {
      const sid = store.selectedSessionId;
      if (!sid) return;
      try {
        await api.reopenSession(sid);
        emit('refresh');
        setNotice('已重新打开。');
      } catch (err) { setNotice(`重新打开失败：${err.message}`, 'error'); }
    }

    // ── Submit take / press ──────────────────────────────────────────
    async function submitDeepAction(actionType) {
      const sid = store.selectedSessionId;
      if (!sid || submitting.value) return;
      const input = actionType === 'take' ? takeInput.value.trim() : questionInput.value.trim();
      if (!input) { setNotice('请输入内容。', 'error'); return; }
      submitting.value = true;
      try {
        await api.submitDeepAction(sid, actionType, input);
        if (actionType === 'take') takeInput.value = '';
        else questionInput.value = '';
        emit('refresh');
        setNotice(actionType === 'take' ? '理解已提交。' : '追问已提交。');
      } catch (err) {
        setNotice(`提交失败：${err.message}`, 'error');
      } finally { submitting.value = false; }
    }

    // ── Regenerate ───────────────────────────────────────────────────
    async function regenerateAnswer() {
      const sid = store.selectedSessionId; if (!sid) return;
      submitting.value = true;
      try { await api.regenerateAnswer(sid); emit('refresh'); setNotice('AI 回答已重新生成。'); }
      catch (err) { setNotice(`重新生成失败：${err.message}`, 'error'); }
      finally { submitting.value = false; }
    }
    async function regeneratePress(roundId) {
      const sid = store.selectedSessionId; if (!sid) return;
      submitting.value = true;
      try { await api.regeneratePress(sid, roundId); emit('refresh'); setNotice('追问回答已重新生成。'); }
      catch (err) { setNotice(`重新生成失败：${err.message}`, 'error'); }
      finally { submitting.value = false; }
    }
    async function regenerateFeynman() {
      const sid = store.selectedSessionId; if (!sid) return;
      submitting.value = true;
      try { await api.regenerateFeynman(sid); emit('refresh'); setNotice('费曼题已重新生成。'); }
      catch (err) { setNotice(`重新生成失败：${err.message}`, 'error'); }
      finally { submitting.value = false; }
    }

    // ── Feynman ──────────────────────────────────────────────────────
    const correctionPlan = ref(null);
    async function startFeynman() {
      const sid = store.selectedSessionId; if (!sid) return;
      submitting.value = true;
      try { await api.startFeynman(sid); emit('refresh'); setNotice('费曼题已生成，开始检验。'); }
      catch (err) { setNotice(`启动费曼失败：${err.message}`, 'error'); }
      finally { submitting.value = false; }
    }
    async function submitFeynman() {
      const sid = store.selectedSessionId;
      const gid = store.currentFeynmanGroupId;
      if (!sid || !gid) return;
      const group = feynmanGroup.value;
      const answers = group.map((_, i) => (feynmanAnswers.value[i] || '').trim());
      if (answers.some(a => !a)) { setNotice('请填写所有费曼答案。', 'error'); return; }
      submitting.value = true;
      try {
        const data = await api.completeFeynman(sid, gid, answers);
        feynmanAnswers.value = {};
        correctionPlan.value = data.correction_plan || null;
        emit('refresh');
        setNotice(data.passed ? '费曼检验通过！🎉' : '费曼未通过——下方有具体修正计划。');
      } catch (err) { setNotice(`提交失败：${err.message}`, 'error'); }
      finally { submitting.value = false; }
    }

    // ── Review ───────────────────────────────────────────────────────
    const reviewSchedule = ref([]);
    const reviewContents = ref({});
    const reviewSubmitting = ref({});
    const reviewResults = ref({});
    watch(() => store.workspace, (ws) => {
      const s = ws?.review_schedule || [];
      reviewSchedule.value = s.sort((a, b) => {
        const pa = !a.review_date ? 0 : a.review_date;
        const pb = !b.review_date ? 0 : b.review_date;
        if (pa < pb) return -1; if (pa > pb) return 1;
        const sa = a.status === 'pending' ? 0 : 1;
        const sb = b.status === 'pending' ? 0 : 1;
        return sa - sb;
      });
    }, { immediate: true, deep: true });

    async function submitReviewReExplain(reviewId) {
      if (!reviewId || reviewSubmitting.value[reviewId]) return;
      reviewSubmitting.value[reviewId] = true;
      try {
        const data = await api.submitReviewReExplain(reviewId, reviewContents.value[reviewId] || '');
        reviewResults.value[reviewId] = data;
        delete reviewContents.value[reviewId];
        emit('refresh');
      } catch (err) { setNotice(`提交失败：${err.message}`, 'error'); }
      finally { delete reviewSubmitting.value[reviewId]; }
    }
    async function completeReviewDirect(reviewId, btn) {
      if (!reviewId) return;
      if (btn) btn.disabled = true;
      try {
        await api.completeReviewDirect(reviewId);
        emit('refresh');
        setNotice('已标记完成。');
      } catch (err) { setNotice(`操作失败：${err.message}`, 'error'); }
      finally { if (btn) btn.disabled = false; }
    }

    // ── Write-first ──────────────────────────────────────────────────
    function _skipKey(sid) { return 'aiterate_skip_write_' + sid; }
    const writeFirstSkipped = ref(false);
    function skipWriteFirst() {
      const sid = store.selectedSessionId;
      if (sid) { localStorage.setItem(_skipKey(sid), '1'); writeFirstSkipped.value = true; }
    }
    watch(() => store.selectedSessionId, (sid) => {
      writeFirstSkipped.value = !!(sid && localStorage.getItem(_skipKey(sid)));
    }, { immediate: true });
    const shouldWriteFirst = computed(() => {
      return ['preparing', 'learning'].includes(currentSession.value?.status) && !hasUserTake.value && !writeFirstSkipped.value;
    });

    // ── Icons ────────────────────────────────────────────────────────
    const icons = {
      bulb: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/></svg>',
      book: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
      refresh: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
      flask: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5l5.45 9.54A2 2 0 0 1 18.73 21H5.27a2 2 0 0 1-1.72-3.46L9 8V3z"/><line x1="9" y1="3" x2="9" y2="8"/><line x1="15" y1="3" x2="15" y2="8"/></svg>',
      check: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
      search: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
      edit: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>',
      chart: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
      warn: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      clip: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>',
      chevron: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>',
    };

    // Helpers for accordion summary text
    const roundCount = computed(() => currentRounds.value.filter(r => r.type === 'take' || r.type === 'press').length);
    const feynmanDoneCount = computed(() => currentRounds.value.filter(r => r.type === 'feynman' && r.status === 'completed').length);

    return {
      currentSession, currentRounds, feynmanGroup, unresolvedGaps, reviewReport, knowledgeNode,
      doneFeynmanGroups, takeEvals, correctionPlan,
      shouldWriteFirst, skipWriteFirst, hasUserTake, showDeepen, showFeynman,
      canEdit, canFeynman, accordion, toggleAccordion,
      takeInput, questionInput, feynmanAnswers, submitting, completingSession,
      submitDeepAction, completeSession, reopenSession,
      startFeynman, submitFeynman,
      regenerateAnswer, regeneratePress, regenerateFeynman,
      reviewSchedule, reviewContents, reviewSubmitting, reviewResults,
      submitReviewReExplain, completeReviewDirect,
      getStageMeta, escapeHtml, renderMarkdown, formatDate, icons,
    };
  },

  template: `
    <div id="workspacePanel">
      <template v-if="!currentSession">
        <div class="empty-state">
          <div class="empty-icon"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.3"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/></svg></div>
          <h3>从左侧选一个 session，或点 ＋ 新建</h3>
          <p>每个问题 / 观点都是独立迭代单元。</p>
        </div>
      </template>
      <template v-else>
        <div class="panel-content single-flow">

          <!-- ── Header ────────────────────────────────────────────── -->
          <div class="session-header">
            <div class="sh-top">
              <div class="sh-left">
                <h2 class="sh-title">{{ currentSession.title || '未命名' }}</h2>
                <div class="sh-meta">
                  <span :class="['stage-badge', getStageMeta(currentSession.status).cls]">{{ getStageMeta(currentSession.status).label }}</span>
                  <span>{{ currentSession.type === 'viewpoint' ? '观点' : '问题' }}</span>
                  <span>{{ formatDate(currentSession.created_at) }}</span>
                  <span v-if="currentSession.score && currentSession.status==='completed'\">评分 {{ currentSession.score }}/100</span>
                </div>
              </div>
              <div v-if="currentSession.status==='completed'" class="sh-actions">
                <button class="btn btn-text" :disabled="submitting" @click="reopenSession">重新打开</button>
              </div>
            </div>
            <div v-if="currentSession.content && currentSession.content !== currentSession.title" class="sh-question">
              {{ currentSession.content }}
            </div>
          </div>

          <!-- ══════════════════════════════════════════════════════════
               Section 1: 学习
               ══════════════════════════════════════════════════════════ -->
          <div class="accordion-section" :class="{ open: accordion.learn }">
            <button class="accordion-header" @click="toggleAccordion('learn')">
              <span class="accordion-chevron" :class="{ open: accordion.learn }" v-html="icons.chevron"></span>
              <span class="accordion-title" v-html="icons.book + ' 学习'\"></span>
              <span class="accordion-summary" v-if="!accordion.learn">AI 回答</span>
            </button>
            <div v-if="accordion.learn" class="accordion-body">

              <!-- Write-first -->
              <div v-if="shouldWriteFirst" class="panel-section write-first-section">
                <div class="ps-label" v-html="icons.edit + ' 先写你的理解（可选）'\"></div>
                <p class="ps-hint">用自己的话解释你对这个问题的理解，AI 会对比并指出差距。也可以直接跳过。</p>
                <textarea v-model="takeInput" rows="5" placeholder="你对这个问题的理解是什么？靠自己的知识来回答…"></textarea>
                <div class="write-first-actions">
                  <button class="btn btn-primary" :disabled="submitting || currentSession.status === 'preparing'"
                          @click="submitDeepAction('take')">
                    {{ currentSession.status === 'preparing' ? 'AI 回答生成中，可先写' : '提交理解，查看 AI 对比' }}
                  </button>
                  <button class="btn btn-text" @click="skipWriteFirst">跳过，直接看 AI 回答</button>
                </div>
              </div>

              <!-- AI Answer -->
              <div v-if="currentSession.material" class="ai-answer-section">
                <div class="ai-answer-header">
                  <div class="ps-label" style="margin:0" v-html="icons.book + ' AI 回答'\"></div>
                  <button class="btn btn-sm btn-text" :disabled="submitting" @click="regenerateAnswer">🔄 重新回答</button>
                </div>
                <div class="ps-body md-body" v-html="renderMarkdown(currentSession.material)"></div>
              </div>

            </div>
          </div>

          <!-- ══════════════════════════════════════════════════════════
               Section 2: 深化
               ══════════════════════════════════════════════════════════ -->
          <div v-if="showDeepen" class="accordion-section" :class="{ open: accordion.deepen }">
            <button class="accordion-header" @click="toggleAccordion('deepen')">
              <span class="accordion-chevron" :class="{ open: accordion.deepen }" v-html="icons.chevron"></span>
              <span class="accordion-title" v-html="icons.edit + ' 深化'"></span>
              <span class="accordion-summary" v-if="!accordion.deepen">{{ roundCount ? roundCount + ' 轮' : '写理解 / 提追问' }}</span>
            </button>
            <div v-if="accordion.deepen" class="accordion-body">

              <!-- 写理解 + 提追问 并排 -->
              <div class="deepen-grid">
                <div class="panel-section">
                  <div class="ps-label" v-html="icons.edit + ' 写理解'"></div>
                  <p class="ps-hint">用自己的话说说你对 AI 回答的理解。</p>
                  <textarea v-model="takeInput" rows="5" placeholder="用自己的话解释…"></textarea>
                  <button class="btn btn-primary btn-block" :disabled="submitting" @click="submitDeepAction('take')">提交理解</button>
                </div>
                <div class="panel-section">
                  <div class="ps-label" v-html="icons.search + ' 提追问'"></div>
                  <p class="ps-hint">追问细节、反例、边界条件。</p>
                  <textarea v-model="questionInput" rows="5" placeholder="我对…还有疑问…"></textarea>
                  <button class="btn btn-primary btn-block" :disabled="submitting" @click="submitDeepAction('press')">提交追问</button>
                </div>
              </div>

              <!-- History rounds -->
              <template v-if="roundCount">
                <div class="ps-label" style="margin-bottom:12px" v-html="icons.clip + ' 历史记录 · ' + roundCount + ' 轮'\"></div>
                <template v-for="r in currentRounds.filter(r => r.type === 'take' || r.type === 'press')" :key="r.id">
                  <div v-if="r.type === 'take'" class="round-card round-take">
                    <div class="round-user-wrap"><span class="round-label" v-html="icons.edit + ' 理解'\"></span><span class="round-user">{{ r.input || '' }}</span></div>
                    <div class="round-ai md-body">
                      <div class="ps-label">AI 评价</div>
                      <div v-html="renderMarkdown(r.output || '')"></div>
                    </div>
                    <div v-if="takeEvals[r.id]?.gaps?.length" class="gaps-section">
                      <div class="gaps-label" v-html="icons.warn + ' 薄弱点'\"></div>
                      <ul class="gaps-list"><li v-for="g in takeEvals[r.id].gaps">{{ g }}</li></ul>
                    </div>
                    <div v-if="r.score" class="round-score">评分 {{ r.score }}/100</div>
                  </div>
                  <div v-else-if="r.type === 'press'" class="round-card round-press">
                    <div class="round-user-wrap"><span class="round-label" v-html="icons.search + ' 追问'\"></span><span class="round-user">{{ r.input || '' }}</span></div>
                    <div class="round-ai md-body">
                      <div style="display:flex;align-items:center;gap:8px">
                        <div class="ps-label" style="margin-bottom:0">AI 回答</div>
                        <button class="btn btn-sm btn-text" :disabled="submitting" @click="regeneratePress(r.id)" style="padding:2px 8px;font-size:12px">🔄</button>
                      </div>
                      <div v-html="renderMarkdown(r.output || '')"></div>
                    </div>
                  </div>
                </template>
              </template>

            </div>
          </div>

          <!-- ══════════════════════════════════════════════════════════
               Section 3: 费曼检验
               ══════════════════════════════════════════════════════════ -->
          <div v-if="showFeynman" class="accordion-section" :class="{ open: accordion.feynman }">
            <button class="accordion-header" @click="toggleAccordion('feynman')">
              <span class="accordion-chevron" :class="{ open: accordion.feynman }" v-html="icons.chevron"></span>
              <span class="accordion-title" v-html="icons.flask + ' 费曼检验'\"></span>
              <span class="accordion-summary" v-if="!accordion.feynman">{{ currentSession.status === 'feynman' ? '进行中' : feynmanDoneCount ? feynmanDoneCount + ' 题已完成' : '待检验' }}</span>
            </button>
            <div v-if="accordion.feynman" class="accordion-body">

              <!-- Active feynman -->
              <div v-if="feynmanGroup.length && currentSession.status === 'feynman'">
                <div style="display:flex;align-items:center;gap:8px">
                  <div class="ps-label" style="margin-bottom:0" v-html="icons.flask + ' 费曼检验'\"></div>
                  <button class="btn btn-sm btn-text" :disabled="submitting" @click="regenerateFeynman" style="padding:2px 8px;font-size:12px">🔄 重新出题</button>
                </div>
                <p class="ps-hint">用自己的话回答，AI 会评估你的掌握程度。</p>
                <div v-for="(q, i) in feynmanGroup" :key="q.id" class="review-q">
                  <div class="review-q-title">Q{{ i+1 }}. {{ q.input || '' }}</div>
                  <textarea class="review-answer" rows="4" :placeholder="'用自己的话回答…'" v-model="feynmanAnswers[i]"></textarea>
                </div>
                <button class="btn btn-primary btn-block mt8" :disabled="submitting" @click="submitFeynman" v-html="icons.chart + ' 提交答案'\"></button>
              </div>

              <!-- Start feynman -->
              <div v-else-if="canEdit && !feynmanGroup.length">
                <button class="btn btn-primary btn-block" :disabled="submitting" @click="startFeynman">开始费曼检验</button>
              </div>

              <!-- Correction plan -->
              <div v-if="correctionPlan && currentSession.status !== 'completed'" class="correction-plan-section">
                <div class="ps-label" v-html="icons.warn + ' 修正计划'\"></div>
                <div v-if="correctionPlan.weak_concepts?.length" class="cp-block">
                  <div class="cp-subtitle">薄弱概念</div>
                  <ul class="cp-list weak"><li v-for="c in correctionPlan.weak_concepts">{{ c }}</li></ul>
                </div>
                <div v-if="correctionPlan.failed_items?.length" class="cp-block">
                  <div class="cp-subtitle">失败题目</div>
                  <div v-for="(fi, i) in correctionPlan.failed_items" :key="i" class="cp-failed-item">
                    <div class="cp-failed-q">{{ fi.question }}</div>
                    <span :class="['item-score', fi.score >= 60 ? 'pass' : 'fail']">{{ fi.score }}分 — {{ fi.comment }}</span>
                  </div>
                </div>
                <div v-if="correctionPlan.recommended_actions?.length" class="cp-block">
                  <div class="cp-subtitle">建议动作</div>
                  <ul class="cp-list"><li v-for="a in correctionPlan.recommended_actions">{{ a }}</li></ul>
                </div>
              </div>

              <!-- Done feynman history -->
              <template v-if="doneFeynmanGroups.length">
                <div v-for="(grp, gi) in doneFeynmanGroups" :key="gi" class="round-card round-review">
                  <div class="round-label" v-html="icons.flask + ' 费曼记录 · '\n                    + Math.round(grp.reduce((s,r) => s + (r.score||0), 0) / grp.length) + '/100'"></div>
                  <div class="qa-list">
                    <div v-for="(r, i) in grp" :key="r.id" class="qa-pair">
                      <div class="qa-q">Q{{ i+1 }} {{ r.input || '' }}
                        <span v-if="r.score != null" :class="['item-score', r.score >= 60 ? 'pass' : 'fail']">{{ r.score }}分</span>
                      </div>
                      <div class="qa-a">{{ r.output || '（未作答）' }}</div>
                      <div v-if="r.score_comment" style="margin-top:6px">
                        <div class="ps-label">AI 评价</div>
                        <div class="item-comment">{{ r.score_comment }}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </template>

            </div>
          </div>

          <!-- ── Completed summary ───────────────────────────────────── -->
          <div v-if="currentSession.status === 'completed'" class="panel-section completed-summary">
            <div class="final-score-row">
              <span class="final-score-num" v-if="currentSession.score">{{ currentSession.score }}/100</span>
              <span class="final-score-num muted" v-else>未评分</span>
              <span class="stage-badge stage-completed">已完成</span>
            </div>
            <div v-if="!reviewSchedule.length && !doneFeynmanGroups.length" class="muted small" style="text-align:center;padding:16px 0">
              本次未进行费曼检验
            </div>
            <div v-if="reviewReport" class="review-report">
              <div class="report-row"><span class="report-label">掌握度</span><span class="report-value">{{ reviewReport.mastery_level || '—' }}</span></div>
              <div v-if="reviewReport.final_summary" class="report-summary md-body" v-html="renderMarkdown(reviewReport.final_summary)"></div>
              <div v-if="reviewReport.strong_points?.length" class="report-section">
                <div class="report-label" v-html="icons.check + ' 理解到位的点'\"></div>
                <ul class="report-list good"><li v-for="p in reviewReport.strong_points">{{ p }}</li></ul>
              </div>
              <div v-if="reviewReport.weak_points?.length" class="report-section">
                <div class="report-label" v-html="icons.edit + ' 还需加强'\"></div>
                <ul class="report-list weak"><li v-for="p in reviewReport.weak_points">{{ p }}</li></ul>
              </div>
            </div>
          </div>

          <!-- ── Review schedule ─────────────────────────────────────── -->
          <div v-if="reviewSchedule.length" class="review-schedule-section">
            <div class="ps-label" v-html="icons.refresh + ' 复习排期'\"></div>
            <div class="rs-list">
              <div v-for="rs in reviewSchedule" :key="rs.id"
                   :class="['rs-item', rs.status === 'completed' ? 'rs-done' : 'rs-pending']">
                <span class="rs-date">{{ rs.review_date }}</span>
                <template v-if="rs.status === 'pending' && !reviewResults[rs.id]">
                  <textarea class="review-re-explain" rows="3"
                            :placeholder="'用自己的话重新解释这个概念…'"
                            :value="reviewContents[rs.id] || ''"
                            @input="e => reviewContents[rs.id] = e.target.value"></textarea>
                  <div class="rs-actions">
                    <button class="btn btn-primary btn-sm" :disabled="reviewSubmitting[rs.id]"
                            @click="submitReviewReExplain(rs.id)">{{ reviewSubmitting[rs.id] ? '…' : '提交解释' }}</button>
                    <button class="btn btn-sm" @click="completeReviewDirect(rs.id, $event.target)">稍后提醒</button>
                  </div>
                </template>
                <div v-else-if="reviewResults[rs.id]" class="rs-feedback">
                  <span :class="['rs-score', reviewResults[rs.id].passed ? 'pass' : 'fail']">{{ reviewResults[rs.id].score }}/100</span>
                  <div class="rs-feedback-text md-body" v-html="renderMarkdown(reviewResults[rs.id].feedback)"></div>
                </div>
                <template v-else-if="rs.status === 'completed'">
                  <span class="rs-status">
                    <span v-if="rs.review_score != null" :class="['rs-score-badge', rs.review_score >= 60 ? 'pass' : 'fail']">{{ rs.review_score }}/100</span>
                    <span v-else>✓</span>
                  </span>
                  <div v-if="rs.user_content" class="rs-user-content">
                    <div class="rs-label-small">你的重新解释</div>
                    <div class="rs-content-text">{{ rs.user_content }}</div>
                  </div>
                  <div v-if="rs.ai_feedback" class="rs-feedback-text md-body" v-html="renderMarkdown(rs.ai_feedback)"></div>
                </template>
              </div>
            </div>
          </div>

          <!-- ── Unresolved gaps ─────────────────────────────────────── -->
          <div v-if="unresolvedGaps.length" class="gaps-banner">
            <div class="gaps-banner-title" v-html="icons.clip + ' 待解决薄弱点（' + unresolvedGaps.length + '）'\"></div>
            <ul class="gaps-summary">
              <li v-for="g in unresolvedGaps.slice(0, 8)">{{ g.gap }} <span class="muted small">→ 第{{ g.seq }}轮</span></li>
            </ul>
          </div>

          <!-- ── Bottom: End Session ─────────────────────────────────── -->
          <div v-if="canEdit" class="bottom-actions">
            <button class="btn btn-end-session-bottom" :disabled="completingSession" @click="completeSession">
              <span v-html="icons.check"></span> {{ completingSession ? '…' : '结束学习' }}
            </button>
            <p class="muted" style="text-align:center;font-size:12px;margin-top:10px">随时可以结束，不需要走完所有阶段</p>
          </div>

        </div>
      </template>
    </div>
  `,
});
