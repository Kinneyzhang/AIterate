// ── NewSessionModal.js ────────────────────────────────────────────────────

import { defineComponent, ref, onMounted } from 'vue';
import { api } from '../../api.js';
import { icon } from '../../icons.js';
import { setNotice } from '../../store.js';

export default defineComponent({
  emits: ['close', 'created'],
  
  setup(props, { emit }) {
    const content = ref('');
    const selectedType = ref('question');
    const webSearch = ref(false);
    const selectedNodeId = ref(null);
    const submitting = ref(false);
    const ready = ref({ llm: true, tavily: false });
    const knowledgeTree = ref(null);
    const suggestions = ref([]);
    
    onMounted(async () => {
      try { ready.value = await api.getReady(); } catch {}
      try { const r = await api.getKnowledgeTree(); knowledgeTree.value = r.tree || []; } catch {}
    });
    
    let suggestTimer = null;
    function onInput() {
      clearTimeout(suggestTimer);
      selectedNodeId.value = null;
      suggestTimer = setTimeout(() => {
        const val = content.value.trim();
        if (!val || val.length < 3 || !knowledgeTree.value) { suggestions.value = []; return; }
        suggestions.value = clientSuggest(val).slice(0, 4);
      }, 500);
    }
    
    function clientSuggest(query) {
      const ql = query.toLowerCase();
      const words = ql.split(/\s+/).filter(w => w.length > 1);
      if (!words.length) return [];
      const scored = [];
      function walk(nodes, path = '') {
        for (const n of nodes) {
          let s = 0;
          const t = (n.title || '').toLowerCase();
          const kws = (n.keywords || []).map(k => k.toLowerCase());
          for (const w of words) {
            if (t.includes(w)) s += 3;
            for (const kw of kws) if (kw.includes(w) || w.includes(kw)) s += 2;
          }
          if (ql.includes(t) || t.includes(ql)) s += 5;
          if (s > 0) scored.push({ id: n.id, title: n.title, path: (path ? path + '/' : '') + n.title, score: s });
          walk(n.children || [], path ? path + '/' + n.title : n.title);
        }
      }
      walk(knowledgeTree.value);
      return scored.sort((a, b) => b.score - a.score || a.path.localeCompare(b.path));
    }
    
    async function submit() {
      const c = content.value.trim();
      if (!c) return;
      submitting.value = true;
      try {
        await api.createSession('', c, selectedType.value, webSearch.value, selectedNodeId.value);
        emit('created');
        emit('close');
      } catch (err) {
        setNotice(`创建失败：${err.message}`, 'error');
      } finally {
        submitting.value = false;
      }
    }
    
    function close() { emit('close'); }
    
    return { content, selectedType, webSearch, selectedNodeId, submitting, ready, suggestions, onInput, submit, close, icon };
  },
  
  template: `
    <div class="modal-overlay" @click.self="close">
      <div class="modal-box" role="dialog">
        <div class="modal-header">
          <div class="modal-title">提出问题或观点</div>
          <button class="modal-close" @click="close">✕</button>
        </div>
        <div class="modal-body">
          <div v-if="!ready.llm" class="modal-config-warning" style="display:flex">
            <span v-html="icon('warn')"></span> 尚未配置大模型，<a href="#" @click.prevent="close(); $parent.$emit('open-settings')">前往设置</a> 后再提交。
          </div>
          <div class="type-toggle">
            <button :class="['type-btn', { active: selectedType === 'question' }]" @click="selectedType = 'question'" v-html="icon('search') + ' 问题'"></button>
            <button :class="['type-btn', { active: selectedType === 'viewpoint' }]" @click="selectedType = 'viewpoint'" v-html="icon('bulb') + ' 观点'"></button>
          </div>
          <textarea v-model="content" @input="onInput" rows="7" class="modal-textarea"
            :placeholder="selectedType === 'question' ? '写下你的问题，可以描述得详细一些…\\nAI 会自动生成标题并给出回答。' : '写下你的观点，可以展开说说…\\nAI 会自动生成标题并进行分析。'"></textarea>
          <div v-if="suggestions.length" class="modal-node-suggestions" style="display:block">
            <div class="node-suggest-label" v-html="icon('tag') + ' 推荐知识节点（可选）'"></div>
            <div class="node-suggest-list">
              <button v-for="n in suggestions" :key="n.id"
                :class="['node-suggest-item', { selected: n.id === selectedNodeId }]"
                @click="selectedNodeId = selectedNodeId === n.id ? null : n.id">
                {{ n.path }} <span class="kn-score">{{ n.score }}</span>
              </button>
            </div>
          </div>
          <div class="modal-hint">提交后立即入队，不阻塞你继续提下一个。</div>
        </div>
        <div class="modal-footer">
          <div class="modal-footer-left">
            <button :class="['btn btn-sm web-search-btn', { active: webSearch }]" @click="webSearch = !webSearch" v-html="icon('globe') + ' 联网'"></button>
          </div>
          <div class="modal-footer-right">
            <button class="btn" @click="close">取消</button>
            <button class="btn btn-primary" :disabled="submitting || !ready.llm" @click="submit" v-html="icon('rocket') + ' 提交'"></button>
          </div>
        </div>
      </div>
    </div>
  `,
});
