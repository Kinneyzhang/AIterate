# LearnSystem 双模式改造计划

目标：在不拆底层数据模型的前提下，为学习系统加入“简单模式 / 专业模式”双界面，并将长滚动页重构为 tab 导航结构。

范围：
1. 后端新增 profile / task_feedback / recommendation 相关存储与 API
2. 保留现有 domains / sessions / guided_tasks / concepts / connections 作为统一底层
3. 前端新增 mode switch、一级 tabs（学习/统计/设置）
4. 简单模式：极简推荐闭环（接受/拒绝/换一个）
5. 专业模式：显示高级配置和完整功能，但全部保留默认值

执行顺序：
1. 扩展 learn_db.py
   - 新表：profile_settings, task_feedback
   - 新方法：get_profile, upsert_profile, add_task_feedback, get_recent_feedback
   - 推荐聚合：build_recommendation_candidates / get_recommendation_signals
2. 扩展 learn_server.py
   - GET/PATCH /api/profile
   - GET /api/recommendations
   - POST /api/recommendations/{id}/accept
   - POST /api/recommendations/{id}/reject
   - POST /api/recommendations/regenerate
3. 前端 index.html 重写
   - 顶部 mode switch
   - 一级 tabs: 学习 / 统计 / 设置
   - 简单模式页面：推荐卡片、当前任务、提交输出、AI反馈
   - 专业模式页面：推荐任务、任务队列、提交输出、会话、跨域连接、月度复盘
4. 服务重启与验收
   - py_compile
   - systemctl --user restart learn-system.service
   - curl 验证新增 API
   - 浏览器验证模式切换和 tab

默认策略：
- mode 默认 simple
- daily_minutes_goal 默认 25
- default_difficulty 默认 adaptive
- default_output_style 默认 short_explanation
- 默认推荐优先级：
  1. 用户高兴趣领域
  2. 最近有材料设置的领域
  3. 最近较少学习的领域补位

拒绝原因标准化：
- boring
- too_hard
- too_easy
- too_abstract
- not_now
- duplicate

简单模式推荐卡片字段：
- title
- domain
- estimated_minutes
- why_recommended
- accept
- reject
- regenerate

专业模式扩展字段：
- preferred_domains
- disliked_topics
- daily_minutes_goal
- default_difficulty
- default_output_style
- advanced options 可选展开
