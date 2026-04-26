// ── SettingsModal.js ── 精确复刻原版 settings ──────────────────────────────

import { defineComponent, ref, onMounted, reactive, nextTick, computed } from 'vue';
import { useRouter, useRoute } from 'vue-router';
import { api } from '../../api.js';
import { icon } from '../../icons.js';
import { setNotice } from '../../store.js';

const PROVIDER_PRESETS = {
  openai: { base_url: 'https://api.openai.com/v1', models: 'gpt-4o / gpt-4o-mini / o1' },
  deepseek: { base_url: 'https://api.deepseek.com/v1', models: 'deepseek-v4-pro / deepseek-v4-flash / deepseek-chat' },
  kimi: { base_url: 'https://api.moonshot.cn/v1', models: 'moonshot-v1-8k / moonshot-v1-32k / moonshot-v1-128k' },
  doubao: { base_url: 'https://ark.cn-beijing.volces.com/api/v3', models: 'doubao-pro-32k / doubao-pro-4k / deepseek-v3-241226' },
  copilot: { base_url: 'https://api.githubcopilot.com', models: 'gpt-4o / claude-sonnet-4-5 / gemini-2.0-flash-001', hint: 'API Key 填 GitHub OAuth token（GHU_ 开头），通过 Device Code 授权获取' },
  gemini: { base_url: 'https://generativelanguage.googleapis.com/v1beta/openai', models: 'gemini-2.0-flash / gemini-2.5-pro' },
  anthropiccompat: { base_url: 'https://api.anthropic.com/v1', models: 'claude-sonnet-4-5 / claude-opus-4' },
  openrouter: { base_url: 'https://openrouter.ai/api/v1', models: 'any model slug' },
  custom: { base_url: '', models: '' },
};

const PROVIDER_OPTIONS = [
  { value: 'openai', label: 'OpenAI' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'kimi', label: 'Kimi（月之暗面）' },
  { value: 'doubao', label: '豆包（火山引擎）' },
  { value: 'copilot', label: 'GitHub Copilot' },
  { value: 'gemini', label: 'Gemini' },
  { value: 'anthropiccompat', label: 'Anthropic（兼容格式）' },
  { value: 'openrouter', label: 'OpenRouter' },
  { value: 'custom', label: 'Custom' },
];

const ROLE_PROVIDER_OPTIONS = [
  { value: '', label: '— 继承基础 —' },
  ...PROVIDER_OPTIONS,
];

const ROLES = [
  { key: 'title', label: '标题生成 (title)' },
  { key: 'answer', label: '回答生成 (answer)' },
  { key: 'evaluate', label: '评估 (evaluate)' },
  { key: 'review', label: '费曼 (review)' },
  { key: 'deepen', label: '深化追问 (deepen)' },
];

const DB_TYPE_OPTIONS = [
  { value: 'sqlite', label: 'SQLite（本地文件，默认）' },
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'mysql', label: 'MySQL（实验性·未启用）', disabled: true },
  { value: 'oracle', label: 'Oracle（实验性·未启用）', disabled: true },
];

