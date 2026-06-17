# 修复任务清单

- [x] 修复 apiClient.ts 中 sendFeedback 路径错误（sessions → tasks）
- [x] 修复 apiClient.ts 中 verifySession 路径错误
- [x] 修复 apiClient.ts 中 branchSession 路径不存在问题
- [x] 修复 rollback_controller.py 中 finding ID 过滤逻辑缺陷
- [x] 修复 state_machine.py 中 SynthesisRestored 缺少 canvas_schema 提取
- [x] 修复 orchestrator.py 中 process_feedback EXPLORATORY 分支缺少 Verification/Synthesis
- [x] 修复 session_manager.py 中 _noop 任务泄漏
- [x] 修复 post_processor.py 中 HMAC 密钥硬编码问题（添加环境变量检查警告）
- [x] 修复 main.py 中 CORS 配置注释（添加生产环境提醒）
- [x] 修复 main.py 中健康检查临时文件安全问题
- [x] 提取公共方法减少代码冗余
- [x] 构建验证
