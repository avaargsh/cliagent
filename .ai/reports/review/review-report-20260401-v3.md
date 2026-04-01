# 评审报告 · 20260401-v3

## 0. 评审范围

- 本轮评审聚焦 `OpenAIProvider` 落地相关改动：
  - `src/digital_employee/providers/openai_provider.py`
  - `src/digital_employee/bootstrap/factories.py`
  - `src/digital_employee/providers/catalog.py`
  - `src/digital_employee/providers/factory.py`
  - `src/digital_employee/providers/router.py`
  - `tests/unit/providers/test_openai_provider.py`
- 评审基线：
  - `.ai/temp/architect.md`
  - `.ai/temp/cli-spec.md`
  - `.ai/temp/package-plan.md`

## 1. 阻塞项

### 阻塞项 1：`OpenAIProvider` 在 `async` 边界内执行阻塞式网络 I/O，会卡住事件循环并失去取消能力

- 位置：
  - `src/digital_employee/providers/openai_provider.py:35-56`
  - `src/digital_employee/providers/openai_provider.py:108-120`
  - `.ai/temp/architect.md:77-80`
- 事实：
  - `complete()` 是 `async def`，但内部直接调用同步 `_post()`。
  - `_post()` 继续使用 `urllib.request.urlopen()` 执行真实 HTTP 请求。
  - 架构约束明确要求“所有跨层 I/O 必须可取消、可超时、可重试”。
- 影响：
  - 一旦 OpenAI 请求阻塞，`TurnEngine` 所在事件循环会被整段卡住，后台任务心跳、取消、并发 session 都会一起受影响。
  - 当前 `timeout` 只覆盖 socket 超时，不等于 `asyncio` 级可取消；`TaskSupervisor` 或后台 reclaim 无法及时中断该请求。
- 建议：
  - 至少把阻塞请求放到 `asyncio.to_thread()` 或专用执行器中，保证不阻塞事件循环。
  - 更稳妥的方案是把 provider HTTP 调用下沉到真正的异步 adapter，再补超时/重试策略。

### 阻塞项 2：OpenAI 适配层丢弃 `ContextAssembler` 产出的历史上下文，并把工具结果伪装成新的 `user` 消息，导致多回合工具链不正确

- 位置：
  - `src/digital_employee/runtime/turn/context_assembler.py:64-99`
  - `src/digital_employee/runtime/turn/engine.py:311-345`
  - `src/digital_employee/providers/openai_provider.py:77-89`
- 事实：
  - `ContextAssembler` 已把 `recent_context` 和 `context_compaction` 放入 `request.metadata`。
  - `TurnEngine` 在工具执行后会把 `tool` 消息写回 session，并进入下一回合。
  - `OpenAIProvider._build_messages()` 只发送 `developer + user(prompt)`，再把 `tool_observations` 拼成新的 `user` 文本，完全没有消费 `recent_context`，也没有保留工具回合的结构化消息关系。
- 影响：
  - 历史上下文压缩链路对 `openai` provider 基本失效，恢复执行、长对话和多回合推理会退化成“只看当前 prompt”。
  - 工具执行后的继续推理不再基于真实的会话消息流，而是基于二次摘要文本，容易出现重复调用、遗漏上下文或回答与工具结果不一致。
- 建议：
  - 把 `recent_context` 映射成 provider 可消费的消息数组，至少保留 `user / assistant / tool` 的顺序和内容。
  - 工具续跑不要再把观察结果塞成新的 `user` 文本，而应沿用 session 中已经记录的消息事实，保持 provider 看到的对话状态与 runtime 一致。

## 2. 建议项

### 建议项 1：新增测试只覆盖单次序列化和首轮 tool call，未覆盖 `TurnEngine + OpenAIProvider` 的真实多回合路径

- 位置：
  - `tests/unit/providers/test_openai_provider.py:87-212`
  - `tests/unit/runtime/test_turn_engine.py:191-215`
- 现状：
  - 当前新增测试验证了请求体字段、首轮 tool call 解析、HTTP/连接错误映射。
  - 但没有把 `OpenAIProvider` 接到 `TurnEngine.run()` 中，验证 `recent_context`、工具执行后继续推理、审批暂停/恢复等主链路。
- 风险：
  - 当前两个阻塞问题都不会被这组测试发现，因此回归通过并不代表运行时链路正确。
- 建议：
  - 补一组 `TurnEngine` 级测试，使用 patched `urlopen` 或 capturing fake provider，覆盖“tool call -> tool executed -> second completion”与“resume after approval”两条路径。

## 3. 分类扫描补充

### 分层与依赖问题

- 阻塞项 2 本质上也是分层契约偏差：`runtime.turn` 已经准备好的上下文契约没有被 `providers.openai_provider` 消费。

### 并发 / 取消 / 超时风险

- 阻塞项 1 成立，当前实现不满足架构约束中的异步 I/O 要求。

### 配置与密钥泄露风险

- 未发现本轮新增代码把 `Authorization` 或 API Key 明文写入状态文件、报告或 CLI 输出。

### 输出协议与 CLI 规范偏差

- 本轮未直接修改 CLI 输出层，未发现新的 `stdout/stderr/--json` 协议回归。

### 缺失测试与回归风险

- 建议项 1 成立，`OpenAIProvider` 目前只有 adapter 级单测，没有覆盖到 runtime 主链路。

## 4. 结论

- 发现 **2 个阻塞项**，都位于 `OpenAIProvider` 接入层。
- 当前实现已经具备“能发请求、能收首轮 tool call”的最小能力，但还不满足架构文档对异步执行和多回合上下文一致性的要求。
- **结论：不建议进入 QA，需退回 P6 修复后再评审。**
