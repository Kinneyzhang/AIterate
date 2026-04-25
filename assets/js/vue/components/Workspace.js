// ── Workspace.js ── 工作区（三 tab 切换）────────────────────────────────

import { defineComponent, ref, watch, computed } from 'vue';
import { store, currentSession, currentRounds, feynmanGroup, unresolvedGaps, reviewReport, knowledgeNode, setNotice, getStageMeta, escapeHtml, renderMarkdown, formatDate } from '../store.js';
import { api } from '../api.js';
import { icon } from '../icons.js';

export default defineComponent({
  emits: ['refresh'],
  
  setup(props, { emit }) {
    const activeTab = ref('learn');
    const takeInput = ref('');
    const questionInput = ref('');
    const feynmanAnswers = ref({});
    const submitting = ref(false);
    
    // Switch tab based on session status
    watch(() => currentSession.value?.status, (status) => {
      if (status === 'feynman' || status === 'completed') activeTab.value = 'review';
      else if (status === 'deepening' || status === 'revising') activeTab.value = 'deepen';
      else activeTab.value = 'learn';
    }, { immediate: true });
    
    const canDeepen = computed(() => {
      const s = currentSession.value?.status;
      return s && !['processing', 'idle', 'preparing'].includes(s);
    });
    const canReview = computed(() => {
      const s = currentSession.value?.status;
      return ['feynman', 'completed'].includes(s) || currentRounds.value.some(r => r.type === 'feynman');
    });
    
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
      } catch (err) {
        setNotice(`提交失败：${err.message}`, 'error');
      } finally {
        submitting.value = false;
      }
    }
    
    // Feynman
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
      if (answers.some(a => !a)) { alert('请填写所有费曼答案'); return; }
      submitting.value = true;
      try {
        const data = await api.completeFeynman(sid, gid, answers);
        feynmanAnswers.value = {};
        emit('refresh');
        setNotice(data.passed ? '费曼检验通过，学习完成！' : '费曼未通过，已退回深化阶段。');
      } catch (err) {
        setNotice(`提交失败：${err.message}`, 'error');
      } finally {
        submitting.value = false;
      }
    }
    
    return {
      activeTab, takeInput, questionInput, feynmanAnswers, submitting,
      canDeepen, canReview, currentSession, currentRounds, feynmanGroup,
      unresolvedGaps, reviewReport, knowledgeNode,
      submitDeepAction, startFeynman, submitFeynman,
      getStageMeta, escapeHtml, renderMarkdown, formatDate, icon,
    };
  },
  
  template: `
    <div id="workspacePanel" style="flex:1; display:flex; flex-direction:column; overflow:hidden;">
      <template v-if="!currentSession">
        <div class="empty-state">
          <div class="empty-icon" v-html="icon('bulb')" style="width:48px;height:48px;opacity:0.3"></div>
          <h3>从左侧选一个 session，或点 ＋ 新建</h3>
          <p>每个问题 / 观点都是独立迭代单元，经过三个阶段走向完成。</p>
        </div>
      </template>
      <template v-else>
        <!-- Tabs -->
        <div class="ws-tabs">
          <button :class="['ws-tab', { active: activeTab === 'learn' }]" @click="activeTab = 'learn'" v-html="icon('book') + ' 学习'"></button>
          <button :class="['ws-tab', { active: activeTab === 'deepen' }]" :disabled="!canDeepen" @click="activeTab = 'deepen'" v-html="icon('refresh') + ' 深化'"></button>
          <button :class="['ws-tab', { active: activeTab === 'review' }]" :disabled="!canReview" @click="activeTab = 'review'" v-html="icon('flask') + ' 费曼'"></button>
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
            <span class="kn-label" v-html="icon('tag') + ' 知识节点'"></span>
            <span class="kn-path">{{ knowledgeNode.title }}</span>
            <span v-if="knowledgeNode.keywords?.length" class="kn-keywords">
              <template v-for="k in knowledgeNode.keywords.slice(0,3)">#{{ k }} </template>
            </span>
          </div>
          <div v-if="currentSession.material" class="panel-section">
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
            <div class="gaps-banner-title" v-html="icon('clip') + ' 待解决薄弱点（' + unresolvedGaps.length + '）'"></div>
            <ul class="gaps-summary">
              <li v-for="g in unresolvedGaps.slice(0, 8)">{{ g.gap }} <span class="muted small">→ 第{{ g.seq }}轮</span></li>
            </ul>
          </div>
          
          <!-- Rounds -->
          <div v-if="currentRounds.filter(r => r.type === 'take' || r.type === 'press').length" class="deepen-history">
            <div v-for="r in currentRounds.filter(r => r.type === 'take' || r.type === 'press')" :key="r.id" :class="['round-card', r.type === 'take' ? 'round-take' : 'round-press']">
              <div class="round-user-wrap">
                <span class="round-label" v-html="r.type === 'take' ? icon('bulb') + ' 理解' : icon('search') + ' 追问'"></span>
                <span class="round-user">{{ r.input || '' }}</span>
              </div>
              <div class="round-ai md-body">
                <div class="ps-label">AI {{ r.type === 'take' ? '评价' : '回答' }}</div>
                <div v-html="renderMarkdown(r.output || '')"></div>
              </div>
            </div>
          </div>
          
          <!-- Inputs -->
          <div v-if="canDeepen" class="deepen-inputs">
            <div class="deepen-col">
              <div class="col-label muted small" v-html="icon('search') + ' 提追问'"></div>
              <textarea v-model="questionInput" rows="4" placeholder="追问某个细节、反例、边界条件…"></textarea>
              <button class="btn btn-primary btn-block mt8" :disabled="submitting" @click="submitDeepAction('press')">提交追问</button>
            </div>
            <div class="deepen-col">
              <div class="col-label muted small" v-html="icon('edit') + ' 写理解'"></div>
              <textarea v-model="takeInput" rows="4" placeholder="用自己的话说说你对 AI 回答的理解，有没有偏差 AI 会告诉你…"></textarea>
              <button class="btn btn-primary btn-block mt8" :disabled="submitting" @click="submitDeepAction('take')">提交理解</button>
            </div>
          </div>
          <button v-if="canDeepen" class="btn btn-success btn-block mt12" :disabled="submitting" @click="startFeynman" v-html="icon('check') + ' 差不多了，开始费曼检验'"></button>
        </div>
        
        <!-- Review Panel -->
        <div v-show="activeTab === 'review'" class="panel-content">
          <!-- Completed summary -->
          <div v-if="currentSession.status === 'completed'" class="panel-section completed-summary">
            <div class="final-score-row">
              <span class="final-score-num">{{ currentSession.score || 0 }}/100</span>
              <span class="stage-badge stage-completed">已完成</span>
            </div>
            <div v-if="reviewReport" class="review-report">
              <div class="report-row"><span class="report-label">掌握度</span><span class="report-value">{{ reviewReport.mastery_level || '—' }}</span></div>
              <div v-if="reviewReport.final_summary" class="report-summary md-body" v-html="renderMarkdown(reviewReport.final_summary)"></div>
              <div v-if="reviewReport.strong_points?.length" class="report-section">
                <div class="report-label" v-html="icon('check') + ' 理解到位的点'"></div>
                <ul class="report-list good"><li v-for="p in reviewReport.strong_points">{{ p }}</li></ul>
              </div>
              <div v-if="reviewReport.weak_points?.length" class="report-section">
                <div class="report-label" v-html="icon('edit') + ' 还需加强'"></div>
                <ul class="report-list weak"><li v-for="p in reviewReport.weak_points">{{ p }}</li></ul>
              </div>
            </div>
          </div>
          
          <!-- Active Feynman -->
          <div v-if="feynmanGroup.length && currentSession.status === 'feynman'" class="panel-section">
            <div class="ps-label" v-html="icon('flask') + ' 费曼检验'"></div>
            <div class="ps-hint muted small mb12">用自己的话回答，AI 会评估你的掌握程度。</div>
            <div v-for="(q, i) in feynmanGroup" :key="q.id" class="review-q">
              <div class="review-q-title">Q{{ i+1 }}. {{ q.input || '' }}</div>
              <textarea class="review-answer" rows="4" :placeholder="'用自己的话回答…'" v-model="feynmanAnswers[i]"></textarea>
            </div>
            <button class="btn btn-primary btn-block mt8" :disabled="submitting" @click="submitFeynman" v-html="icon('chart') + ' 提交答案'"></button>
          </div>
        </div>
      </template>
    </div>
  `,
});
