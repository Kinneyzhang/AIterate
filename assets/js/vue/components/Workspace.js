// ── Workspace.js ── 精确复刻原版 workspace ───────────────────────────────

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

    // activeTab 从路由派生，但 overlay / 新 session 加载期间保持上次的 session tab。
    // 关键：切换 session 时 route 会先变，workspace 异步稍后才回来。
    // 如果此时直接按新 route 切 tab，就会把“旧 session”短暂渲染到“新 route 的 tab”里，用户会看到闪页。
    const OVERLAY_ROUTES = new Set(['new-session','knowledge-tree','command-center',
      'settings-basic','settings-roles','settings-tavily','settings-database','settings-learn']);
    const lastSessionTab = ref('learn');   // 记住上次选的 tab
    const activeTab = computed(() => {
      if (OVERLAY_ROUTES.has(route.name)) return lastSessionTab.value;  // overlay 期间不变
      const routeSessionId = route.params.id ? Number(route.params.id) : null;
      const loadedSessionId = currentSession.value?.id ? Number(currentSession.value.id) : null;
      if (routeSessionId && loadedSessionId && routeSessionId !== loadedSessionId) {
        return lastSessionTab.value; // 新 workspace 未加载完成前，不用新 route 改旧 workspace 的 tab
      }
      const tab = route.name === 'session-deepen' ? 'deepen'
                : route.name === 'session-review'  ? 'review'
                : 'learn';
      lastSessionTab.value = tab;   // 记录最新选择
      return tab;
    });

    // session 状态变化时自动跳转到合适的 tab
    // 规则：
    //   1. 初次加载（prevStatus=undefined）→ 强制跳到匹配 status 的 tab（初始化）
    //   2. 运行时 status 真正变化 → 自动跳
    //   3. 用户手动切 tab 后（activeTab 已不是 learn）→ 不强制覆盖
    let sessionInitialized = false;
    watch(() => store.selectedSessionId, () => { sessionInitialized = false; });  // 切换 session 时重置
    watch(() => currentSession.value?.status, (status, prevStatus) => {
      if (!store.selectedSessionId) return;
      if (!status) return;
      const id = store.selectedSessionId;
      if (String(route.params.id) !== String(id)) return;
      const isInit = !prevStatus || !sessionInitialized;
      if (status === prevStatus && !isInit) return;
      sessionInitialized = true;
      // feynman/completed 默认进入费曼 tab，但不要阻止用户查看深化历史
      if ((status === 'feynman' || status === 'completed') && activeTab.value !== 'review' && activeTab.value !== 'deepen') {
        router.replace({ name: 'session-review', params: { id } });
      }
      // deepening/revising：初始化时跳 deepen；运行时只从 learn 跳
      else if ((status === 'deepening' || status === 'revising') && (isInit || activeTab.value === 'learn')) {
        router.replace({ name: 'session-deepen', params: { id } });
      }
      // learning/preparing：初始化时跳回 learn
      else if (isInit && (status === 'learning' || status === 'preparing')) {
        router.replace({ name: 'session-learn', params: { id } });
      }
    });

    // #1: knowledge node auto-suggest
    const nodeSuggestion = ref(null);
    const nodeSuggestionLoading = ref(false);
    watch(() => store.workspace, async (ws) => {
      if (!ws || !ws.session) { nodeSuggestion.value = null; return; }
      if (ws.knowledge_node_id || ws.knowledge_suggestion_ignored) { nodeSuggestion.value = null; return; }
      if (nodeSuggestionLoading.value || nodeSuggestion.value) return;
      const sid = ws.session.id;
      if (!sid) return;
      nodeSuggestionLoading.value = true;
      try {
        const data = await api.suggestKnowledgeNodes(sid);
        if (data?.suggestions?.length) {
          nodeSuggestion.value = data.suggestions[0];
        }
      } catch {} finally {
        nodeSuggestionLoading.value = false;
      }
    });

    async function bindSuggestedNode() {
      if (!nodeSuggestion.value) return;
      const sid = store.selectedSessionId;
      if (!sid) return;
      try {
        await api.bindKnowledgeNode(sid, nodeSuggestion.value.id);
        nodeSuggestion.value = null;
        emit('refresh');
      } catch (err) { setNotice(`绑定失败：${err.message}`, 'error'); }
    }

    async function ignoreSuggestedNode() {
      const sid = store.selectedSessionId;
      if (!sid) return;
      try {
        await api.ignoreKnowledgeNodeSuggestion(sid);
        nodeSuggestion.value = null;
        emit('refresh');
      } catch (err) { setNotice(`忽略失败：${err.message}`, 'error'); }
    }

    const canEditDeepen = computed(() => {
      const s = currentSession.value?.status;
      // Phase 5: whitelist — only allow deepen in these states
      return s && ['learning', 'deepening', 'revising'].includes(s);
    });
    const canDeepen = computed(() => {
      const s = currentSession.value?.status;
      return canEditDeepen.value
        || ['feynman', 'completed'].includes(s)
        || currentRounds.value.some(r => r.type === 'take' || r.type === 'press');
    });
    const canReview = computed(() => {
      const s = currentSession.value?.status;
      return ['feynman', 'completed'].includes(s) || currentRounds.value.some(r => r.type === 'feynman');
    });

    // 整个 session 的已完成费曼（按 group_id 聚合）
    const doneFeynmanGroups = computed(() => {
      const done = currentRounds.value.filter(r => r.type === 'feynman' && r.status === 'completed');
      const byGroup = {};
      for (const r of done) {
        const gid = r.group_id ?? r.id;
        (byGroup[gid] = byGroup[gid] || []).push(r);
      }
      return Object.values(byGroup).reverse().map(grp => grp.sort((a, b) => a.seq - b.seq));
    });

    // Take evaluations map
    const takeEvals = computed(() => {
      const map = {};
      for (const e of store.workspace?.take_evaluations || []) {
        if (e?.eval) map[e.id] = e.eval;
      }
      return map;
    });

    // #3: 学习状态且未写过理解 → 先隐藏 AI 回答，让用户写
    const hasUserTake = computed(() => {
      return currentRounds.value.some(r => r.type === 'take');
    });

    // Review schedule for completed sessions
    const reviewSchedule = computed(() => store.workspace?.review_schedule || []);

    // P4.2: 复习重新解释表单状态
    const reviewContents = ref({});   // rid → text
    const reviewSubmitting = ref({}); // rid → bool
    const reviewResults = ref({});    // rid → { score, feedback, passed }

    async function submitReviewReExplain(rid) {
      const content = (reviewContents.value[rid] || '').trim();
      if (!content) { setNotice('请先写重新解释。', 'error'); return; }
      reviewSubmitting.value = { ...reviewSubmitting.value, [rid]: true };
      try {
        const data = await api.submitReview(rid, content);
        reviewResults.value = { ...reviewResults.value, [rid]: data };
        reviewContents.value = { ...reviewContents.value, [rid]: '' };
        emit('refresh');
      } catch (err) {
        setNotice(`提交失败：${err.message}`, 'error');
      } finally {
        reviewSubmitting.value = { ...reviewSubmitting.value, [rid]: false };
      }
    }

    async function completeReviewDirect(rid, btn) {
      btn.disabled = true;
      btn.textContent = '…';
      try {
        await api.skipReview(rid);
        btn.textContent = '已跳过';
        emit('refresh');
      } catch {
        btn.textContent = '✗';
        btn.disabled = false;
      }
    }

    // Take/Press
    async function submitDeepAction(actionType) {
      const sid = store.selectedSessionId;
      const text = (actionType === 'take' ? takeInput.value : questionInput.value).trim();
      if (!sid || !text) return;
      submitting.value = true;
      try {
        await api.deepenSession(sid, actionType, text);
        if (actionType === 'take') takeInput.value = '';
        else questionInput.value = '';
        emit('refresh');
        setNotice(actionType === 'take' ? '理解评估完成，可继续迭代。' : '追问回答已返回。');
      } catch (err) {
        setNotice(`提交失败：${err.message}`, 'error');
      } finally {
        submitting.value = false;
      }
    }

    // Feynman
    const correctionPlan = ref(null);   // #8: 费曼失败修正计划

    async function startFeynman() {
      const sid = store.selectedSessionId;
      if (!sid) return;
      submitting.value = true;
      try {
        await api.startFeynman(sid);
        emit('refresh');
        setNotice('费曼题已生成，开始费曼检验。');
      } catch (err) {
        setNotice(`启动费曼失败：${err.message}`, 'error');
      } finally {
        submitting.value = false;
      }
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
        setNotice(data.passed ? '费曼检验通过，学习完成！\uD83C\uDF89' : '费曼未通过——下方有具体修正计划。');
      } catch (err) {
        setNotice(`提交失败：${err.message}`, 'error');
      } finally {
        submitting.value = false;
      }
    }

    function switchTab(tab) {
      const id = store.selectedSessionId;
      if (!id) return;
      const nameMap = { learn: 'session-learn', deepen: 'session-deepen', review: 'session-review' };
      router.push({ name: nameMap[tab], params: { id } });
    }

    // 图标 SVG
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
      tag: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>',
      clip: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>',
    };

    function openKnowledgeTree() {
      router.push({ name: 'knowledge-tree' });
    }

    // #5: 监听 gap → 追问预填
    watch(() => store.prefillQuestion, (val) => {
      if (val) {
        questionInput.value = val;
        store.prefillQuestion = '';
      }
    });

    // #3: 跳过写理解，直接查看 AI 回答
    const writeFirstSkipped = ref(false);
    function skipWriteFirst() {
      writeFirstSkipped.value = true;
    }
    const shouldWriteFirst = computed(() => {
      return currentSession.value?.status === 'learning' && !hasUserTake.value && !writeFirstSkipped.value;
    });

    return {
      activeTab, takeInput, questionInput, feynmanAnswers, submitting,
      canDeepen, canEditDeepen, canReview, currentSession, currentRounds, feynmanGroup,
      unresolvedGaps, reviewReport, knowledgeNode, doneFeynmanGroups, takeEvals,
      shouldWriteFirst, skipWriteFirst,
      correctionPlan,
      nodeSuggestion, nodeSuggestionLoading, bindSuggestedNode, ignoreSuggestedNode,
      submitDeepAction, startFeynman, submitFeynman, switchTab,
      reviewSchedule, completeReviewDirect,
      reviewContents, reviewSubmitting, reviewResults, submitReviewReExplain,
      openKnowledgeTree,
      getStageMeta, escapeHtml, renderMarkdown, formatDate, icons, router, route,
    };
  },

  template: `
    <div id="workspacePanel">
      <template v-if="!currentSession">
        <div class="empty-state">
          <div class="empty-icon"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity="0.3"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/></svg></div>
          <h3>从左侧选一个 session，或点 ＋ 新建</h3>
          <p>每个问题 / 观点都是独立迭代单元，经过三个阶段走向完成。</p>
        </div>
      </template>
      <template v-else>
        <!-- Tabs -->
        <div class="ws-tabs">
          <button :class="['ws-tab', { active: activeTab === 'learn' }]" id="tab-learn" @click="switchTab('learn')" v-html="icons.book + ' 学习'"></button>
          <button :class="['ws-tab', { active: activeTab === 'deepen' }]" id="tab-deepen" :disabled="!canDeepen" @click="switchTab('deepen')" v-html="icons.refresh + ' 深化'"></button>
          <button :class="['ws-tab', { active: activeTab === 'review' }]" id="tab-review" :disabled="!canReview" @click="switchTab('review')" v-html="icons.flask + ' 费曼'"></button>
        </div>

        <!-- Learn Panel -->
        <div v-show="activeTab === 'learn'" class="panel-content">
          <div class="panel-header">
            <div class="ph-title">{{ currentSession.title || '未命名' }}</div>
            <div class="ph-meta">
              <span :class="['stage-badge', getStageMeta(currentSession.status).cls]">{{ getStageMeta(currentSession.status).label }}</span>
              <span>{{ currentSession.type === 'viewpoint' ? '观点' : '问题' }}</span>
              <span>{{ formatDate(currentSession.created_at) }}</span>
              <span v-if="currentSession.score">评分 {{ currentSession.score }}/100</span>
            </div>
          </div>
          <div v-if="currentSession.content && currentSession.content !== currentSession.title" class="original-question">{{ currentSession.content }}</div>
          <div v-if="knowledgeNode" class="knowledge-node-bar">
            <span class="kn-label" v-html="icons.tag + ' 知识节点'"></span>
            <span class="kn-path">{{ knowledgeNode.title }}</span>
            <span v-if="knowledgeNode.keywords?.length" class="kn-keywords">
              <template v-for="k in knowledgeNode.keywords.slice(0,3)">#{{ k }} </template>
            </span>
          </div>
          <div v-else class="knowledge-node-bar" style="opacity:0.65; cursor:pointer;" @click="openKnowledgeTree" v-html="icons.tag + ' 未绑定知识节点 — 点击关联'"></div>
          <!-- #1: knowledge node auto-suggest -->
          <div v-if="nodeSuggestion && !knowledgeNode" class="knowledge-node-bar suggest-bar" style="cursor:default;">
            <span v-html="icons.tag + ' 系统推荐：' + nodeSuggestion.title"></span>
            <button class="btn btn-sm" @click="bindSuggestedNode" :disabled="nodeSuggestionLoading">确认绑定</button>
            <button class="btn btn-sm btn-text" @click="ignoreSuggestedNode" :disabled="nodeSuggestionLoading">忽略</button>
          </div>
          <!-- #3: 先写理解 — 不看 AI 回答，靠自己的理解 -->
          <div v-if="shouldWriteFirst" class="panel-section write-first-section">
            <div class="ps-label" v-html="icons.edit + ' 先写你的理解（可选）'"></div>
            <div class="ps-hint muted small mb8">用自己的话解释你对这个问题的理解，AI 会对比并指出差距。也可以直接跳过。</div>
            <textarea id="firstTakeInput" v-model="takeInput" rows="6" placeholder="你对这个问题的理解是什么？靠自己的知识来回答…"></textarea>
            <div class="write-first-actions">
              <button class="btn btn-primary" :disabled="submitting" @click="submitDeepAction('take')">提交理解，查看 AI 对比</button>
              <button class="btn btn-text" @click="skipWriteFirst">跳过，直接看 AI 回答</button>
            </div>
          </div>
          <div v-else-if="currentSession.material" class="panel-section">
            <div class="ps-label">AI 回答</div>
            <div class="ps-body md-body" v-html="renderMarkdown(currentSession.material)"></div>
          </div>
          <div v-else class="panel-empty">
            <span class="muted">AI 正在后台回答，稍后刷新查看…</span>
          </div>
        </div>

        <!-- Deepen Panel -->
        <div v-show="activeTab === 'deepen'" class="panel-content">
          <!-- Gaps banner -->
          <div v-if="unresolvedGaps.length" class="gaps-banner">
            <div class="gaps-banner-title" v-html="icons.clip + ' 待解决薄弱点（' + unresolvedGaps.length + '）'"></div>
            <ul class="gaps-summary">
              <li v-for="g in unresolvedGaps.slice(0, 8)">{{ g.gap }} <span class="muted small">→ 第{{ g.seq }}轮</span></li>
            </ul>
          </div>

          <!-- Rounds history -->
          <div v-if="currentRounds.filter(r => r.type === 'take' || r.type === 'press').length" class="deepen-history">
            <template v-for="r in currentRounds.filter(r => r.type === 'take' || r.type === 'press')" :key="r.id">
              <!-- Take round -->
              <div v-if="r.type === 'take'" class="round-card round-take">
                <div class="round-user-wrap"><span class="round-label" v-html="icons.bulb + ' 理解'"></span><span class="round-user">{{ r.input || '' }}</span></div>
                <div class="round-ai md-body">
                  <div class="ps-label">AI 评价</div>
                  <div v-html="renderMarkdown(r.output || '')"></div>
                </div>
                <div v-if="takeEvals[r.id]?.gaps?.length" class="gaps-section">
                  <div class="gaps-label" v-html="icons.warn + ' 薄弱点'"></div>
                  <ul class="gaps-list"><li v-for="g in takeEvals[r.id].gaps">{{ g }}</li></ul>
                </div>
                <div v-if="r.score" class="round-score">评分 {{ r.score }}/100</div>
              </div>
              <!-- Press round -->
              <div v-else-if="r.type === 'press'" class="round-card round-press">
                <div class="round-user-wrap"><span class="round-label" v-html="icons.search + ' 追问'"></span><span class="round-user">{{ r.input || '' }}</span></div>
                <div class="round-ai md-body">
                  <div class="ps-label">AI 回答</div>
                  <div v-html="renderMarkdown(r.output || '')"></div>
                </div>
              </div>
            </template>
          </div>

          <!-- Inputs -->
          <div v-if="canEditDeepen" class="deepen-inputs">
            <div class="deepen-col">
              <div class="col-label muted small" v-html="icons.search + ' 提追问'"></div>
              <textarea id="questionInput" v-model="questionInput" rows="4" placeholder="追问某个细节、反例、边界条件…"></textarea>
              <button class="btn btn-primary btn-block mt8" id="submitQuestionBtn" :disabled="submitting" @click="submitDeepAction('press')">提交追问</button>
            </div>
            <div class="deepen-col">
              <div class="col-label muted small" v-html="icons.edit + ' 写理解'"></div>
              <textarea id="takeInput" v-model="takeInput" rows="4" placeholder="用自己的话说说你对 AI 回答的理解，有没有偏差 AI 会告诉你…"></textarea>
              <button class="btn btn-primary btn-block mt8" id="submitTakeBtn" :disabled="submitting" @click="submitDeepAction('take')">提交理解</button>
            </div>
          </div>
          <button v-if="canEditDeepen" class="btn btn-success btn-block mt12" id="startFeynmanBtn" :disabled="submitting" @click="startFeynman" v-html="icons.check + ' 差不多了，开始费曼检验'"></button>
        </div>

        <!-- Review Panel -->
        <div v-show="activeTab === 'review'" class="panel-content">
          <!-- Completed summary -->
          <div v-if="currentSession.status === 'completed'" class="panel-section completed-summary">
            <div class="final-score-row">
              <span class="final-score-num" v-if="currentSession.score">{{ currentSession.score }}/100</span>
              <span class="final-score-num muted" v-else>未评分</span>
              <span class="stage-badge stage-completed">已完成</span>
            </div>
            <!-- Review Schedule (P4.2: re-explanation form) -->
            <div v-if="reviewSchedule.length" class="review-schedule-section mt12">
              <div class="ps-label" v-html="icons.refresh + ' 复习排期'"></div>
              <div class="rs-list">
                <div v-for="rs in reviewSchedule" :key="rs.id"
                     :class="['rs-item', rs.status === 'completed' ? 'rs-done' : 'rs-pending']">
                  <span class="rs-date">{{ rs.review_date }}</span>
                  <!-- Pending: show re-explanation form -->
                  <template v-if="rs.status === 'pending' && !reviewResults[rs.id]">
                    <textarea class="review-re-explain" rows="3"
                              :placeholder="'用自己的话重新解释这个概念…'"
                              :value="reviewContents[rs.id] || ''"
                              @input="e => reviewContents[rs.id] = e.target.value"></textarea>
                    <div class="rs-actions">
                      <button class="btn btn-primary btn-sm"
                              :disabled="reviewSubmitting[rs.id]"
                              @click="submitReviewReExplain(rs.id)">
                        {{ reviewSubmitting[rs.id] ? '…' : '提交解释' }}
                      </button>
                      <button class="btn btn-sm"
                              @click="completeReviewDirect(rs.id, $event.target)">稍后提醒</button>
                    </div>
                  </template>
                  <!-- Just submitted: show AI feedback -->
                  <div v-else-if="reviewResults[rs.id]" class="rs-feedback">
                    <span :class="['rs-score', reviewResults[rs.id].passed ? 'pass' : 'fail']">
                      {{ reviewResults[rs.id].score }}/100
                    </span>
                    <div class="rs-feedback-text md-body" v-html="renderMarkdown(reviewResults[rs.id].feedback)"></div>
                  </div>
                  <!-- Completed with content: show re-explanation + AI feedback -->
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
            <div v-if="reviewSchedule.length > 0 && reviewSchedule.some(r => r.status === 'pending' && !reviewResults[r.id])"
                 class="review-hint mt8" style="text-align:center; color:var(--muted); font-size:13px">
              用自己的话重新解释概念，AI 会评估你的掌握程度
            </div>
            <div v-if="!reviewReport && !doneFeynmanGroups.length" class="muted small mt8" style="text-align:center;padding:16px 0">
              本次未进行费曼检验（手动完成）
            </div>
            <div v-if="reviewReport" class="review-report">
              <div class="report-row"><span class="report-label">掌握度</span><span class="report-value">{{ reviewReport.mastery_level || '—' }}</span></div>
              <div v-if="reviewReport.final_summary" class="report-summary md-body" v-html="renderMarkdown(reviewReport.final_summary)"></div>
              <div v-if="reviewReport.strong_points?.length" class="report-section">
                <div class="report-label" v-html="icons.check + ' 理解到位的点'"></div>
                <ul class="report-list good"><li v-for="p in reviewReport.strong_points">{{ p }}</li></ul>
              </div>
              <div v-if="reviewReport.weak_points?.length" class="report-section">
                <div class="report-label" v-html="icons.edit + ' 还需加强'"></div>
                <ul class="report-list weak"><li v-for="p in reviewReport.weak_points">{{ p }}</li></ul>
              </div>
            </div>
          </div>

          <!-- Active Feynman -->
          <div v-if="feynmanGroup.length && currentSession.status === 'feynman'" class="panel-section">
            <div class="ps-label" v-html="icons.flask + ' 费曼检验'"></div>
            <div class="ps-hint muted small mb12">用自己的话回答，AI 会评估你的掌握程度。</div>
            <div v-for="(q, i) in feynmanGroup" :key="q.id" class="review-q">
              <div class="review-q-title">Q{{ i+1 }}. {{ q.input || '' }}</div>
              <textarea class="review-answer" rows="4" :placeholder="'用自己的话回答…'" v-model="feynmanAnswers[i]"></textarea>
            </div>
            <button class="btn btn-primary btn-block mt8" id="submitFeynmanBtn" :disabled="submitting" @click="submitFeynman" v-html="icons.chart + ' 提交答案'"></button>
          </div>

          <!-- Done Feynman history -->
          <template v-if="doneFeynmanGroups.length">
            <div v-for="(grp, gi) in doneFeynmanGroups" :key="gi" class="round-card round-review">
              <div class="round-label" v-html="icons.flask + ' 费曼记录 · ' + Math.round(grp.reduce((s,r) => s + (r.score||0), 0) / grp.length) + '/100'"></div>
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

          <!-- #8: 费曼失败修正计划 -->
          <div v-if="correctionPlan && currentSession.status !== 'completed'" class="correction-plan-section mt16">
            <div class="ps-label" v-html="icons.warn + ' 修正计划'"></div>
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
            <div v-if="correctionPlan.next_feynman_prerequisites?.length" class="cp-block">
              <div class="cp-subtitle">下次费曼前置条件</div>
              <ul class="cp-list"><li v-for="p in correctionPlan.next_feynman_prerequisites">✅ {{ p }}</li></ul>
            </div>
          </div>
        </div>
      </template>
    </div>
  `,
});
