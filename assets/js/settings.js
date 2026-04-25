// ── settings.js ──────────────────────────────────────────────────────────────
// 设置页面 modal

import { getSettings, saveSettings } from './api.js';

const PROVIDER_PRESETS = {
  openai: {
    base_url: 'https://api.openai.com/v1',
    models: 'gpt-4o / gpt-4o-mini / o1',
  },
  deepseek: {
    base_url: 'https://api.deepseek.com/v1',
    models: 'deepseek-v4-pro / deepseek-v4-flash / deepseek-chat',
  },
  kimi: {
    base_url: 'https://api.moonshot.cn/v1',
    models: 'moonshot-v1-8k / moonshot-v1-32k / moonshot-v1-128k',
  },
  doubao: {
    base_url: 'https://ark.cn-beijing.volces.com/api/v3',
    models: 'doubao-pro-32k / doubao-pro-4k / deepseek-v3-241226',
  },
  copilot: {
    base_url: 'https://api.githubcopilot.com',
    models: 'gpt-4o / claude-sonnet-4-5 / gemini-2.0-flash-001',
    hint: 'API Key 填 GitHub OAuth token（GHU_ 开头），通过 Device Code 授权获取',
  },
  gemini: {
    base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
    models: 'gemini-2.0-flash / gemini-2.5-pro',
  },
  anthropiccompat: {
    base_url: 'https://api.anthropic.com/v1',
    models: 'claude-sonnet-4-5 / claude-opus-4',
  },
  openrouter: {
    base_url: 'https://openrouter.ai/api/v1',
    models: 'any model slug',
  },
  custom: {
    base_url: '',
    models: '',
  },
};

const ROLES = [
  { key: 'title', label: '标题生成 (title)' },
  { key: 'answer', label: '回答生成 (answer)' },
  { key: 'evaluate', label: '评估 (evaluate)' },
  { key: 'review', label: '费曼 (review)' },
  { key: 'deepen', label: '深化追问 (deepen)' },
];

// ── 自定义 Select 控件（替代原生 select，避免原生弹出层与 GPU 合成层冲突导致的闪烁）──
// 用法：const sel = createCustomSelect(options, initialValue, onChange)
//       sel.el   → DOM 元素，插入页面
//       sel.value → 当前选中值（可读可写）
function createCustomSelect(options, initialValue, onChange) {
  let currentValue = initialValue || options[0]?.value || '';
  let isOpen = false;

  const wrapper = document.createElement('div');
  wrapper.className = 'csel';

  const trigger = document.createElement('div');
  trigger.className = 'csel-trigger settings-input';
  trigger.tabIndex = 0;
  trigger.setAttribute('role', 'combobox');
  trigger.setAttribute('aria-expanded', 'false');

  const triggerText = document.createElement('span');
  triggerText.className = 'csel-text';

  const triggerArrow = document.createElement('span');
  triggerArrow.className = 'csel-arrow';
  triggerArrow.innerHTML = '&#9660;';

  trigger.appendChild(triggerText);
  trigger.appendChild(triggerArrow);

  const dropdown = document.createElement('div');
  dropdown.className = 'csel-dropdown';

  function getLabel(val) {
    return options.find(o => o.value === val)?.label || val;
  }

  function renderOptions() {
    dropdown.innerHTML = '';
    options.forEach(opt => {
      const item = document.createElement('div');
      item.className = 'csel-option' + (opt.value === currentValue ? ' selected' : '');
      item.textContent = opt.label;
      item.dataset.value = opt.value;
      item.addEventListener('mousedown', e => {
        e.preventDefault(); // 防止 trigger 失焦
        select(opt.value);
      });
      dropdown.appendChild(item);
    });
  }

  function open() {
    if (isOpen) return;
    isOpen = true;
    wrapper.classList.add('open');
    trigger.setAttribute('aria-expanded', 'true');
    renderOptions();
    // 定位到当前选中项
    requestAnimationFrame(() => {
      const selected = dropdown.querySelector('.csel-option.selected');
      if (selected) selected.scrollIntoView({ block: 'nearest' });
    });
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    wrapper.classList.remove('open');
    trigger.setAttribute('aria-expanded', 'false');
  }

  function select(val) {
    currentValue = val;
    triggerText.textContent = getLabel(val);
    close();
    onChange && onChange(val);
  }

  // 初始显示
  triggerText.textContent = getLabel(currentValue);

  trigger.addEventListener('click', () => isOpen ? close() : open());

  trigger.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); isOpen ? close() : open(); }
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      const idx = options.findIndex(o => o.value === currentValue);
      if (idx < options.length - 1) select(options[idx + 1].value);
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      const idx = options.findIndex(o => o.value === currentValue);
      if (idx > 0) select(options[idx - 1].value);
    }
  });

  // 点击外部关闭
  document.addEventListener('click', function onOutside(e) {
    if (!wrapper.contains(e.target)) {
      close();
      // 如果 modal 已关闭则移除监听
      if (!document.contains(wrapper)) document.removeEventListener('click', onOutside);
    }
  });

  wrapper.appendChild(trigger);
  wrapper.appendChild(dropdown);

  return {
    el: wrapper,
    get value() { return currentValue; },
    set value(v) {
      currentValue = v;
      triggerText.textContent = getLabel(v);
    },
  };
}