export default defineComponent({
  emits: ['close'],

  setup(props, { emit }) {
    const router = useRouter();
    const route  = useRoute();

    // activeTab 由路由决定：settings-basic → 'basic', settings-roles → 'roles', …
    const TAB_MAP = {
      'settings-basic':    'basic',
      'settings-roles':    'roles',
      'settings-tavily':   'tavily',
      'settings-database': 'database',
      'settings-learn':    'learn',
    };
    const activeTab = computed(() => TAB_MAP[route.name] || 'basic');

    function switchTab(tab) {
      const name = `settings-${tab}`;
      router.replace({ name });
    }
    const saving = ref(false);

    // AI settings
    const provider = ref('deepseek');
    const baseUrl = ref('');
    const apiKey = ref('');
    const apiKeyPlaceholder = ref('sk-...');
    const model = ref('');
    const modelHint = ref('');

    // Role settings — each role has provider/base_url/api_key/model
    const roles = reactive({});
    for (const r of ROLES) {
      roles[r.key] = reactive({ provider: '', base_url: '', api_key: '', model: '', api_key_placeholder: '继承基础配置' });
    }

    // Tavily
    const tavilyKey = ref('');
    const tavilyKeyPlaceholder = ref('tvly-...');

    // DB
    const dbType = ref('postgresql');
    const dbHost = ref('');
    const dbPort = ref('');
    const dbName = ref('');
    const dbUser = ref('');
    const dbPassword = ref('');
    const dbSqlitePath = ref('');
    const dbOracleHost = ref('');
    const dbOraclePort = ref('');
    const dbServiceName = ref('');
    const dbOracleUser = ref('');
    const dbOraclePassword = ref('');
    const originalDbPayload = ref(null);

    // Learning
    const feynmanPassScore = ref(60);
    const sliderDisplay = ref('60');

    // Load settings
    onMounted(async () => {
      try {
        const s = await api.getSettings();
        const llm = s.llm || {};
        if (llm.provider) provider.value = llm.provider;
        if (llm.base_url) baseUrl.value = llm.base_url;
        apiKeyPlaceholder.value = llm.has_api_key ? '已配置 (留空不修改)' : 'sk-...';
        if (llm.model) model.value = llm.model;

        tavilyKeyPlaceholder.value = s.has_tavily_api_key ? '已配置 (留空不修改)' : 'tvly-...';

        const ps = s.feynman_pass_score ?? 60;
        feynmanPassScore.value = ps;
        sliderDisplay.value = String(ps);

        const rolesData = llm.roles || {};
        for (const r of ROLES) {
          const rd = rolesData[r.key] || {};
          if (rd.provider) roles[r.key].provider = rd.provider;
          if (rd.base_url) roles[r.key].base_url = rd.base_url;
          if (rd.has_api_key) roles[r.key].api_key_placeholder = '已配置 (留空不修改)';
          if (rd.model) roles[r.key].model = rd.model;
        }

        // Load DB config
        try {
          const cfg = await api.getDbConfig();
          const t = cfg.type || 'postgresql';
          dbType.value = t;
          if (t === 'oracle') {
            if (cfg.host) dbOracleHost.value = cfg.host;
            if (cfg.port) dbOraclePort.value = String(cfg.port);
            if (cfg.service_name) dbServiceName.value = cfg.service_name;
            if (cfg.user) dbOracleUser.value = cfg.user;
          } else if (t !== 'sqlite') {
            if (cfg.host) dbHost.value = cfg.host;
            if (cfg.port) dbPort.value = String(cfg.port);
            if (cfg.dbname) dbName.value = cfg.dbname;
            if (cfg.user) dbUser.value = cfg.user;
          } else {
            if (cfg.sqlite_path) dbSqlitePath.value = cfg.sqlite_path;
          }
          originalDbPayload.value = buildDbPayload(false);
        } catch (e) { console.warn('Failed to load db-config:', e); }
      } catch (err) {
        setNotice(`加载设置失败：${err.message || err}`, 'error');
      }
    });

    // Provider change → auto-fill base URL
    function onProviderChange() {
      const p = PROVIDER_PRESETS[provider.value];
      if (p) {
        if (p.base_url) baseUrl.value = p.base_url;
        modelHint.value = p.hint || '';
        if (provider.value !== 'custom') {
          document.getElementById('settingsModel').placeholder = p.models.split('/')[0].trim();
        }
      }
    }

    // Role provider change
    function onRoleProviderChange(roleKey) {
      const rp = roles[roleKey];
      const preset = PROVIDER_PRESETS[rp.provider];
      if (preset && rp.provider) {
        if (preset.base_url) rp.base_url = preset.base_url;
        if (preset.models) {
          const el = document.getElementById(`role-model-${roleKey}`);
          if (el) el.placeholder = preset.models.split('/')[0].trim();
        }
      }
    }

    // Slider
    function onSliderInput() {
      sliderDisplay.value = String(feynmanPassScore.value);
    }

    function buildDbPayload(includePasswords = true) {
      const payload = { type: dbType.value };
      if (dbType.value === 'sqlite') {
        payload.sqlite_path = dbSqlitePath.value || '~/.aiterate/data.db';
      } else if (dbType.value === 'oracle') {
        payload.host = dbOracleHost.value;
        payload.port = parseInt(dbOraclePort.value) || 1521;
        payload.service_name = dbServiceName.value;
        payload.user = dbOracleUser.value;
        if (includePasswords && dbOraclePassword.value) payload.password = dbOraclePassword.value;
      } else {
        payload.host = dbHost.value;
        payload.port = parseInt(dbPort.value) || (dbType.value === 'mysql' ? 3306 : 5432);
        payload.dbname = dbName.value;
        payload.user = dbUser.value;
        if (includePasswords && dbPassword.value) payload.password = dbPassword.value;
      }
      return payload;
    }

    function stableStringify(obj) {
      return JSON.stringify(obj, Object.keys(obj).sort());
    }

    // Save
    async function save() {
      saving.value = true;
      try {
        const rolesPayload = {};
        for (const r of ROLES) {
          const rp = roles[r.key];
          if (rp.provider || rp.base_url || rp.api_key || rp.model) {
            rolesPayload[r.key] = {
              provider: rp.provider,
              base_url: rp.base_url,
              api_key: rp.api_key,
              model: rp.model,
            };
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

        // Save DB config only when the database tab actually changed.
        // Otherwise a transient DB test failure would make unrelated AI/Tavily saves look failed.
        const dbPayload = buildDbPayload(true);
        const dbPayloadComparable = buildDbPayload(false);
        const dbChanged = !originalDbPayload.value
          || stableStringify(dbPayloadComparable) !== stableStringify(originalDbPayload.value)
          || Boolean(dbPayload.password);
        if (dbChanged) {
          await api.saveDbConfig(dbPayload);
          originalDbPayload.value = dbPayloadComparable;
        }

        emit('close');
        setNotice('设置已保存。');
      } catch (err) {
        setNotice(`保存失败：${err.message}`, 'error');
      } finally {
        saving.value = false;
      }
    }

    return {
      activeTab, switchTab, saving,
      provider, baseUrl, apiKey, apiKeyPlaceholder, model, modelHint,
      roles, ROLES, PROVIDER_OPTIONS, ROLE_PROVIDER_OPTIONS,
      tavilyKey, tavilyKeyPlaceholder,
      dbType, dbHost, dbPort, dbName, dbUser, dbPassword,
      dbSqlitePath, dbOracleHost, dbOraclePort, dbServiceName, dbOracleUser, dbOraclePassword,
      DB_TYPE_OPTIONS, feynmanPassScore, sliderDisplay,
      onProviderChange, onRoleProviderChange, onSliderInput, save,
      icon_warn: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
      icon_gear: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
      icon_save: '<svg width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>',
    };
  },

  template: `
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box modal-box-lg" role="dialog" aria-modal="true">
        <div class="modal-header">
          <div class="modal-title" v-html="icon_gear + ' 设置'"></div>
          <button class="modal-close" aria-label="关闭" @click="$emit('close')">✕</button>
        </div>
        <div class="settings-tabs">
          <button :class="['settings-tab', { active: activeTab === 'basic' }]" @click="switchTab('basic')">AI 基础</button>
          <button :class="['settings-tab', { active: activeTab === 'roles' }]" @click="switchTab('roles')">分功能模型</button>
          <button :class="['settings-tab', { active: activeTab === 'tavily' }]" @click="switchTab('tavily')">联网搜索</button>
          <button :class="['settings-tab', { active: activeTab === 'database' }]" @click="switchTab('database')">数据库</button>
          <button :class="['settings-tab', { active: activeTab === 'learn' }]" @click="switchTab('learn')">学习</button>
        </div>
        <div class="modal-body settings-modal-body">
          <!-- Tab1: 基础 -->
          <div :class="['settings-panel', { active: activeTab === 'basic' }]">
            <div class="settings-row">
              <div class="settings-label">Provider</div>
              <select v-model="provider" @change="onProviderChange" class="settings-input">
                <option v-for="o in PROVIDER_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>
            <div class="settings-row">
              <div class="settings-label">Base URL</div>
              <input v-model="baseUrl" class="settings-input" placeholder="https://api.openai.com/v1">
            </div>
            <div class="settings-row">
              <div class="settings-label">API Key</div>
              <input v-model="apiKey" type="password" class="settings-input" :placeholder="apiKeyPlaceholder">
            </div>
            <div class="settings-row">
              <div class="settings-label">Model</div>
              <input v-model="model" class="settings-input" id="settingsModel" placeholder="gpt-4o">
              <div class="settings-hint">{{ modelHint }}</div>
            </div>
          </div>

          <!-- Tab2: 分功能模型 -->
          <div :class="['settings-panel', { active: activeTab === 'roles' }]">
            <p class="settings-section-desc">每个功能可单独配置，留空则继承「AI 基础」设置。</p>
            <template v-for="r in ROLES" :key="r.key">
              <details class="settings-accordion">
                <summary>{{ r.label }}</summary>
                <div class="settings-accordion-body">
                  <div class="settings-row">
                    <div class="settings-label">Provider（留空继承基础）</div>
                    <select v-model="roles[r.key].provider" @change="onRoleProviderChange(r.key)" class="settings-input">
                      <option v-for="o in ROLE_PROVIDER_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
                    </select>
                  </div>
                  <div class="settings-row">
                    <div class="settings-label">Base URL</div>
                    <input v-model="roles[r.key].base_url" class="settings-input" placeholder="继承基础配置">
                  </div>
                  <div class="settings-row">
                    <div class="settings-label">API Key</div>
                    <input v-model="roles[r.key].api_key" type="password" class="settings-input" :placeholder="roles[r.key].api_key_placeholder">
                  </div>
                  <div class="settings-row">
                    <div class="settings-label">Model</div>
                    <input v-model="roles[r.key].model" class="settings-input" :id="'role-model-' + r.key" placeholder="继承基础配置">
                  </div>
                </div>
              </details>
            </template>
          </div>

          <!-- Tab3: 联网搜索 -->
          <div :class="['settings-panel', { active: activeTab === 'tavily' }]">
            <div class="settings-row">
              <div class="settings-label">Tavily API Key</div>
              <input v-model="tavilyKey" type="password" class="settings-input" :placeholder="tavilyKeyPlaceholder">
            </div>
            <p class="settings-hint">
              还没有 Tavily Key？
              <a class="settings-link" href="https://tavily.com/" target="_blank" rel="noopener">前往 tavily.com 免费申请 ↗</a>
              （每月 1000 次免费）
            </p>
          </div>

          <!-- Tab4: 数据库 -->
          <div :class="['settings-panel', { active: activeTab === 'database' }]">
            <div class="settings-row">
              <div class="settings-label">数据库类型</div>
              <select v-model="dbType" class="settings-input">
                <option v-for="o in DB_TYPE_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
            </div>

            <!-- PG / MySQL fields -->
            <template v-if="dbType === 'postgresql' || dbType === 'mysql'">
              <div class="settings-row">
                <div class="settings-label">Host</div>
                <input v-model="dbHost" class="settings-input" placeholder="127.0.0.1">
              </div>
              <div class="settings-row">
                <div class="settings-label">Port</div>
                <input v-model="dbPort" type="number" class="settings-input" :placeholder="dbType === 'mysql' ? '3306' : '5432'">
              </div>
              <div class="settings-row">
                <div class="settings-label">数据库名</div>
                <input v-model="dbName" class="settings-input" placeholder="aiterate">
              </div>
              <div class="settings-row">
                <div class="settings-label">用户名</div>
                <input v-model="dbUser" class="settings-input" placeholder="postgres">
              </div>
              <div class="settings-row">
                <div class="settings-label">密码</div>
                <input v-model="dbPassword" type="password" class="settings-input" placeholder="（留空则不修改）">
              </div>
            </template>

            <!-- SQLite fields -->
            <template v-if="dbType === 'sqlite'">
              <div class="settings-row">
                <div class="settings-label">SQLite 文件路径</div>
                <input v-model="dbSqlitePath" class="settings-input" placeholder="~/.aiterate/data.db">
              </div>
            </template>

            <!-- Oracle fields -->
            <template v-if="dbType === 'oracle'">
              <div class="settings-row">
                <div class="settings-label">Host</div>
                <input v-model="dbOracleHost" class="settings-input" placeholder="127.0.0.1">
              </div>
              <div class="settings-row">
                <div class="settings-label">Port</div>
                <input v-model="dbOraclePort" type="number" class="settings-input" placeholder="1521">
              </div>
              <div class="settings-row">
                <div class="settings-label">Service Name</div>
                <input v-model="dbServiceName" class="settings-input" placeholder="ORCL">
              </div>
              <div class="settings-row">
                <div class="settings-label">用户名</div>
                <input v-model="dbOracleUser" class="settings-input" placeholder="system">
              </div>
              <div class="settings-row">
                <div class="settings-label">密码</div>
                <input v-model="dbOraclePassword" type="password" class="settings-input" placeholder="（留空则不修改）">
              </div>
            </template>

            <p class="settings-hint" v-html="icon_warn + ' 修改后将立即重新连接数据库，请确认新库已初始化。'"></p>
          </div>

          <!-- Tab5: 学习 -->
          <div :class="['settings-panel', { active: activeTab === 'learn' }]">
            <div class="settings-row" style="flex-direction:column;align-items:flex-start;gap:12px;">
              <div class="settings-label">费曼检测通过分数</div>
              <div style="width:100%;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                  <span style="font-size:13px;color:var(--fg-1);">难度越高，学得越扎实</span>
                  <span style="font-size:22px;font-weight:700;color:var(--accent,#1a6ef5);min-width:52px;text-align:right;">{{ sliderDisplay }}<span style="font-size:13px;font-weight:400;color:var(--fg-1);"> 分</span></span>
                </div>
                <input type="range" v-model.number="feynmanPassScore" @input="onSliderInput" min="1" max="100"
                  style="width:100%;accent-color:var(--accent,#1a6ef5);height:6px;cursor:pointer;" />
                <div style="position:relative;margin-top:6px;height:16px;font-size:11px;color:var(--fg-2,#888);">
                  <span style="position:absolute;left:0;">1</span>
                  <span style="position:absolute;left:calc(49/99*100%);transform:translateX(-50%);">50</span>
                  <span style="position:absolute;left:calc(79/99*100%);transform:translateX(-50%);">80</span>
                  <span style="position:absolute;right:0;">100</span>
                </div>
              </div>
            </div>
            <p class="settings-hint" style="margin-top:8px;">费曼自测得分达到此分数才算通过，否则退回巩固。</p>
          </div>
        </div>
        <div class="modal-footer">
          <div class="modal-footer-left"></div>
          <div class="modal-footer-right">
            <button class="btn" @click="$emit('close')">取消</button>
            <button class="btn btn-primary" :disabled="saving" @click="save" v-html="icon_save + ' 保存'"></button>
          </div>
        </div>
      </div>
    </div>
  `,
});
