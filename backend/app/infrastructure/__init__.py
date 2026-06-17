"""基础设施层包

包含：
- event_store: 事件存储（SQLite 后端），提供追加式事件持久化
- merkle: Merkle 树实现，用于事件链完整性验证
- rollback_controller: 回退控制器，处理分析要点的回退逻辑
- cleanup_scheduler: 清理调度器，管理会话的延迟清理
- lineage_graph: 谱系图，追踪事件之间的依赖关系
"""
