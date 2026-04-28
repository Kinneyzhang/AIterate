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
    const selectedBatchIds = ref([]);
    const collectMode = ref('questions');
    const sourceUrl = ref('');
    const urlFetching = ref(false);
    const voiceListening = ref(false);
    const imagePreview = ref('');
    const imageName = ref('');
    const domainOptions = ref(['计算机', '写作', '心理学', '哲学']);
    const modeOptions = [
      {
        value: 'questions',
        label: '生成问题',
        hint: '转成可学习的问题',
        prompt: '请把素材转化为可进入学习流程的研究问题，问题要具体、可回答、能引出核心概念。',
      },
      {
        value: 'counter',
        label: '找反例',
        hint: '暴露边界和漏洞',
        prompt: '请优先从反例、边界条件、失败场景、隐藏假设入手生成问题，帮助我避免过早相信这个观点。',
      },
      {
        value: 'summary',
        label: '提炼要点',
        hint: '压缩成结构化笔记',
        prompt: '请先提炼素材中的概念、论点、证据和疑问，再生成适合继续学习或写作的候选问题。',
      },
      {
        value: 'action',
        label: '行动实验',
        hint: '变成下一步实践',
        prompt: '请把素材转化为可执行的小实验、验证步骤或下一步行动，并生成围绕行动可行性的候选问题。',
      },
      {
        value: 'writing',
        label: '写作素材',
        hint: '变成观点和例子',
        prompt: '请把素材拆成可写作的观点、例子、金句、论证路径，并生成能扩展文章的候选问题。',
      },
      {
        value: 'feynman',
        label: '费曼检验',
        hint: '检查我是否真懂',
        prompt: '请围绕素材生成能检验理解的费曼式问题，偏向解释、举例、类比和反驳。',
      },
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
    const selectedBatchItems = computed(() => pendingItems.value.filter(x => selectedBatchIds.value.includes(x.id)));
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

    function toggleBatchItem(id) {
      selectedBatchIds.value = selectedBatchIds.value.includes(id)
        ? selectedBatchIds.value.filter(x => x !== id)
        : [...selectedBatchIds.value, id];
    }

    function clearBatchSelection() {
      selectedBatchIds.value = [];
    }

    async function archiveSelectedBatch() {
      const targets = selectedBatchItems.value;
      if (!targets.length || actionBusy.value.batchArchive) return;
      actionBusy.value.batchArchive = true;
      try {
        await Promise.all(targets.map(x => api.archiveInboxItem(x.id)));
        selectedBatchIds.value = [];
        await loadList();
        emit('refresh');
        setNotice(`已完成 ${targets.length} 条素材。`);
      } catch (err) {
        setNotice(`批量完成失败：${err.message}`, 'error');
      } finally {
        actionBusy.value.batchArchive = false;
      }
    }

    async function mergeSelectedBatch() {
      const targets = selectedBatchItems.value;
      if (targets.length < 2 || actionBusy.value.batchMerge) return;
      actionBusy.value.batchMerge = true;
      try {
        const content = targets.map((x, i) => `素材 ${i + 1}：\n${x.content}`).join('\n\n---\n\n');
        const created = await api.createInboxItem(content, 'text', {
          direction: `${buildPageDirection()}；批量处理：请把多条素材合并成一个更高价值的问题簇，识别共同主题、冲突点和可行动方向。`,
        });
        selectedBatchIds.value = [];
        await loadList();
        emit('refresh');
        setNotice('已合并为一条批量素材，AI 正在生成候选问题。');
        router.push({ name: 'inbox-item', params: { id: created.id } });
      } catch (err) {
        setNotice(`批量合并失败：${err.message}`, 'error');
      } finally {
        actionBusy.value.batchMerge = false;
      }
    }

    function toggleDomain(domain) {
      selectedDomains.value = selectedDomains.value.includes(domain)
        ? selectedDomains.value.filter(x => x !== domain)
        : [...selectedDomains.value, domain];
    }

    function buildPageDirection() {
      const mode = modeOptions.find(x => x.value === collectMode.value) || modeOptions[0];
      const domains = selectedDomains.value.length ? selectedDomains.value.join('、') : '跨学科';
      const extra = pageDirection.value.trim();
      return [
        `领域：${domains}`,
        `处理模板：${mode.label}`,
        `模板提示词：${mode.prompt}`,
        extra ? `额外要求：${extra}` : '',
      ].filter(Boolean).join('；');
    }

    async function loadDomainOptions() {
      try {
        const data = await api.getKnowledgeTree();
        const titles = (data.tree || [])
          .map(node => (node.title || '').trim())
          .filter(Boolean);
        if (titles.length) domainOptions.value = titles.slice(0, 8);
      } catch (_) {
        // 领域只是预设入口，知识树加载失败时保留本地兜底，不打断收集。
      }
    }

    async function importUrlToComposer() {
      const url = sourceUrl.value.trim();
      if (!url || urlFetching.value) return;
      urlFetching.value = true;
      try {
        const data = await api.extractInboxUrl(url);
        const title = data.title ? `标题：${data.title}\n` : '';
        pageContent.value = `${title}来源：${data.url}\n\n${data.content}`.trim();
        sourceUrl.value = '';
        setNotice('链接正文已抓取，检查后可放入收集箱。');
      } catch (err) {
        setNotice(`链接抓取失败：${err.message}`, 'error');
      } finally {
        urlFetching.value = false;
      }
    }

    function startVoiceInput() {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRecognition) {
        setNotice('当前浏览器不支持语音输入，可先用系统输入法语音转文字。', 'error');
        return;
      }
      const recognition = new SpeechRecognition();
      recognition.lang = 'zh-CN';
      recognition.interimResults = false;
      recognition.continuous = false;
      voiceListening.value = true;
      recognition.onresult = (event) => {
        const transcript = Array.from(event.results || [])
          .map(result => result[0]?.transcript || '')
          .join('')
          .trim();
        if (transcript) {
          pageContent.value = [pageContent.value.trim(), transcript].filter(Boolean).join('\n\n');
        }
      };
      recognition.onerror = (event) => {
        setNotice(`语音输入失败：${event.error || '未知错误'}`, 'error');
      };
      recognition.onend = () => { voiceListening.value = false; };
      recognition.start();
    }

    function handleImageFile(file) {
      if (!file || !file.type?.startsWith('image/')) return;
      imageName.value = file.name || 'clipboard-image.png';
      const reader = new FileReader();
      reader.onload = () => { imagePreview.value = String(reader.result || ''); };
      reader.readAsDataURL(file);
      const imageNote = `图片素材：${imageName.value}\n请围绕这张图片对应的信息生成候选问题。若图片里有文字，我会在这里补充关键内容。`;
      if (!pageContent.value.trim()) pageContent.value = imageNote;
      setNotice('图片已捕获到收集区；当前先保留预览和说明，精确 OCR 需要后续配置识别引擎。');
    }

    function handleImageInput(event) {
      handleImageFile(event.target.files?.[0]);
      event.target.value = '';
    }

    function handlePagePaste(event) {
      const file = Array.from(event.clipboardData?.files || []).find(x => x.type?.startsWith('image/'));
      if (file) handleImageFile(file);
    }

    async function submitPageCollection() {
      const text = pageContent.value.trim();
      if (!text || pageSubmitting.value) return;
      pageSubmitting.value = true;
      try {
        const created = await api.createInboxItem(text, 'text', { direction: buildPageDirection() });
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
    onMounted(() => {
      loadDomainOptions();
      loadCurrent();
    });
    onUnmounted(stopPolling);

    return {
      items, pendingItems, completedItems, visibleItems, readyItems, generatingItems, errorItems, selectedBatchItems,
      item, questions, loading, actionBusy, direction, router, icon,
      pageContent, pageDirection, pageSubmitting, selectedDomains, selectedBatchIds, collectMode,
      sourceUrl, urlFetching, voiceListening, imagePreview, imageName, domainOptions, modeOptions,
      statusLabel, depthLabel, toggleDomain, toggleBatchItem, clearBatchSelection, archiveSelectedBatch, mergeSelectedBatch, buildPageDirection, loadDomainOptions,
      importUrlToComposer, startVoiceInput, handleImageInput, handlePagePaste, submitPageCollection, handlePageKeydown,
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
            <div class="inbox-source-tools">
              <div class="inbox-url-import">
                <input type="url" v-model="sourceUrl" placeholder="粘贴文章/网页链接，先抓正文再加工…" @keydown.enter.prevent="importUrlToComposer" />
                <button type="button" class="btn" :disabled="!sourceUrl.trim() || urlFetching" @click="importUrlToComposer">{{ urlFetching ? '抓取中' : '抓取链接' }}</button>
              </div>
              <button type="button" class="btn inbox-source-tool-btn" :class="{ active: voiceListening }" @click="startVoiceInput">{{ voiceListening ? '正在听…' : '语音输入' }}</button>
              <label class="btn inbox-source-tool-btn">贴图片
                <input type="file" accept="image/*" class="visually-hidden" @change="handleImageInput" />
              </label>
            </div>
            <div v-if="imagePreview" class="inbox-image-preview">
              <img :src="imagePreview" :alt="imageName" />
              <span>{{ imageName }}</span>
            </div>
            <div class="inbox-page-compose-grid">
              <textarea
                class="inbox-page-input"
                v-model="pageContent"
                rows="5"
                placeholder="粘贴摘录、链接、想法，或写下一个还没成型的灵感…"
                :disabled="pageSubmitting"
                @keydown="handlePageKeydown"
                @paste="handlePagePaste"></textarea>
              <div class="inbox-compose-side">
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
            <div v-if="pendingItems.length" class="inbox-batch-toolbar">
              <span>{{ selectedBatchItems.length ? '已选 ' + selectedBatchItems.length + ' 条' : '可多选后批量加工' }}</span>
              <div>
                <button type="button" class="btn" :disabled="selectedBatchItems.length < 2 || actionBusy.batchMerge" @click="mergeSelectedBatch">合并加工</button>
                <button type="button" class="btn btn-ghost" :disabled="!selectedBatchItems.length || actionBusy.batchArchive" @click="archiveSelectedBatch">批量完成</button>
                <button v-if="selectedBatchItems.length" type="button" class="btn btn-ghost" @click="clearBatchSelection">清空</button>
              </div>
            </div>
            <article v-for="x in pendingItems" :key="'pending-'+x.id" class="inbox-material-card batchable clickable" tabindex="0" @click="openItem(x)" @keydown.enter.prevent="openItem(x)" @keydown.space.prevent="openItem(x)">
              <input type="checkbox" class="inbox-batch-check" :checked="selectedBatchIds.includes(x.id)" @click.stop.prevent="toggleBatchItem(x.id)" aria-label="选择素材" />
              <div class="inbox-material-main">
                <div class="inbox-material-line">
                  <span class="inbox-material-title">{{ x.content }}</span>
                  <span :class="['inbox-list-status', 'is-' + x.status]">{{ statusLabel(x.status) }} · {{ x.question_count || 0 }} 个问题</span>
                </div>
              </div>
              <div class="inbox-material-actions">
                <button type="button" class="btn btn-ghost inbox-batch-toggle" @click.stop="toggleBatchItem(x.id)">{{ selectedBatchIds.includes(x.id) ? '已选' : '选择' }}</button>
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
