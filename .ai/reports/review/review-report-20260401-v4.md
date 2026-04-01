# 评审报告 · 20260401-v4（回归评审）

## 0. 评审范围

- 本轮评审是对 `review-report-20260401-v3.md` 两个阻塞项的回归确认。
- 聚焦文件：
  - `src/digital_employee/providers/openai_provider.py`
  - `src/digital_employee/runtime/turn/engine.py`
  - `src/digital_employee/memory/context_compactor.py`
  - `tests/unit/providers/test_openai_provider.py`
  - `tests/unit/runtime/test_turn_engine.py`
  - `tests/unit/memory/test_context_compactor.py`

## 1. 阻塞项回归结论

### 未发现阻塞问题

- 前次阻塞项 1 已修复：
  - `src/digital_employee/providers/openai_provider.py:56-57` 现在通过 `asyncio.to_thread()` 执行阻塞式 HTTP 请求，避免直接卡住事件循环。
  - `tests/unit/providers/test_openai_provider.py:268-283` 已补非阻塞回归用例。
- 前次阻塞项 2 已修复：
  - `src/digital_employee/providers/openai_provider.py:78-103` 已开始消费 `context_compaction` 和 `recent_context`。
  - `src/digital_employee/providers/openai_provider.py:191-251` 已按 `assistant/tool` 结构重建历史消息。
  - `src/digital_employee/runtime/turn/engine.py:169-230`、`src/digital_employee/runtime/turn/engine.py:317-326` 已把 `tool_call_id` 写入 session 消息链路。
  - `src/digital_employee/memory/context_compactor.py:75-99`、`src/digital_employee/memory/context_compactor.py:140-142` 已避免压缩阶段丢掉“空文本但带 tool_calls”的 assistant 消息。
  - `tests/unit/runtime/test_turn_engine.py:270-352` 已覆盖 `tool call -> tool executed -> second completion` 主链。

## 2. 建议项

### 建议项 1：`asyncio.to_thread()` 解决了事件循环阻塞，但还不等于真正可取消的 HTTP 适配器

- 位置：
  - `src/digital_employee/providers/openai_provider.py:56-57`
- 现状：
  - 当前实现已经避免阻塞事件循环，这是本轮必须修复的问题。
  - 但当外层 task 被取消时，底层线程中的 `urlopen()` 仍会继续跑到 socket 超时或请求结束。
- 风险：
  - 在高并发或大量超时请求时，线程池中的悬挂请求仍会占用资源。
- 建议：
  - 后续如果要严格兑现架构中的“可取消”语义，仍建议把 provider HTTP 调用替换成真正的异步 adapter。

### 建议项 2：OpenAI 主链测试已覆盖二次 completion，但尚未覆盖“审批通过后 resume”路径

- 位置：
  - `tests/unit/runtime/test_turn_engine.py:270-352`
- 现状：
  - 目前已覆盖 `tool call -> tool executed -> second completion`。
  - 但还没有把 `waiting_approval -> approval decide -> resume` 与 `OpenAIProvider` 串起来验证。
- 风险：
  - 恢复链路依赖 session 历史回放；虽然当前结构化消息链已经补齐，但该路径仍缺少直接回归保护。
- 建议：
  - 后续补一条 resume 场景测试，确认审批后的同 session 恢复仍能正确拼装历史消息。

## 3. 分类扫描补充

### 分层与依赖问题

- 本轮未发现新的分层破坏。`provider` 仍只做模型协议适配，没有倒灌业务仓储依赖。

### 并发 / 取消 / 超时风险

- 前次“事件循环被阻塞”的阻塞项已关闭。
- 残余风险见建议项 1。

### 配置与密钥泄露风险

- 未发现新增代码把 API Key、Authorization 头或完整请求体写入状态文件、日志或 CLI 输出。

### 输出协议与 CLI 规范偏差

- 本轮未修改 CLI 输出层，未发现新的协议偏差。

### 缺失测试与回归风险

- 前次“没有 runtime 主链测试”的问题已关闭。
- 残余风险见建议项 2。

## 4. 结论

- 前次 2 个阻塞项均已修复，并有对应测试覆盖。
- 当前仅剩 2 个非阻塞建议项，不影响进入 QA。
- **结论：建议进入 QA 验收。**
