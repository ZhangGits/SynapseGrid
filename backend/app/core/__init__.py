"""核心业务逻辑包

包含：
- orchestrator: 任务编排器，协调 Research→Verification→Synthesis 三阶段流水线
- session_manager: 会话生命周期管理，单写者队列模式
- state_machine: 内存状态投影，从追加事件存储重建
- logging_config: 中央日志配置
"""
