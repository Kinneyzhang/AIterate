// ── InboxPanel.js ── 收集箱工作区 ────────────────────────────────────────

import { defineComponent, ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { api } from '../api.js';
import { icon } from '../icons.js';
import { store, setNotice, askConfirm } from '../store.js';

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
    const pageSubmitting = ref(false);
    const selectedDomains = ref([]);
    const sourceUrl = ref('');
    const urlFetching = ref(false);
    const voiceListening = ref(false);
    const imagePreview = ref('');
    const imageName = ref('');
    const domainOptions = ref(['计算机', '写作', '心理学', '哲学']);
    let pollTimer = null;
    let lastProcessingNoticeKey = '';
    let recsPollTimer = null;
    const recommendations = ref([]);
    const recsGenerating = ref(false);

    const isInboxRoute = computed(() => route.name === 'inbox' || route.name === 'inbox-item');
    const itemId = computed(() => route.name === 'inbox-item' && route.params.id ? Number(route.params.id) : null);
    const pendingItems = computed(() => items.value.filter(x => ['stored', 'pending', 'generating', 'ready', 'error'].includes(x.status)));
    const completedItems = computed(() => items.value.filter(x => ['partially_used', 'archived', 'ignored'].includes(x.status)));
    const visibleItems = pendingItems;
    const readyItems = computed(() => pendingItems.value.filter(x => x.status === 'ready'));
    const generatingItems = computed(() => pendingItems.value.filter(x => ['stored', 'pending', 'generating'].includes(x.status)));
    const errorItems = computed(() => pendingItems.value.filter(x => x.status === 'error'));
    const activeItems = computed(() => pendingItems.value.some(x => ['stored', 'pending', 'generating'].includes(x.status)) || ['stored', 'pending', 'generating'].includes(item.value?.status));
    const visibleQuestions = computed(() => questions.value.slice(0, 5));

    function statusLabel(status) {
      return {
        pending: '已存储',
        generating: '生成中',
        stored: '已存储',
        ready: '有候选',
        partially_used: '已完成',
        archived: '已完成',
        ignored: '已忽略',
        error: '失败',
      }[status] || status || '未知';
    }

    function summarizeInboxTitle(content) {
      const text = String(content || '').trim();
      if (!text) return '未命名素材';
      const first = text.split(/\n+/).map(x => x.trim()).filter(Boolean)[0] || text;
      const cleaned = first
        .replace(/^标题[:：]\s*/i, '')
        .replace(/^来源[:：]\s*/i, '')
        .replace(/https?:\/\/\S+/g, '')
        .replace(/^[#>*\-\s]+/, '')
        .trim();
      const title = (cleaned || text).split(/[。！？!?；;]/)[0].trim();
      return (title || '未命名素材').slice(0, 32);
    }

    function displayInboxTitle(x) {
      return (x?.title && String(x.title).trim()) || summarizeInboxTitle(x?.content);
    }

    function depthLabel(depth) {
      return { low: '浅', medium: '中', high: '深' }[depth] || depth || '中';
    }

    async function loadDomainOptions() {
      try {
        const data = await api.getKnowledgeTree();
        const titles = (data.tree || [])
          .map(node => (node.title || '').trim())
          .filter(Boolean);
        if (titles.length) domainOptions.value = titles.slice(0, 8);
      } catch (_) { /* fallback to defaults */ }
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
      setNotice('图片已捕获到收集区。');
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
        await api.createInboxItem(text, 'text');
        pageContent.value = '';
        setNotice('已保存到收集箱。');
        await loadList();
        emit('refresh');
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

    // ── Generate questions on demand ──────────────────────────────────────

    async function generateQuestions(target) {
      if (!target?.id || actionBusy.value[`gen-${target.id}`]) return;
      actionBusy.value[`gen-${target.id}`] = true;
      try {
        await api.generateInboxQuestions(target.id);
        setNotice('AI 正在生成候选问题…');
        await loadCurrent();
        if (item.value?.id === target.id) startPolling();
      } catch (err) {
        setNotice(`生成失败：${err.message}`, 'error');
      } finally {
        actionBusy.value[`gen-${target.id}`] = false;
      }
    }

    // ── Recommendations ──────────────────────────────────────────────────────

    async function loadRecommendations() {
      try {
        const data = await api.getInboxRecommendations();
        recommendations.value = data.recommendations || [];
        recsGenerating.value = data.status === 'generating';
        if (recsGenerating.value) {
          startRecsPolling();
        } else {
          stopRecsPolling();
        }
      } catch (_) { /* recommendations are optional */ }
    }

    function startRecsPolling() {
      if (recsPollTimer) return;
      recsPollTimer = setInterval(loadRecommendations, 8000);
    }

    function stopRecsPolling() {
      if (recsPollTimer) {
        clearInterval(recsPollTimer);
        recsPollTimer = null;
      }
    }

    async function refreshRecommendations() {
      recsGenerating.value = true;
      recommendations.value = [];
      try {
        await api.refreshInboxRecommendations();
        startRecsPolling();
      } catch (err) {
        setNotice(`刷新推荐失败：${err.message}`, 'error');
        recsGenerating.value = false;
      }
    }

    async function selectRecommendation(rec) {
      if (!rec?.id || actionBusy.value[`rec-${rec.id}`]) return;
      actionBusy.value[`rec-${rec.id}`] = true;
      try {
        const result = await api.selectInboxRecommendation(rec.id);
        emit('refresh');
        router.push({ name: 'session-learn', params: { id: result.session_id } });
      } catch (err) {
        setNotice(`创建学习失败：${err.message}`, 'error');
      } finally {
        actionBusy.value[`rec-${rec.id}`] = false;
      }
    }

    async function ignoreRecommendation(rec) {
      if (!rec?.id || actionBusy.value[`rec-ignore-${rec.id}`]) return;
      actionBusy.value[`rec-ignore-${rec.id}`] = true;
      try {
        await api.ignoreInboxRecommendation(rec.id);
        recommendations.value = recommendations.value.map(x => x.id === rec.id ? { ...x, status: 'ignored' } : x);
      } catch (err) {
        setNotice(`忽略失败：${err.message}`, 'error');
      } finally {
        actionBusy.value[`rec-ignore-${rec.id}`] = false;
      }
    }

    const activeRecommendations = computed(() =>
      (recommendations.value || []).filter(r => r.status === 'active')
    );

    function syncGenerationNotice(currentItem) {
      if (!currentItem?.id) return;
      const key = `${currentItem.id}:${currentItem.status}`;
      if (key === lastProcessingNoticeKey) return;
      if (['stored', 'pending', 'generating'].includes(currentItem.status)) {
        lastProcessingNoticeKey = key;
        setNotice('AI 正在把这条素材加工成候选问题…');
        return;
      }
      if (currentItem.status === 'ready' && lastProcessingNoticeKey.startsWith(`${currentItem.id}:`)) {
        lastProcessingNoticeKey = key;
        setNotice('候选问题已生成，可以选择一个开始学习。');
      }
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
          loadRecommendations();
        }
        syncGenerationNotice(item.value);
        if (item.value && ['stored', 'pending', 'generating'].includes(item.value.status)) {
          startPolling();
        } else {
          stopPolling();
        }
      } catch (err) {
        setNotice(`加载收集箱失败：${err.message}`, 'error');
      } finally {
        loading.value = false;
      }
    }

    function startPolling() {
      if (pollTimer) return;
      pollTimer = setInterval(loadCurrent, 10000);
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

    async function deleteHistoryItem(target) {
      if (!target?.id || actionBusy.value[`delete-${target.id}`]) return;
      actionBusy.value[`delete-${target.id}`] = true;
      try {
        await api.deleteInboxItem(target.id);
        if (item.value?.id === target.id) router.push({ name: 'inbox' });
        await loadCurrent();
        emit('refresh');
        setNotice('已删除这条历史素材。');
      } catch (err) {
        setNotice(`删除失败：${err.message}`, 'error');
      } finally {
        actionBusy.value[`delete-${target.id}`] = false;
      }
    }

    async function clearHistory() {
      if (!completedItems.value.length || actionBusy.value.clearHistory) return;
      const ok = await askConfirm({
        title: '清空已完成素材',
        message: `确定清空 ${completedItems.value.length} 条已完成素材？`,
        details: '只会清理已完成/已忽略的素材，不影响最近收集。',
        confirmText: '清空',
        cancelText: '取消',
        tone: 'danger',
      });
      if (!ok) return;
      actionBusy.value.clearHistory = true;
      try {
        const result = await api.clearInboxHistory();
        if (item.value && ['partially_used', 'archived', 'ignored'].includes(item.value.status)) {
          router.push({ name: 'inbox' });
        }
        await loadCurrent();
        emit('refresh');
        setNotice(`已清空 ${result.deleted || 0} 条已完成素材。`);
      } catch (err) {
        setNotice(`清空失败：${err.message}`, 'error');
      } finally {
        actionBusy.value.clearHistory = false;
      }
    }

    watch(() => route.fullPath, loadCurrent);
    onMounted(() => {
      loadDomainOptions();
      loadCurrent();
    });
    onUnmounted(() => { stopPolling(); stopRecsPolling(); });

    return {
      items, pendingItems, completedItems, visibleItems, readyItems, generatingItems, errorItems,
      item, questions, visibleQuestions, loading, actionBusy, direction, router, icon,
      pageContent, pageSubmitting, selectedDomains,
      sourceUrl, urlFetching, voiceListening, imagePreview, imageName, domainOptions,
      statusLabel, depthLabel, loadDomainOptions,
      importUrlToComposer, startVoiceInput, handleImageInput, handlePagePaste, submitPageCollection, handlePageKeydown, generateQuestions,
      openItem, regenerate, selectQuestion, ignoreQuestion, archiveItem, deleteHistoryItem, clearHistory, displayInboxTitle,
      recommendations, activeRecommendations, recsGenerating, loadRecommendations, refreshRecommendations, selectRecommendation, ignoreRecommendation,
    };
  },

  template: `
    <div class="inbox-panel">
      <section :class="['inbox-detail-pane', { 'is-overview': !item }]">
        <div v-if="loading && !item" class="empty-state">加载中…</div>
        <div v-else-if="!item" class="inbox-overview">
          <div class="inbox-overview-kicker">INBOX</div>
          <h2>收集箱</h2>
          <p>随手记录碎片想法，感兴趣的点「生成问题」让 AI 帮你提炼；也可以直接「完成」忽略。</p>

          <section v-if="activeRecommendations.length || recsGenerating" class="inbox-recs-section">
            <div class="inbox-section-head">
              <div class="home-section-title" v-html="icon('bulb') + ' 为你推荐'"></div>
              <button type="button" class="btn btn-ghost" :disabled="recsGenerating" @click="refreshRecommendations">换一批</button>
            </div>
            <p class="inbox-recs-desc">基于你的学习轨迹自动推荐，每天换一批。随心选择。</p>
            <div v-if="recsGenerating" class="inbox-recs-generating">
              <span class="inbox-recs-dot"></span>AI 正在为你推荐…
            </div>
            <div v-else class="inbox-recs-grid">
              <article v-for="rec in activeRecommendations.slice(0,4)" :key="'rec-'+rec.id" class="inbox-rec-card">
                <div class="inbox-rec-body">
                  <div class="inbox-rec-question">{{ rec.question }}</div>
                  <p v-if="rec.why" class="inbox-rec-why">{{ rec.why }}</p>
                  <div class="inbox-rec-meta">
                    <span class="inbox-rec-angle">{{ rec.angle || '跨学科' }}</span>
                    <span class="inbox-rec-depth">{{ {low:'浅',medium:'中',high:'深'}[rec.depth] || rec.depth || '中' }}</span>
                  </div>
                </div>
                <div class="inbox-rec-actions">
                  <button type="button" class="btn btn-primary" :disabled="actionBusy['rec-'+rec.id]" @click="selectRecommendation(rec)">开始学习</button>
                  <button type="button" class="btn btn-ghost" :disabled="actionBusy['rec-ignore-'+rec.id]" @click="ignoreRecommendation(rec)">不感兴趣</button>
                </div>
              </article>
            </div>
          </section>

          <section class="inbox-page-composer">
            <div class="inbox-page-composer-head">
              <div class="home-section-title" v-html="icon('edit') + ' 快速收集'"></div>
              <span>纯记录，不自动生成问题。需要提炼时再手动触发生成。</span>
            </div>
            <div class="inbox-source-tools">
              <div class="inbox-url-import">
                <input type="url" v-model="sourceUrl" placeholder="粘贴文章/网页链接，先抓正文再加工…" @keydown.enter.prevent="importUrlToComposer" />
                <button type="button" class="btn inbox-source-tool-btn" :disabled="!sourceUrl.trim() || urlFetching" @click="importUrlToComposer"><span v-html="icon('globe')"></span>{{ urlFetching ? '抓取中' : '抓取链接' }}</button>
              </div>
              <button type="button" class="btn inbox-source-tool-btn" :class="{ active: voiceListening }" @click="startVoiceInput"><span v-html="icon('mic')"></span>{{ voiceListening ? '正在听…' : '语音输入' }}</button>
              <label class="btn inbox-source-tool-btn"><span v-html="icon('image')"></span>贴图片
                <input type="file" accept="image/*" class="visually-hidden" @change="handleImageInput" />
              </label>
            </div>
            <div v-if="imagePreview" class="inbox-image-preview">
              <img :src="imagePreview" :alt="imageName" />
              <span>{{ imageName }}</span>
            </div>
            <textarea
              class="inbox-page-input"
              v-model="pageContent"
              rows="4"
              placeholder="粘贴摘录、想法、链接…纯粹记录，不会自动生成问题"
              :disabled="pageSubmitting"
              @keydown="handlePageKeydown"
              @paste="handlePagePaste"></textarea>
            <div class="inbox-compose-option-row is-domains">
              <span class="inbox-compose-label">可选领域</span>
              <div class="inbox-compose-domain-grid">
                <button v-for="domain in domainOptions" :key="domain" type="button" :class="['btn', 'inbox-chip', { active: selectedDomains.includes(domain) }]" @click="selectedDomains = selectedDomains.includes(domain) ? selectedDomains.filter(x => x !== domain) : [...selectedDomains, domain]">{{ domain }}</button>
              </div>
            </div>
            <div class="inbox-compose-footer">
              <button type="button" class="btn btn-primary" :disabled="!pageContent.trim() || pageSubmitting" @click="submitPageCollection">
                {{ pageSubmitting ? '保存中' : '放入收集箱' }}
              </button>
            </div>
          </section>

          <section class="inbox-overview-section">
            <div class="inbox-section-head">
              <div class="home-section-title" v-html="icon('clip') + ' 最近收集'"></div>
              <span>{{ pendingItems.length }} 条</span>
            </div>
            <article v-for="x in pendingItems" :key="'pending-'+x.id" class="inbox-material-card">
              <div class="inbox-material-main">
                <div class="inbox-material-line">
                  <button type="button" class="inbox-material-title inbox-material-title-button" @click.stop="openItem(x)">{{ displayInboxTitle(x) }}</button>
                  <span :class="['inbox-list-status', 'is-' + x.status]">{{ statusLabel(x.status) }} · {{ x.question_count || 0 }} 个问题</span>
                </div>
              </div>
              <div class="inbox-material-actions">
                <button v-if="!x.question_count && !['generating'].includes(x.status)" type="button" class="btn btn-accent" :disabled="actionBusy['gen-' + x.id]" @click.stop="generateQuestions(x)">生成问题</button>
                <button v-if="x.question_count" type="button" class="btn btn-primary" @click.stop="openItem(x)">查看</button>
                <button type="button" class="btn btn-ghost" :disabled="actionBusy['archive-' + x.id]" @click.stop="archiveItem(x)">完成</button>
              </div>
            </article>
            <div v-if="!pendingItems.length" class="inbox-overview-empty">暂无收集的素材。上方粘贴或左侧输入框快速记录。</div>
          </section>

          <section class="inbox-overview-section inbox-completed-section">
            <div class="inbox-section-head">
              <div class="home-section-title" v-html="icon('check') + ' 已完成'"></div>
              <span>共 {{ completedItems.length }} 条</span>
              <button v-if="completedItems.length" type="button" class="btn btn-ghost inbox-clear-history" :disabled="actionBusy.clearHistory" @click="clearHistory">清空已完成</button>
            </div>
            <article v-for="x in completedItems" :key="'done-'+x.id" class="inbox-material-card done">
              <div class="inbox-material-main">
                <div class="inbox-material-line">
                  <button type="button" class="inbox-material-title inbox-material-title-button" @click.stop="openItem(x)">{{ displayInboxTitle(x) }}</button>
                  <span :class="['inbox-list-status', 'is-' + x.status]">{{ statusLabel(x.status) }} · {{ x.question_count || 0 }} 个问题</span>
                </div>
              </div>
              <div class="inbox-material-actions">
                <button type="button" class="btn btn-ghost" @click.stop="openItem(x)">查看</button>
                <button type="button" class="btn btn-ghost" :disabled="actionBusy['delete-' + x.id]" @click.stop="deleteHistoryItem(x)">删除</button>
              </div>
            </article>
            <div v-if="!completedItems.length" class="inbox-overview-empty">暂无已完成的素材。</div>
          </section>
        </div>
        <template v-else>
          <header class="inbox-detail-header">
            <div>
              <div class="inbox-breadcrumb">
                <button type="button" class="inbox-breadcrumb-link" @click="router.push({ name: 'inbox' })">收集箱</button>
                <span>/ {{ statusLabel(item.status) }}</span>
              </div>
              <h2>{{ displayInboxTitle(item) }}</h2>
            </div>
            <button type="button" class="btn btn-ghost" @click="archiveItem()">完成</button>
          </header>

          <div v-if="item.error_msg && !questions.length" class="inbox-error">{{ item.error_msg }}</div>
          <section class="inbox-source-block">
            <div class="ps-label">原始素材</div>
            <div class="inbox-source-text">{{ item.content }}</div>
          </section>

          <section class="inbox-regenerate-row">
            <input type="text" v-model="direction" placeholder="可选：更偏心理学 / 技术 / 哲学..." @keydown.enter.prevent="regenerate()" />
            <button type="button" class="btn" :disabled="actionBusy.regenerate" @click="regenerate()">换一批问题</button>
          </section>

          <div class="inbox-question-list">
            <article v-for="q in visibleQuestions" :key="q.id" :class="['inbox-question-card', 'is-' + q.status]">
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
            <div v-if="!questions.length && !['stored','pending','generating'].includes(item.status)" class="inbox-empty-small">还没有生成问题。</div>
          </div>
        </template>
      </section>

      <aside class="inbox-list-pane">
        <template v-if="item">
          <div class="inbox-panel-title">最近收集</div>
          <div class="inbox-panel-subtitle">感兴趣的点「生成问题」</div>
          <div v-if="!pendingItems.length && !loading" class="inbox-empty-small">暂无收集的素材</div>
          <button v-for="x in pendingItems" :key="x.id" type="button"
                  :class="['inbox-list-item', { active: item && item.id === x.id }]"
                  @click="openItem(x)">
            <span class="inbox-list-title">{{ displayInboxTitle(x) }}</span>
            <span :class="['inbox-list-status', 'is-' + x.status]">{{ statusLabel(x.status) }} · {{ x.question_count || 0 }}</span>
          </button>
        </template>
        <template v-else>
          <div class="inbox-panel-title">使用方式</div>
          <div class="inbox-panel-subtitle">收集箱不是任务清单，是灵感便签</div>
          <div class="inbox-rail-note">
            <p><strong>生成问题</strong><span>对感兴趣的素材点击生成，AI 帮你提炼问题。</span></p>
            <p><strong>查看</strong><span>打开已生成问题的素材，选择一个进入学习。</span></p>
            <p><strong>完成</strong><span>不再需要的素材移到已完成。</span></p>
          </div>
        </template>
      </aside>
    </div>
  `,
});
