// ── KnowledgeTreeModal.js ────────────────────────────────────────────────

import { defineComponent, ref, onMounted } from 'vue';
import { api } from '../../api.js';
import { icon } from '../../icons.js';
import { escapeHtml } from '../../utils.js';

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
        const masteryData = await api.getKnowledgeMastery();
        treeHtml.value = (masteryData.tree || []).map(n => renderDomain(n)).join('');
      } catch (err) {
        console.error('knowledge tree error', err);
      }
    });
    
    function masteryBadge(node) {
      const score = node.mastery_score || 0;
      const status = node.status || 'unseen';
      if (status === 'mastered') return `<span class="kt-mastery-badge kt-mastery-mastered">${score}%</span>`;
      if (status === 'reviewing') return `<span class="kt-mastery-badge kt-mastery-reviewing">${score}%</span>`;
      if (status === 'learning') return `<span class="kt-mastery-badge kt-mastery-learning">${score}%</span>`;
      if (status === 'weak') return `<span class="kt-mastery-badge kt-mastery-weak">${score}%</span>`;
      if (score > 0) return `<span class="kt-mastery-badge kt-mastery-untouched">${score}%</span>`;
      return '';
    }

    function nodeIssues(node) {
      const parts = [];
      if (node.gap_count > 0) parts.push(`${node.gap_count} gaps`);
      if (node.low_score_count > 0) parts.push(`${node.low_score_count} 低分`);
      if (node.review_due_count > 0) parts.push(`${node.review_due_count} 待复习`);
      return parts.length > 0 ? `<span class="kt-node-issues">${parts.join(' · ')}</span>` : '';
    }

    function touchedCount(node) {
      let count = (node.total_sessions || 0) > 0 ? 1 : 0;
      if (node.children) for (const c of node.children) count += touchedCount(c);
      return count;
    }
    
    function renderChild(node, depth) {
      const total = node.total_sessions || 0;
      const hasProgress = total > 0;
      const hasChildren = node.children?.length > 0;
      const indent = (depth - 1) * 20;
      
      let childrenHtml = '';
      if (hasChildren) childrenHtml = node.children.map(c => renderChild(c, depth + 1)).join('');
      if (!hasProgress && !hasChildren && depth > 1) return '';
      
      return `<div class="kt-child" style="padding-left:${indent}px">
        <div class="kt-child-row">
          ${masteryBadge(node)}
          <span class="kt-child-title">${escapeHtml(node.title || node.id)}</span>
          ${nodeIssues(node)}
        </div>${childrenHtml}</div>`;
    }
    
    function renderDomain(node) {
      const iconName = domainIcons[node.title] || 'book';
      const touched = touchedCount(node);
      const hasChildren = node.children?.length > 0;
      const childrenHtml = hasChildren ? node.children.map(c => renderChild(c, 1)).join('') : '';
      
      return `<div class="kt-domain-card">
        <div class="kt-domain-header" onclick="const c=this.parentElement,b=c.querySelector('.kt-domain-body'),a=c.querySelector('.kt-arrow');b.style.display=b.style.display==='none'?'block':'none';a.textContent=b.style.display==='none'?'▶':'▼'">
          <span class="kt-arrow">▶</span>
          <span class="kt-domain-icon">${icon(iconName)}</span>
          <span class="kt-domain-title">${escapeHtml(node.title)}</span>
          ${masteryBadge(node)}
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
