// ── KnowledgeTreeModal.js ────────────────────────────────────────────────

import { defineComponent, ref, onMounted } from 'vue';
import { api } from '../../api.js?v=027';
import { icon } from '../../icons.js?v=027';

const domainIcons = {
  '计算机': 'monitor',
  '写作': 'edit',
  '心理学': 'brain',
  '哲学': 'atom',
};

export default defineComponent({
  emits: ['close'],
  
  setup() {
    const treeHtml = ref('');
    
    onMounted(async () => {
      try {
        const [treeData, progressData] = await Promise.all([
          api.getKnowledgeTree(),
          api.getKnowledgeProgress(),
        ]);
        const tree = treeData.tree || [];
        const progMap = {};
        for (const p of progressData.progress || []) progMap[p.node_id] = p;
        
        treeHtml.value = tree.map(n => renderDomain(n, progMap)).join('');
      } catch (err) {
        console.error('knowledge tree error', err);
      }
    });
    
    function statusDotCls(p) {
      const total = p?.total_sessions || 0;
      const completed = p?.completed_sessions || 0;
      const active = p?.active_sessions || 0;
      if (completed === total && total > 0) return 'kt-dot-mastered';
      if (active > 0) return 'kt-dot-learning';
      if (total > 0) return 'kt-dot-review';
      return 'kt-dot-untouched';
    }
    
    function touchedCount(node, progMap) {
      const p = progMap[node.id];
      let count = (p?.total_sessions || 0) > 0 ? 1 : 0;
      if (node.children) for (const c of node.children) count += touchedCount(c, progMap);
      return count;
    }
    
    function renderChild(node, progMap, depth) {
      const p = progMap[node.id];
      const total = p?.total_sessions || 0;
      const hasProgress = total > 0;
      const hasChildren = node.children?.length > 0;
      const dotCls = hasProgress ? statusDotCls(p) : 'kt-dot-untouched';
      const indent = (depth - 1) * 20;
      
      let childrenHtml = '';
      if (hasChildren) childrenHtml = node.children.map(c => renderChild(c, progMap, depth + 1)).join('');
      if (!hasProgress && !hasChildren && depth > 1) return '';
      
      return `<div class="kt-child" style="padding-left:${indent}px">
        <div class="kt-child-row">
          <span class="kt-dot ${dotCls}"></span>
          <span class="kt-child-title">${node.title || node.id}</span>
        </div>${childrenHtml}</div>`;
    }
    
    function renderDomain(node, progMap) {
      const iconName = domainIcons[node.title] || 'book';
      const touched = touchedCount(node, progMap);
      const hasChildren = node.children?.length > 0;
      const childrenHtml = hasChildren ? node.children.map(c => renderChild(c, progMap, 1)).join('') : '';
      
      return `<div class="kt-domain-card">
        <div class="kt-domain-header" onclick="const c=this.parentElement,b=c.querySelector('.kt-domain-body'),a=c.querySelector('.kt-arrow');b.style.display=b.style.display==='none'?'block':'none';a.textContent=b.style.display==='none'?'▶':'▼'">
          <span class="kt-arrow">▶</span>
          <span class="kt-domain-icon">${icon(iconName)}</span>
          <span class="kt-domain-title">${node.title}</span>
          ${touched > 0 ? `<span class="kt-domain-touched">${touched} 个知识点</span>` : ''}
        </div>
        <div class="kt-domain-body" style="display:none">${childrenHtml || '<div class="kt-child-empty">暂无子节点</div>'}</div>
      </div>`;
    }
    
    return { treeHtml, icon };
  },
  
  template: `
    <div class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-box knowledge-tree-modal" role="dialog" style="max-width:540px; max-height:85vh;">
        <div class="modal-header">
          <div class="modal-title" v-html="icon('compass') + ' 知识地图'"></div>
          <button class="modal-close" @click="$emit('close')">✕</button>
        </div>
        <div class="modal-body kt-modal-body">
          <div class="kt-legend">
            <span><span class="kt-dot kt-dot-mastered"></span> 已掌握</span>
            <span><span class="kt-dot kt-dot-learning"></span> 学习中</span>
            <span><span class="kt-dot kt-dot-review"></span> 待复习</span>
            <span><span class="kt-dot kt-dot-untouched"></span> 未触及</span>
          </div>
          <div class="kt-tree" v-html="treeHtml || '<div class=\\'muted\\'>还没有绑定知识节点的 session</div>'"></div>
        </div>
      </div>
    </div>
  `,
});
