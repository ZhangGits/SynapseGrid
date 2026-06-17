"""SynapseGrid 后端应用包

该包是 SynapseGrid MVP 后端的根包，包含以下模块：
- agents: AI Agent 实现（研究、验证、综合）
- api: REST API 路由
- core: 核心业务逻辑（编排器、会话管理、状态机、日志配置）
- infrastructure: 基础设施层（事件存储、Merkle树、回滚控制、清理调度）
- schemas: Pydantic 数据模型
- services: 服务层（成本追踪、模板引擎、Token计数、后处理）
- templates: 场景模板文件
"""
