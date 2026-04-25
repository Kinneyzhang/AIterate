// ── SettingsModal.js ───────────────────────────────────────────────────────

import { defineComponent, ref, onMounted, reactive } from 'vue';
import { api } from '../../api.js';
import { icon } from '../../icons.js';
import { setNotice } from '../../store.js';

const PROVIDER_PRESETS = {
  openai: { base_url: 'https://api.openai.com/v1', models: 'gpt-4o / gpt-4o-mini / o1' },
  deepseek: { base_url: 'https://api.deepseek.com/v1', models: 'deepseek-chat / deepseek-reasoner' },
  kimi: { base_url: 'https://api.moonshot.cn/v1', models: 'moonshot-v1-8k / moonshot-v1-32k' },
  doubao: { base_url: 'https://ark.cn-beijing.volces.com/api/v3', models: 'ep-xxxx' },
  copilot: { base_url: 'https://api.githubcopilot.com', models: 'gpt-4o / claude-sonnet-4' },
  custom: { base_url: '', models: '' },
};

const ROLES = [
  { key: 'title', label: '标题生成' },
  { key: 'answer', label: '材料生成' },
  { key: 'evaluate', label: '理解评分' },
  { key: 'review', label: '费曼评分' },
  { key: 'deepen', label: '深化追问' },
];

export default defineComponent({
  emits: ['close'],
  
  setup(props, { emit }) {
    const activeTab = ref('ai');
    const saving = ref(false);
    
    // AI settings
    const provider = ref('deepseek');
    const baseUrl = ref('');
    const apiKey = ref('');
    const model = ref('');
    const roles = reactive({});
    
    // Search
    const tavilyKey = ref('');
    
    // Learning
    const feynmanPassScore = ref(60);
    
    onMounted(async () => {
      try {
        const s = await api.getSettings();
        const llm = s.llm || {};
        provider.value = llm.provider || 'deepseek';
        baseUrl.value = llm.base_url || '';
        apiKey.value = '';
        model.value = llm.model || '';
        for (const r of ROLES) {
          roles[r.key] = llm.roles?.[r.key] || { provider: '', base_url: '', api_key: '', model: '' };
        }
        tavilyKey.value = '';
        feynmanPassScore.value = s.feynman_pass_score || 60;
      } catch {}
    });
    
    function onProviderChange() {
      const p = PROVIDER_PRESETS[provider.value];
      if (p) baseUrl.value = p.base_url;
    }
    
    async function save() {
      saving.value = true;
      try {
        const rolesPayload = {};
        for (const r of ROLES) {
          const cfg = roles[r.key];
          if (cfg.provider || cfg.base_url || cfg.api_key || cfg.model) {
            rolesPayload[r.key] = { ...cfg };
          }
        }
        await api.saveSettings({
          llm: {
            provider: provider.value,
            base_url: baseUrl.value.trim(),
            api_key: apiKey.value.trim(),
            model: model.value.trim(),
            roles: rolesPayload,
          },
          tavily_api_key: tavilyKey.value.trim(),
          feynman_pass_score: parseInt(feynmanPassScore.value) || 60,
        });
        emit('close');
        setNotice('设置已保存。');
      } catch (err) {
        setNotice(`保存失败：${err.message}`, 'error');
      } finally {
        saving.value = false;
      }
    }
    
    return { activeTab, saving, provider, baseUrl, apiKey, model, roles, tavilyKey, feynmanPassScore, onProviderChange, save, icon, ROLES };
  },
  
  template: `
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box modal-box-lg" role="dialog">
        <div class="modal-header">
          <div class="modal-title" v-html="icon('gear') + ' 设置'"></div>
          <button class="modal-close" @click="$emit('close')">✕</button>
        </div>
        <div class="settings-tabs">
          <button :class="['settings-tab', { active: activeTab === 'ai' }]" @click="activeTab = 'ai'">AI 基础</button>
          <button :class="['settings-tab', { active: activeTab === 'roles' }]" @click="activeTab = 'roles'">分功能模型</button>
          <button :class="['settings-tab', { active: activeTab === 'search' }]" @click="activeTab = 'search'">联网搜索</button>
          <button :class="['settings-tab', { active: activeTab === 'learn' }]" @click="activeTab = 'learn'">学习</button>
        </div>
        <div class="modal-body settings-modal-body">
          <!-- AI -->
          <div :class="['settings-panel', { active: activeTab === 'ai' }]">
            <div class="settings-row">
              <div class="settings-label">Provider</div>
              <select v-model="provider" @change="onProviderChange" class="settings-input">
                <option value="deepseek">DeepSeek</option>
                <option value="kimi">Kimi</option>
                <option value="doubao">豆包</option>
                <option value="copilot">GitHub Copilot</option>
                <option value="custom">自定义</option>
              </select>
            </div>
            <div class="settings-row">
              <div class="settings-label">Base URL</div>
              <input v-model="baseUrl" class="settings-input" placeholder="https://api.deepseek.com/v1">
            </div>
            <div class="settings-row">
              <div class="settings-label">API Key</div>
              <input v-model="apiKey" type="password" class="settings-input" placeholder="已配置 (留空不修改)">
            </div>
            <div class="settings-row">
              <div class="settings-label">Model</div>
              <input v-model="model" class="settings-input" placeholder="deepseek-chat">
            </div>
          </div>
          
          <!-- Roles -->
          <div :class="['settings-panel', { active: activeTab === 'roles' }]">
            <div v-for="r in ROLES" :key="r.key" class="settings-row" style="margin-bottom:18px">
              <div class="settings-label" style="font-weight:600; margin-bottom:6px">{{ r.label }}</div>
              <input v-model="roles[r.key].model" class="settings-input" :placeholder="'模型名（留空用默认）'" style="margin-bottom:4px">
            </div>
          </div>
          
          <!-- Search -->
          <div :class="['settings-panel', { active: activeTab === 'search' }]">
            <div class="settings-row">
              <div class="settings-label">Tavily API Key</div>
              <input v-model="tavilyKey" type="password" class="settings-input" placeholder="tvly-...（留空不修改）">
            </div>
          </div>
          
          <!-- Learning -->
          <div :class="['settings-panel', { active: activeTab === 'learn' }]">
            <div class="settings-row">
              <div class="settings-label">费曼通过分数线</div>
              <input v-model.number="feynmanPassScore" type="number" min="0" max="100" class="settings-input">
              <p class="settings-hint">费曼平均分 ≥ 此值视为通过，默认 60</p>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <div class="modal-footer-left"></div>
          <div class="modal-footer-right">
            <button class="btn" @click="$emit('close')">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save" v-html="icon('save') + ' 保存'"></button>
          </div>
        </div>
      </div>
    </div>
  `,
});