const PROVIDER_OPTIONS = [
  { value: 'openai',          label: 'OpenAI' },
  { value: 'deepseek',        label: 'DeepSeek' },
  { value: 'kimi',            label: 'Kimi（月之暗面）' },
  { value: 'doubao',          label: '豆包（火山引擎）' },
  { value: 'copilot',         label: 'GitHub Copilot' },
  { value: 'gemini',          label: 'Gemini' },
  { value: 'anthropiccompat', label: 'Anthropic（兼容格式）' },
  { value: 'openrouter',      label: 'OpenRouter' },
  { value: 'custom',          label: 'Custom' },
];

const ROLE_PROVIDER_OPTIONS = [
  { value: '',               label: '— 继承基础 —' },
  ...PROVIDER_OPTIONS,
];

function buildRoleAccordion(role, data = {}) {
  return `
    <details class="settings-accordion" data-role="${role.key}">
      <summary>${role.label}</summary>
      <div class="settings-accordion-body">
        <div class="settings-row">
          <div class="settings-label">Provider（留空继承基础）</div>
          <div class="csel-placeholder" data-role="${role.key}" data-type="provider"></div>
        </div>
        <div class="settings-row">
          <div class="settings-label">Base URL</div>
          <input type="text" class="settings-input role-base-url" data-role="${role.key}" placeholder="继承基础配置" value="${data.base_url || ''}">
        </div>
        <div class="settings-row">
          <div class="settings-label">API Key</div>
          <input type="password" class="settings-input role-api-key" data-role="${role.key}" placeholder="继承基础配置" value="${data.api_key || ''}">
        </div>
        <div class="settings-row">
          <div class="settings-label">Model</div>
          <input type="text" class="settings-input role-model" data-role="${role.key}" placeholder="继承基础配置" value="${data.model || ''}">
        </div>
      </div>
    </details>`;
}

