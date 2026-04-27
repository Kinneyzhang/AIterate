// ── HomeRail.js ── 日拱一卒右侧栏 ───────────────────────────────────────

import { defineComponent, ref, computed, onMounted, watch } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '../api.js';
import { icon } from '../icons.js';
import { store, setNotice } from '../store.js';

export default defineComponent({
  setup() {
    const router = useRouter();
    const data = ref({});
    const loading = ref(false);
    const ready = ref(false);
    const error = ref('');

    function localDateKey(d = new Date()) {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
    }
    const today = localDateKey();

    async function loadRail(showLoading = false) {
      let loadingTimer = null;
      if (showLoading) loadingTimer = setTimeout(() => { loading.value = true; }, 120);
      try {
        data.value = await api.getCommandCenter();
        ready.value = true;
        error.value = '';
      } catch (err) {
        console.error('home rail error', err);
        error.value = err.message || '右侧栏加载失败';
        setNotice(`右侧栏加载失败：${error.value}`, 'error');
      } finally {
        if (loadingTimer) clearTimeout(loadingTimer);
        loading.value = false;
      }
    }

    onMounted(() => loadRail(true));
    watch(() => store.runtimeTick, tick => {
      if (tick > 0) loadRail(false);
    });

    const overdueReviews = computed(() => (data.value.review_due || []).filter(r => r.review_date < today));
    const todayReviews = computed(() => (data.value.review_due || []).filter(r => r.review_date >= today));
    const mustCount = computed(() => overdueReviews.value.length + (data.value.feynman_pending?.length || 0));
    const activeCount = computed(() => todayReviews.value.length + (data.value.active_sessions?.length || 0));
    const gapCount = computed(() => data.value.top_gaps?.length || 0);
    const upcomingCount = computed(() => data.value.upcoming_reviews?.length || 0);
    const health = computed(() => data.value.health || {});
    const healthProblems = computed(() =>
      (health.value.stale_preparing || 0) +
      (health.value.error_sessions || 0) +
      (health.value.parse_failures || 0)
    );
    const nextItems = computed(() => {
      const out = [];
      for (const r of overdueReviews.value.slice(0, 2)) {
        out.push({ kind: '逾期', title: r.title || '未命名', id: r.session_id, panel: 'review' });
      }
      for (const s of (data.value.feynman_pending || []).slice(0, 2)) {
        if (out.length >= 3) break;
        out.push({ kind: '费曼', title: s.title || '未命名', id: s.id, panel: 'review' });
      }
      for (const s of (data.value.active_sessions || []).slice(0, 3)) {
        if (out.length >= 3) break;
        out.push({ kind: '继续', title: s.title || '未命名', id: s.id, panel: s.status === 'deepening' || s.status === 'revising' ? 'deepen' : 'learn' });
      }
      return out;
    });

    function gotoSession(item) {
      const name = item.panel === 'review' ? 'session-review'
                 : item.panel === 'deepen' ? 'session-deepen'
                 : 'session-learn';
      router.push({ name, params: { id: item.id } });
    }

    return {
      icon, loading, ready, error,
      mustCount, activeCount, gapCount, upcomingCount, healthProblems, health,
      nextItems, gotoSession,
    };
  },

  template: `
    <aside class="home-rail" aria-label="日拱一卒侧栏">
      <div class="home-rail-card home-rail-summary">
        <div class="context-card-title" v-html="icon('target') + ' 今日概览'"></div>
        <div v-if="!ready && loading" class="context-empty">加载中…</div>
        <div v-else-if="error" class="context-empty">加载失败</div>
        <div v-else class="home-rail-stats">
          <div class="home-rail-stat urgent"><strong>{{ mustCount }}</strong><span>优先处理</span></div>
          <div class="home-rail-stat"><strong>{{ activeCount }}</strong><span>推进中</span></div>
          <div class="home-rail-stat"><strong>{{ gapCount }}</strong><span>薄弱点</span></div>
          <div class="home-rail-stat"><strong>{{ upcomingCount }}</strong><span>未来复习</span></div>
        </div>
      </div>

      <div class="home-rail-card">
        <div class="context-card-title" v-html="icon('zap') + ' 下一步'"></div>
        <template v-if="nextItems.length">
          <button v-for="item in nextItems" :key="item.kind + '-' + item.id" type="button" class="btn home-rail-next" @click="gotoSession(item)">
            <span class="cmd-badge cmd-badge-review">{{ item.kind }}</span>
            <span class="home-rail-next-title">{{ item.title }}</span>
          </button>
        </template>
        <div v-else class="context-empty">没有紧急事项，可以提一个新问题。</div>
      </div>

      <div class="home-rail-card">
        <div class="context-card-title" v-html="icon('target') + ' 推进原则'"></div>
        <ol class="home-rail-principles">
          <li>先清逾期复习</li>
          <li>再完成待费曼</li>
          <li>然后推进一个进行中问题</li>
          <li>最后再打开新问题</li>
        </ol>
      </div>

      <div class="home-rail-card">
        <div class="context-card-title" v-html="icon('gear') + ' 系统状态'"></div>
        <div v-if="healthProblems > 0" class="home-rail-health warning">
          <span v-if="health.stale_preparing > 0">{{ health.stale_preparing }} 个卡住</span>
          <span v-if="health.error_sessions > 0">{{ health.error_sessions }} 个报错</span>
          <span v-if="health.parse_failures > 0">{{ health.parse_failures }} 次解析失败</span>
        </div>
        <div v-else class="home-rail-health ok" v-html="icon('check') + ' 一切正常'"></div>
      </div>
    </aside>
  `,
});
