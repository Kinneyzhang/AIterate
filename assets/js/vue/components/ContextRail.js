// ── ContextRail.js ── 当前学习上下文右侧栏 ───────────────────────────────

import { defineComponent, computed } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { store, currentSession, currentRounds, unresolvedGaps, reviewReport, knowledgeNode, getStageMeta, setNotice } from '../store.js';
import { api } from '../api.js';

export default defineComponent({
  emits: ['refresh'],

  setup(props, { emit }) {
    const router = useRouter();
    const route = useRoute();

    const icons = {
      bulb: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/></svg>',
      book: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
      refresh: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
      flask: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h6v5l5.45 9.54A2 2 0 0 1 18.73 21H5.27a2 2 0 0 1-1.72-3.46L9 8V3z"/><line x1="9" y1="3" x2="9" y2="8"/><line x1="15" y1="3" x2="15" y2="8"/></svg>',
      chart: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>',
      tag: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></svg>',
      clip: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>',
    };

    const reviewSchedule = computed(() => store.workspace?.review_schedule || []);
    const hasTakeRound = computed(() => currentRounds.value.some(r => r.type === 'take'));
    const canEditDeepen = computed(() => {
      const s = currentSession.value?.status;
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
    const contextScore = computed(() => {
      const report = reviewReport.value || {};
      const session = currentSession.value || {};
      const latestTake = [...currentRounds.value].reverse().find(r => r.type === 'take' && r.score != null);
      const score = report.final_score ?? session.score ?? latestTake?.score;
      return score != null ? `${score}/100` : '暂无';
    });
    const contextRoundCount = computed(() => currentRounds.value.filter(r => r.type === 'take' || r.type === 'press').length);
    const pendingReviewCount = computed(() => reviewSchedule.value.filter(r => r.status === 'pending').length);
    const canCompleteEarly = computed(() => ['learning', 'deepening', 'revising', 'feynman'].includes(currentSession.value?.status));

    function switchTab(tab) {
      const id = store.selectedSessionId;
      if (!id) return;
      const nameMap = { learn: 'session-learn', deepen: 'session-deepen', review: 'session-review' };
      router.push({ name: nameMap[tab], params: { id } });
    }

    // #5: gap 一键转追问
    function fillGapAsQuestion(gap) {
      const text = typeof gap === 'string' ? gap : (gap.gap || gap.text || '');
      store.prefillQuestion = '关于这个薄弱点：' + text + ' —— 请帮我理清这个概念。';
      switchTab('deepen');
    }

    function openKnowledgeTree() {
      router.push({ name: 'knowledge-tree' });
    }

    async function startFeynman() {
      const sid = store.selectedSessionId;
      if (!sid) return;
      try {
        await api.startFeynman(sid);
        emit('refresh');
        setNotice('费曼题已生成，开始费曼检验。');
      } catch (err) {
        setNotice(`启动费曼失败：${err.message}`, 'error');
      }
    }

    async function completeEarly() {
      const sid = store.selectedSessionId;
      if (!sid) return;
      if (!window.confirm('确定提前结束这个学习会话？')) return;
      try {
        await api.completeSession(sid);
        emit('refresh');
        setNotice('已提前结束，进入复习队列。');
      } catch (err) {
        setNotice(`提前结束失败：${err.message}`, 'error');
      }
    }

    return {
      currentSession, currentRounds, unresolvedGaps, knowledgeNode,
      reviewSchedule, hasTakeRound, canEditDeepen, canDeepen, canReview,
      contextScore, contextRoundCount, pendingReviewCount, canCompleteEarly,
      switchTab, openKnowledgeTree, startFeynman, completeEarly, getStageMeta, icons,
      fillGapAsQuestion,
      route,
    };
  },

  template: `
    <aside v-if="currentSession" class="context-rail" aria-label="当前学习上下文">
      <section class="context-card context-stage-card">
        <div class="context-card-title" v-html="icons.chart + ' 当前阶段'"></div>
        <div class="context-stage-row">
          <span :class="['stage-badge', getStageMeta(currentSession.status).cls]">{{ getStageMeta(currentSession.status).label }}</span>
          <span class="context-score">{{ contextScore }}</span>
        </div>
        <div class="context-meta-line">
          <span>{{ currentSession.type === 'viewpoint' ? '观点' : '问题' }}</span>
          <span>深化 {{ contextRoundCount }} 轮</span>
          <span v-if="pendingReviewCount">待复习 {{ pendingReviewCount }}</span>
        </div>
        <button v-if="knowledgeNode" type="button" class="context-node btn" @click="openKnowledgeTree">
          <span v-html="icons.tag"></span><span>{{ knowledgeNode.title }}</span>
        </button>
        <button v-else type="button" class="context-node context-node-empty btn" @click="openKnowledgeTree" v-html="icons.tag + ' 关联知识节点'"></button>
      </section>

      <section class="context-card context-gaps-card">
        <div class="context-card-title" v-html="icons.clip + ' 未解决薄弱点'"></div>
        <template v-if="unresolvedGaps.length">
          <button v-for="g in unresolvedGaps.slice(0, 5)" :key="g.id || g.gap" type="button" class="context-gap-item btn" @click="fillGapAsQuestion(g)">
            <span class="context-gap-text">{{ g.gap }}</span>
            <small v-if="g.seq">第{{ g.seq }}轮</small>
            <span class="context-gap-arrow">→追问</span>
          </button>
          <button v-if="unresolvedGaps.length > 5" type="button" class="context-more-btn btn" @click="switchTab('deepen')">还有 {{ unresolvedGaps.length - 5 }} 个，去深化页查看</button>
        </template>
        <div v-else class="context-empty">暂无薄弱点，继续写理解或进入费曼。</div>
      </section>

      <section class="context-card context-actions-card">
        <div class="context-card-title" v-html="icons.bulb + ' 建议动作'"></div>
        <div class="context-action-list">
          <button v-if="unresolvedGaps.length" type="button" class="btn btn-primary btn-block btn-sm" @click="switchTab('deepen')">追问薄弱点</button>
          <button v-if="canEditDeepen" type="button" class="btn btn-primary btn-block btn-sm" @click="switchTab('deepen')">写一轮理解</button>
          <button v-if="canEditDeepen && hasTakeRound" type="button" class="btn btn-success btn-block btn-sm" @click="startFeynman">开始费曼检验</button>
          <button v-if="currentSession.status === 'feynman'" type="button" class="btn btn-primary btn-block btn-sm" @click="switchTab('review')">回答费曼题</button>
          <button v-if="canCompleteEarly" type="button" class="btn btn-sm btn-block" @click="completeEarly">提前结束</button>
          <button v-if="pendingReviewCount" type="button" class="btn btn-primary btn-block btn-sm" @click="switchTab('review')">完成今日复习</button>
          <button type="button" class="btn btn-sm btn-block" @click="openKnowledgeTree">查看知识树</button>
        </div>
      </section>

      <section class="context-card context-nav-card">
        <div class="context-card-title" v-html="icons.book + ' 本页导航'"></div>
        <button type="button" :class="['context-nav-item', 'btn', { active: route.name === 'session-learn' }]" @click="switchTab('learn')">学习材料</button>
        <button type="button" :class="['context-nav-item', 'btn', { active: route.name === 'session-deepen' }]" :disabled="!canDeepen" @click="switchTab('deepen')">理解 / 追问</button>
        <button type="button" :class="['context-nav-item', 'btn', { active: route.name === 'session-review' }]" :disabled="!canReview" @click="switchTab('review')">费曼 / 复习</button>
      </section>
    </aside>
  `,
});
