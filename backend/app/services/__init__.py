"""服务层包

包含：
- cost_tracker: 成本追踪，跟踪每次 LLM 调用的 Token 消耗和费用
- post_processor: 后处理器，添加审计头、计算内容签名
- template_engine: 模板引擎，管理场景模板的加载和渲染
- token_counter: Token 计数器，估算文本的 Token 数量
"""