export function openSettings() {
  const existing = document.getElementById('settingsModal');
  if (existing) existing.remove();

  const el = document.createElement('div');
  el.id = 'settingsModal';
  el.className = 'modal-overlay';
  el.innerHTML = `
    <div class="modal-box modal-box-lg" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
      <div class="modal-header">
        <div class="modal-title" id="settingsTitle">⚙️ 设置</div>
        <button class="modal-close" aria-label="关闭" id="settingsCloseBtn">✕</button>
      </div>
      <div class="settings-tabs" id="settingsTabs">
        <button class="settings-tab active" data-panel="basic">AI 基础</button>
        <button class="settings-tab" data-panel="roles">分功能模型</button>
        <button class="settings-tab" data-panel="tavily">联网搜索</button>
        <button class="settings-tab" data-panel="database">数据库</button>
        <button class="settings-tab" data-panel="learn">学习</button>
      </div>
      <div class="modal-body settings-modal-body">
        <!-- Tab1: 基础 -->
        <div class="settings-panel active" id="settings-panel-basic">
          <div class="settings-row">
            <div class="settings-label">Provider</div>
            <div id="settingsProviderWrap"></div>
          </div>
          <div class="settings-row">
            <div class="settings-label">Base URL</div>
            <input type="text" class="settings-input" id="settingsBaseUrl" placeholder="https://api.openai.com/v1">
          </div>
          <div class="settings-row">
            <div class="settings-label">API Key</div>
            <input type="password" class="settings-input" id="settingsApiKey" placeholder="sk-...">
          </div>
          <div class="settings-row">
            <div class="settings-label">Model</div>
            <input type="text" class="settings-input" id="settingsModel" placeholder="gpt-4o">
            <div class="settings-hint" id="settingsModelHint"></div>
          </div>
        </div>

        <!-- Tab2: 分功能模型 -->
        <div class="settings-panel" id="settings-panel-roles">
          <p class="settings-section-desc">每个功能可单独配置，留空则继承「AI 基础」设置。</p>
          <div id="settingsRolesContainer"></div>
        </div>

        <!-- Tab3: 联网搜索 -->
        <div class="settings-panel" id="settings-panel-tavily">
          <div class="settings-row">
            <div class="settings-label">Tavily API Key</div>
            <input type="password" class="settings-input" id="settingsTavilyKey" placeholder="tvly-...">
          </div>
          <p class="settings-hint">
            还没有 Tavily Key？
            <a class="settings-link" href="https://tavily.com/" target="_blank" rel="noopener">前往 tavily.com 免费申请 ↗</a>
            （每月 1000 次免费）
          </p>
        </div>

        <!-- Tab4: 数据库 -->
        <div class="settings-panel" id="settings-panel-database">
          <div class="settings-row">
            <div class="settings-label">数据库类型</div>
            <div id="settingsDbTypeWrap"></div>
          </div>
          <div id="settingsDbPgFields">
            <div class="settings-row">
              <div class="settings-label">Host</div>
              <input type="text" class="settings-input" id="settingsDbHost" placeholder="127.0.0.1">
            </div>
            <div class="settings-row">
              <div class="settings-label">Port</div>
              <input type="number" class="settings-input" id="settingsDbPort" placeholder="5432">
            </div>
            <div class="settings-row">
              <div class="settings-label">数据库名</div>
              <input type="text" class="settings-input" id="settingsDbName" placeholder="aiterate">
            </div>
            <div class="settings-row">
              <div class="settings-label">用户名</div>
              <input type="text" class="settings-input" id="settingsDbUser" placeholder="postgres">
            </div>
            <div class="settings-row">
              <div class="settings-label">密码</div>
              <input type="password" class="settings-input" id="settingsDbPassword" placeholder="（留空则不修改）">
            </div>
          </div>
          <div id="settingsDbSqliteFields" style="display:none">
            <div class="settings-row">
              <div class="settings-label">SQLite 文件路径</div>
              <input type="text" class="settings-input" id="settingsDbSqlitePath" placeholder="~/.aiterate/data.db">
            </div>
          </div>
          <div id="settingsDbOracleFields" style="display:none">
            <div class="settings-row">
              <div class="settings-label">Host</div>
              <input type="text" class="settings-input" id="settingsDbOracleHost" placeholder="127.0.0.1">
            </div>
            <div class="settings-row">
              <div class="settings-label">Port</div>
              <input type="number" class="settings-input" id="settingsDbOraclePort" placeholder="1521">
            </div>
            <div class="settings-row">
              <div class="settings-label">Service Name</div>
              <input type="text" class="settings-input" id="settingsDbServiceName" placeholder="ORCL">
            </div>
            <div class="settings-row">
              <div class="settings-label">用户名</div>
              <input type="text" class="settings-input" id="settingsDbOracleUser" placeholder="system">
            </div>
            <div class="settings-row">
              <div class="settings-label">密码</div>
              <input type="password" class="settings-input" id="settingsDbOraclePassword" placeholder="（留空则不修改）">
            </div>
          </div>
          <p class="settings-hint">⚠️ 修改后将立即重新连接数据库，请确认新库已初始化。</p>
        </div>

        <div class="settings-panel" id="settings-panel-learn">
          <div class="settings-row" style="flex-direction:column;align-items:flex-start;gap:12px;">
            <div class="settings-label">费曼检测通过分数</div>
            <div style="width:100%;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span style="font-size:13px;color:var(--fg-1);">难度越高，学得越扎实</span>
                <span id="feynmanPassDisplay" style="font-size:22px;font-weight:700;color:var(--accent,#1a6ef5);min-width:52px;text-align:right;">60<span style="font-size:13px;font-weight:400;color:var(--fg-1);"> 分</span></span>
              </div>
              <input type="range" id="settingsFeynmanPassScore" min="1" max="100" value="60"
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
          <button class="btn" id="settingsCancelBtn">取消</button>
          <button class="btn btn-primary" id="settingsSaveBtn">💾 保存</button>
        </div>
      </div>
    </div>`;

  document.body.appendChild(el);

  // ── 主 Provider 自定义 select ──
  const baseUrlInput = document.getElementById('settingsBaseUrl');
  const modelInput   = document.getElementById('settingsModel');
  const modelHint    = document.getElementById('settingsModelHint');

  const providerSel = createCustomSelect(PROVIDER_OPTIONS, 'openai', val => {
    const preset = PROVIDER_PRESETS[val];
    if (preset) {
      if (preset.base_url) baseUrlInput.value = preset.base_url;
      if (val !== 'custom') modelInput.placeholder = preset.models.split('/')[0].trim();
      modelHint.textContent = preset.hint || '';
    } else {
      modelHint.textContent = '';
    }
  });
  document.getElementById('settingsProviderWrap').appendChild(providerSel.el);

  // ── Build role accordions ──
  const rolesContainer = document.getElementById('settingsRolesContainer');
  rolesContainer.innerHTML = ROLES.map(r => buildRoleAccordion(r)).join('');

  // 给每个 accordion 注入自定义 select
  const roleSelects = {};
  rolesContainer.querySelectorAll('.csel-placeholder[data-type="provider"]').forEach(placeholder => {
    const roleKey = placeholder.dataset.role;
    const roleSel = createCustomSelect(ROLE_PROVIDER_OPTIONS, '', val => {
      const preset = PROVIDER_PRESETS[val];
      if (preset && val !== '') {
        const buInput = rolesContainer.querySelector(`.role-base-url[data-role="${roleKey}"]`);
        if (buInput && preset.base_url) buInput.value = preset.base_url;
        const mInput = rolesContainer.querySelector(`.role-model[data-role="${roleKey}"]`);
        if (mInput && preset.models) mInput.placeholder = preset.models.split('/')[0].trim();
      }
    });
    placeholder.replaceWith(roleSel.el);
    roleSelects[roleKey] = roleSel;
  });

  // ── Tab switching ──
  document.getElementById('settingsTabs').addEventListener('click', e => {
    const btn = e.target.closest('.settings-tab');
    if (!btn) return;
    document.querySelectorAll('#settingsTabs .settings-tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.settings-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`settings-panel-${btn.dataset.panel}`)?.classList.add('active');
  });

  // ── Load current settings ──
  (async () => {
    try {
      const cfg = await getSettings();
      const llm = cfg.llm || {};
      if (llm.provider) providerSel.value = llm.provider;
      if (llm.base_url) baseUrlInput.value = llm.base_url;
      // API Key: 不再填充明文，根据 has_api_key 设置 placeholder
      const akEl = document.getElementById('settingsApiKey');
      akEl.value = '';
      akEl.placeholder = llm.has_api_key ? '已配置 (留空不修改)' : 'sk-...';
      if (llm.model) modelInput.value = llm.model;

      const tvEl = document.getElementById('settingsTavilyKey');
      tvEl.value = '';
      tvEl.placeholder = cfg.has_tavily_api_key ? '已配置 (留空不修改)' : 'tvly-...';

      const passScore = cfg.feynman_pass_score ?? 60;
      const sliderEl = document.getElementById('settingsFeynmanPassScore');
      const displayEl = document.getElementById('feynmanPassDisplay');
      sliderEl.value = passScore;
      displayEl.innerHTML = `${passScore}<span style="font-size:13px;font-weight:400;color:var(--fg-1);"> 分</span>`;
      sliderEl.addEventListener('input', () => {
        displayEl.innerHTML = `${sliderEl.value}<span style="font-size:13px;font-weight:400;color:var(--fg-1);"> 分</span>`;
      });

      const rolesData = llm.roles || {};
      ROLES.forEach(r => {
        const rd = rolesData[r.key] || {};
        const acc = rolesContainer.querySelector(`[data-role="${r.key}"]`);
        if (!acc) return;
        if (rd.provider && roleSelects[r.key]) roleSelects[r.key].value = rd.provider;
        const buInput = acc.querySelector('.role-base-url');
        const akInput = acc.querySelector('.role-api-key');
        const mInput  = acc.querySelector('.role-model');
        if (rd.base_url && buInput) buInput.value = rd.base_url;
        // Role API Key: 不填值，根据 has_api_key 设 placeholder
        if (akInput) {
          akInput.value = '';
          akInput.placeholder = rd.has_api_key ? '已配置 (留空不修改)' : '继承基础配置';
        }
        if (rd.model && mInput) mInput.value = rd.model;
      });
    } catch (err) {
      console.warn('Failed to load settings:', err);
    }
  })();

  // ── Close ──
  const close = () => el.remove();
  document.getElementById('settingsCloseBtn').addEventListener('click', close);
  document.getElementById('settingsCancelBtn').addEventListener('click', close);
  el.addEventListener('click', e => { if (e.target === el) close(); });
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
  });

  // ── DB Type 自定义 select ──
  const DB_TYPE_OPTIONS = [
    { value: 'sqlite',     label: 'SQLite（本地文件，默认）' },
    { value: 'postgresql', label: 'PostgreSQL' },
    { value: 'mysql',      label: 'MySQL' },
    { value: 'oracle',     label: 'Oracle' },
  ];

  function syncDbFields(dbType) {
    const pg  = document.getElementById('settingsDbPgFields');
    const sq  = document.getElementById('settingsDbSqliteFields');
    const ora = document.getElementById('settingsDbOracleFields');
    if (!pg) return;
    pg.style.display  = (dbType === 'postgresql' || dbType === 'mysql') ? '' : 'none';
    sq.style.display  = dbType === 'sqlite'  ? '' : 'none';
    ora.style.display = dbType === 'oracle'  ? '' : 'none';
    // 端口默认值
    const portEl = document.getElementById('settingsDbPort');
    if (portEl && !portEl.value) {
      portEl.placeholder = dbType === 'mysql' ? '3306' : '5432';
    }
  }

  const dbTypeSel = createCustomSelect(DB_TYPE_OPTIONS, 'postgresql', val => {
    syncDbFields(val);
  });
  document.getElementById('settingsDbTypeWrap').appendChild(dbTypeSel.el);
  syncDbFields('postgresql');

  // ── Load DB config ──
  (async () => {
    try {
      const resp = await fetch('/api/db-config', {
        headers: { 'X-Admin-Token': window.AITERATE_TOKEN || '' }
      });
      const cfg  = await resp.json();
      const t    = cfg.type || 'postgresql';
      dbTypeSel.value = t;
      syncDbFields(t);
      const set = (id, val) => { const el = document.getElementById(id); if (el && val) el.value = val; };
      if (t === 'oracle') {
        set('settingsDbOracleHost', cfg.host);
        set('settingsDbOraclePort', cfg.port);
        set('settingsDbServiceName', cfg.service_name);
        set('settingsDbOracleUser', cfg.user);
      } else if (t !== 'sqlite') {
        set('settingsDbHost', cfg.host);
        set('settingsDbPort', cfg.port);
        set('settingsDbName', cfg.dbname);
        set('settingsDbUser', cfg.user);
      } else {
        set('settingsDbSqlitePath', cfg.sqlite_path);
      }
    } catch(e) { console.warn('Failed to load db-config:', e); }
  })();

  // ── Save ──（覆盖原有 Save 按钮逻辑，改为分开保存）
  document.getElementById('settingsSaveBtn').addEventListener('click', async () => {
    const saveBtn = document.getElementById('settingsSaveBtn');
    saveBtn.disabled = true;
    saveBtn.textContent = '⏳ 保存中...';

    const rolesPayload = {};
    ROLES.forEach(r => {
      const provider = roleSelects[r.key]?.value || '';
      const base_url = rolesContainer.querySelector(`.role-base-url[data-role="${r.key}"]`)?.value.trim() || '';
      const api_key  = rolesContainer.querySelector(`.role-api-key[data-role="${r.key}"]`)?.value.trim() || '';
      const model    = rolesContainer.querySelector(`.role-model[data-role="${r.key}"]`)?.value.trim() || '';
      if (provider || base_url || api_key || model) {
        rolesPayload[r.key] = { provider, base_url, api_key, model };
      }
    });

    const payload = {
      llm: {
        provider: providerSel.value,
        base_url:  baseUrlInput.value.trim(),
        api_key:   document.getElementById('settingsApiKey').value.trim(),
        model:     modelInput.value.trim(),
        roles:     rolesPayload,
      },
      tavily_api_key: document.getElementById('settingsTavilyKey').value.trim(),
      feynman_pass_score: parseInt(document.getElementById('settingsFeynmanPassScore').value) || 60,
    };

    try {
      await saveSettings(payload);

      // 保存数据库配置
      const dbType = dbTypeSel.value;
      const g = id => document.getElementById(id)?.value.trim() || '';
      let dbPayload = { type: dbType };
      if (dbType === 'sqlite') {
        dbPayload.sqlite_path = g('settingsDbSqlitePath') || '~/.aiterate/data.db';
      } else if (dbType === 'oracle') {
        dbPayload.host         = g('settingsDbOracleHost');
        dbPayload.port         = parseInt(g('settingsDbOraclePort')) || 1521;
        dbPayload.service_name = g('settingsDbServiceName');
        dbPayload.user         = g('settingsDbOracleUser');
        const pw = g('settingsDbOraclePassword');
        if (pw) dbPayload.password = pw;
      } else {
        dbPayload.host   = g('settingsDbHost');
        dbPayload.port   = parseInt(g('settingsDbPort')) || (dbType === 'mysql' ? 3306 : 5432);
        dbPayload.dbname = g('settingsDbName');
        dbPayload.user   = g('settingsDbUser');
        const pw = g('settingsDbPassword');
        if (pw) dbPayload.password = pw;
      }
      const dbResp = await fetch('/api/db-config', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(window.AITERATE_TOKEN ? { 'X-Admin-Token': window.AITERATE_TOKEN } : {}),
        },
        body: JSON.stringify(dbPayload),
      });
      if (!dbResp.ok) {
        const err = await dbResp.json().catch(() => ({}));
        throw new Error(err.detail || 'DB 配置保存失败');
      }

      close();
    } catch (err) {
      alert(`保存失败：${err.message}`);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = '💾 保存';
    }
  });
}