// ── InboxPanel.js ── 收集箱工作区 ────────────────────────────────────────

import { defineComponent, ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { icon } from '../icons.js';
import { store, setNotice } from '../store.js';

export default defineComponent({
  emits: ['refresh'],

  setup(props, { emit }) {
    const route = useRoute();
    const router = useRouter();
    const items = ref([]);
    const item = ref(null);
    const questions = ref([]);
    const loading = ref(false);
    const actionBusy = ref({});
    const direction = ref('');
    const pageContent = ref('');
    const pageDirection = ref('');
    const pageSubmitting = ref(false);
    const selectedDomains = ref([]);
    const collectMode = ref('questions');
    const sourceType = ref('text');
    const domainOptions = ['计算机', '写作', '心理学', '哲学'];
    const modeOptions = [
      { value: 'questions', label: '生成问题', hint: '转成可学习的问题' },
      { value: 'counter', label: '找反例', hint: '优先暴露边界和漏洞' },
      { value: 'summary', label: '提炼要点', hint: '先压缩成结构化笔记' },
      { value: 'action', label: '行动化', hint: '提炼成下一步实验' },
    ];
    const sourceOptions = [
      { value: 'text', label: '想法' },
      { value: 'quote', label: '摘录' },
      { value: 'url', label: '链接' },
    ];
    let pollTimer = null;

    const isInboxRoute = computed(() => route.name === 'inbox' || route.name === 'inbox-item');
    const itemId = computed(() => route.name === 'inbox-item' && route.params.id ? Number(route.params.id) : null);
    const pendingItems = computed(() => items.value.filter(x => ['pending', 'generating', 'ready', 'error'].includes(x.status)));
    const completedItems = computed(() => items.value.filter(x => ['partially_used', 'archived', 'ignored'].includes(x.status)));
    const visibleItems = pendingItems;
    const readyItems = computed(() => pendingItems.value.filter(x => x.status === 'ready'));
    const generatingItems = computed(() => pendingItems.value.filter(x => ['pending', 'generating'].includes(x.status)));
    const errorItems = computed(() => pendingItems.value.filter(x => x.status === 'error'));
    const activeItems = computed(() => pendingItems.value.some(x => ['pending', 'generating'].includes(x.status)) || ['pending', 'generating'].includes(item.value?.status));

    function statusLabel(status) {
      return {
        pending: '待生成',
        generating: '生成中',
        ready: '已生成',
        partially_used: '已完成',
        archived: '已完成',
        ignored: '已忽略',
        error: '失败',
      }[status] || status || '未知';
    }

    function depthLabel(depth) {
      return { low: '浅', medium: '中', high: '深' }[depth] || depth || '中';
    }

    function toggleDomain(domain) {
      selectedDomains.value = selectedDomains.value.includes(domain)
        ? selectedDomains.value.filter(x => x !== domain)
        : [...selectedDomains.value, domain];
    }

    function buildPageDirection() {
      const mode = modeOptions.find(x => x.value === collectMode.value)?.label || '生成问题';
      const domains = selectedDomains.value.length ? selectedDomains.value.join('、') : '跨学科';
      const extra = pageDirection.value.trim();
      return [`领域：${domains}`, `处理方式：${mode}`, extra ? `额外要求：${extra}` : ''].filter(Boolean).join('；');
    }

    async function submitPageCollection() {
      const text = pageContent.value.trim();
      if (!text || pageSubmitting.value) return;
      pageSubmitting.value = true;
      try {
        const created = await api.createInboxItem(text, sourceType.value, { direction: buildPageDirection() });
        pageContent.value = '';
        pageDirection.value = '';
        setNotice('已按预设放入收集箱，AI 正在生成候选问题。');
        await loadList();
        emit('refresh');
        router.push({ name: 'inbox-item', params: { id: created.id } });
      } catch (err) {
        setNotice(`收集失败：${err.message}`, 'error');
      } finally {
        pageSubmitting.value = false;
      }
    }

    function handlePageKeydown(event) {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        submitPageCollection();
      }
    }

    async function loadList() {
      items.value = await api.getInboxItems(200);
      store.inboxItems = items.value;
    }

    async function loadCurrent() {
      if (!isInboxRoute.value) return;
      loading.value = true;
      try {
        await loadList();
        if (itemId.value) {
          const detail = await api.getInboxItem(itemId.value);
          item.value = detail.item;
          questions.value = detail.questions || [];
        } else {
          item.value = null;
          questions.value = [];
        }
        if (activeItems.value) startPolling();
        else stopPolling();
      } catch (err) {
        setNotice(`加载收集箱失败：${err.message}`, 'error');
      } finally {
        loading.value = false;
      }
    }

    function startPolling() {
      if (pollTimer) return;
      pollTimer = setInterval(loadCurrent, 2200);
    }

    function stopPolling() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function openItem(next) {
      if (!next?.id) return;
      router.push({ name: 'inbox-item', params: { id: next.id } });
    }

    async function regenerate(dir = null) {
      if (!item.value?.id) return;
      const text = (dir ?? direction.value).trim ? (dir ?? direction.value).trim() : dir;
      actionBusy.value.regenerate = true;
      try {
        await api.regenerateInboxQuestions(item.value.id, text || null);
        direction.value = '';
        setNotice('已重新生成，稍等几秒刷新。');
        await loadCurrent();
        startPolling();
      } catch (err) {
        setNotice(`重新生成失败：${err.message}`, 'error');
      } finally {
        actionBusy.value.regenerate = false;
      }
    }

    async function selectQuestion(q) {
      if (!q?.id || actionBusy.value[`select-${q.id}`]) return;
      actionBusy.value[`select-${q.id}`] = true;
      try {
        const result = await api.selectInboxQuestion(q.id, { web_search: false, knowledge_node_id: null });
        emit('refresh');
        router.push({ name: 'session-learn', params: { id: result.session_id } });
      } catch (err) {
        setNotice(`创建学习会话失败：${err.message}`, 'error');
      } finally {
        actionBusy.value[`select-${q.id}`] = false;
      }
    }

    async function ignoreQuestion(q) {
      if (!q?.id) return;
      actionBusy.value[`ignore-${q.id}`] = true;
      try {
        await api.ignoreInboxQuestion(q.id);
        questions.value = questions.value.map(x => x.id === q.id ? { ...x, status: 'ignored' } : x);
      } catch (err) {
        setNotice(`忽略失败：${err.message}`, 'error');
      } finally {
        actionBusy.value[`ignore-${q.id}`] = false;
      }
    }

    async function archiveItem(target = null) {
      const targetItem = target || item.value;
      if (!targetItem?.id || actionBusy.value[`archive-${targetItem.id}`]) return;
      actionBusy.value[`archive-${targetItem.id}`] = true;
      try {
        await api.archiveInboxItem(targetItem.id);
        setNotice('已标记完成。');
        if (item.value?.id === targetItem.id) router.push({ name: 'inbox' });
        await loadCurrent();
      } catch (err) {
        setNotice(`标记完成失败：${err.message}`, 'error');
      } finally {
        actionBusy.value[`archive-${targetItem.id}`] = false;
      }
    }

    watch(() => route.fullPath, loadCurrent);
    onMounted(loadCurrent);
    onUnmounted(stopPolling);

    return {
      items, pendingItems, completedItems, visibleItems, readyItems, generatingItems, errorItems,
      item, questions, loading, actionBusy, direction, router, icon,
      pageContent, pageDirection, pageSubmitting, selectedDomains, collectMode, sourceType,
      domainOptions, modeOptions, sourceOptions,
      statusLabel, depthLabel, toggleDomain, buildPageDirection, submitPageCollection, handlePageKeydown,
      openItem, regenerate, selectQuestion, ignoreQuestion, archiveItem,
    };
  },

  template: `
    <div class="inbox-panel">
      <section :class="['inbox-detail-pane', { 'is-overview': !item }]">
        <div v-if="loading && !item" class="empty-state">加载中…</div>
        <div v-else-if="!item" class="inbox-overview">
          <div class="inbox-overview-kicker">INBOX</div>
          <h2>收集箱</h2>
          <p>零碎素材先放这里，处理成问题后进入学习；没价值的直接点「完成」。</p>

          <section class="inbox-page-composer">
            <div class="inbox-page-composer-head">
              <div class="home-section-title" v-html="icon('edit') + ' 深度收集'"></div>
              <span>给素材预设处理方向，不只是快速捕获</span>
            </div>
            <div class="inbox-page-compose-grid">
              <textarea
                class="inbox-page-input"
                v-model="pageContent"
                rows="5"
                placeholder="粘贴摘录、链接、想法，或写下一个还没成型的灵感…"
                :disabled="pageSubmitting"
                @keydown="handlePageKeydown"></textarea>
              <div class="inbox-compose-side">
                <div class="inbox-compose-option-row">
                  <span class="inbox-compose-label">素材类型</span>
                  <div class="inbox-chip-row">
                    <button v-for="opt in sourceOptions" :key="opt.value" type="button" :class="['btn', 'inbox-chip', { active: sourceType === opt.value }]" @click="sourceType = opt.value">{{ opt.label }}</button>
                  </div>
                </div>
                <div class="inbox-compose-option-row">
                  <span class="inbox-compose-label">处理方式</span>
                  <div class="inbox-compose-mode-list">
                    <button v-for="opt in modeOptions" :key="opt.value" type="button" :class="['btn', 'inbox-mode-chip', { active: collectMode === opt.value }]" @click="collectMode = opt.value">
                      <strong>{{ opt.label }}</strong><small>{{ opt.hint }}</small>
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <div class="inbox-compose-option-row is-domains">
              <span class="inbox-compose-label">回答领域</span>
              <div class="inbox-compose-domain-grid">
                <button v-for="domain in domainOptions" :key="domain" type="button" :class="['btn', 'inbox-chip', { active: selectedDomains.includes(domain) }]" @click="toggleDomain(domain)">{{ domain }}</button>
              </div>
            </div>
            <div class="inbox-compose-footer">
              <input type="text" v-model="pageDirection" placeholder="额外要求：更偏工程实践 / 反例 / 长期价值…" @keydown.enter.prevent="submitPageCollection" />
              <button type="button" class="btn btn-primary" :disabled="!pageContent.trim() || pageSubmitting" @click="submitPageCollection">
                {{ pageSubmitting ? '提交中' : '放入收集箱' }}
              </button>
            </div>
          </section>

          <section class="inbox-overview-section">
            <div class="inbox-section-head">
              <div class="home-section-title" v-html="icon('clip') + ' 待处理素材'"></div>
              <span>{{ pendingItems.length }} 条</span>
            </div>
            <article v-for="x in pendingItems" :key="'pending-'+x.id" class="inbox-material-card clickable" tabindex="0" @click="openItem(x)" @keydown.enter.prevent="openItem(x)" @keydown.space.prevent="openItem(x)">
              <div class="inbox-material-main">
                <div class="inbox-material-line">
                  <span class="inbox-material-title">{{ x.content }}</span>
                  <span :class="['inbox-list-status', 'is-' + x.status]">{{ statusLabel(x.status) }} · {{ x.question_count || 0 }} 个问题</span>
                </div>
              </div>
              <div class="inbox-material-actions">
                <button type="button" class="btn btn-primary" @click.stop="openItem(x)">处理</button>
                <button type="button" class="btn btn-ghost" :disabled="actionBusy['archive-' + x.id]" @click.stop="archiveItem(x)">完成</button>
              </div>
            </article>
            <div v-if="!pendingItems.length" class="inbox-overview-empty">没有待处理素材。看到一个词、一句话，直接在左侧收集。</div>
          </section>

          <section class="inbox-overview-section inbox-completed-section">
            <div class="inbox-section-head">
              <div class="home-section-title" v-html="icon('refresh') + ' 历史素材'"></div>
              <span>共 {{ completedItems.length }} 条</span>
            </div>
            <article v-for="x in completedItems" :key="'done-'+x.id" class="inbox-material-card done clickable" tabindex="0" @click="openItem(x)" @keydown.enter.prevent="openItem(x)" @keydown.space.prevent="openItem(x)">
              <div class="inbox-material-main">
                <div class="inbox-material-line">
                  <span class="inbox-material-title">{{ x.content }}</span>
                  <span :class="['inbox-list-status', 'is-' + x.status]">{{ statusLabel(x.status) }} · {{ x.question_count || 0 }} 个问题</span>
                </div>
              </div>
              <button type="button" class="btn btn-ghost" @click.stop="openItem(x)">查看</button>
            </article>
            <div v-if="!completedItems.length" class="inbox-overview-empty">暂无历史素材。</div>
          </section>
        </div>
        <template v-else>
          <header class="inbox-detail-header">
            <div>
              <div class="inbox-breadcrumb">
                <button type="button" class="inbox-breadcrumb-link" @click="router.push({ name: 'inbox' })">收集箱</button>
                <span>/ {{ statusLabel(item.status) }}</span>
              </div>
              <h2>{{ item.content }}</h2>
            </div>
            <button type="button" class="btn btn-ghost" @click="archiveItem()">完成</button>
          </header>

          <div v-if="item.error_msg" class="inbox-error">{{ item.error_msg }}</div>
          <div v-if="['pending','generating'].includes(item.status)" class="inbox-generating">
            AI 正在把这条素材加工成候选问题…
          </div>

          <section class="inbox-source-block">
            <div class="ps-label">原始素材</div>
            <div class="inbox-source-text">{{ item.content }}</div>
          </section>

          <section class="inbox-regenerate-row">
            <input type="text" v-model="direction" placeholder="可选：更偏心理学 / 技术 / 哲学..." @keydown.enter.prevent="regenerate()" />
            <button type="button" class="btn" :disabled="actionBusy.regenerate" @click="regenerate()">换一批问题</button>
          </section>

          <div class="inbox-question-list">
            <article v-for="q in questions" :key="q.id" :class="['inbox-question-card', 'is-' + q.status]">
              <div class="inbox-question-main">
                <div class="inbox-question-title">{{ q.question }}</div>
                <p v-if="q.why" class="inbox-question-why">{{ q.why }}</p>
                <div class="inbox-question-meta">
                  <span>{{ q.angle || '跨学科' }}</span>
                  <span>{{ depthLabel(q.depth) }}深度</span>
                  <span v-for="c in (q.related_concepts || [])" :key="c">{{ c }}</span>
                </div>
              </div>
              <div class="inbox-question-actions">
                <button v-if="q.status !== 'selected'" type="button" class="btn btn-primary" :disabled="actionBusy['select-' + q.id]" @click="selectQuestion(q)">开始学习</button>
                <button v-else type="button" class="btn btn-success" @click="router.push({ name: 'session-learn', params: { id: q.session_id } })">查看学习</button>
                <button v-if="q.status === 'candidate'" type="button" class="btn btn-ghost" :disabled="actionBusy['ignore-' + q.id]" @click="ignoreQuestion(q)">忽略</button>
              </div>
            </article>
            <div v-if="!questions.length && !['pending','generating'].includes(item.status)" class="inbox-empty-small">还没有生成问题。</div>
          </div>
        </template>
      </section>

      <aside class="inbox-list-pane">
        <template v-if="item">
          <div class="inbox-panel-title">待处理素材</div>
          <div class="inbox-panel-subtitle">当前还没完成的碎片</div>
          <div v-if="!pendingItems.length && !loading" class="inbox-empty-small">暂无待处理素材</div>
          <button v-for="x in pendingItems" :key="x.id" type="button"
                  :class="['inbox-list-item', { active: item && item.id === x.id }]"
                  @click="openItem(x)">
            <span class="inbox-list-title">{{ x.content }}</span>
            <span :class="['inbox-list-status', 'is-' + x.status]">{{ statusLabel(x.status) }} · {{ x.question_count || 0 }}</span>
          </button>
        </template>
        <template v-else>
          <div class="inbox-panel-title">处理规则</div>
          <div class="inbox-panel-subtitle">收集箱不是仓库，是素材加工台</div>
          <div class="inbox-rail-note">
            <p><strong>处理</strong>：打开候选问题，选择一个进入学习。</p>
            <p><strong>完成</strong>：这条素材不再需要推进，移到已处理。</p>
            <p><strong>已处理</strong>：留在页面下方备查，不占主待办。</p>
          </div>
        </template>
      </aside>
    </div>
  `,
});
