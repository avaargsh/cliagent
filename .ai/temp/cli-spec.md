# Python 数字员工控制面 CLI 规范

## 1. 文档范围与假设

- 本文档服务于 P3 阶段，定义 Python 数字员工平台的控制面 CLI，不定义 Web 控制台或企业 IM 交互细节。
- 当前仓库没有正式的 `.ai/temp/requirement.md`，因此本规范基于以下已知事实构建：
  - 用户目标是“重新设计 Python 人工智能数字员工 agent 架构”
  - 已批准的架构文档为 `.ai/temp/architect.md`
  - `.ai/context/product-constraint.md` 明确要求优先脚本化，交互只允许在 TTY 环境出现
- 本 CLI 的目标用户不是终端业务人员，而是：
  - 平台管理员
  - 集成开发者
  - QA / 运维人员
  - 需要调试数字员工执行过程的业务管理员
- 产品定位：
  - 主业务入口优先走 API、Webhook、企业 IM
  - CLI 是“控制面”和“运维面”，负责创建工作单、审批、观察、回放和诊断

## 2. 命令树

建议 CLI 名称：`dectl`

```text
dectl
├── config
│   ├── show
│   └── validate
├── employee
│   ├── list
│   ├── show <employee-id>
│   └── test <employee-id>
├── work-order
│   ├── create
│   ├── get <work-order-id>
│   ├── list
│   ├── run <work-order-id>
│   ├── watch <work-order-id>
│   ├── cancel <work-order-id>
│   ├── reclaim <work-order-id>
│   ├── resume <work-order-id>
│   └── artifacts <work-order-id>
├── approval
│   ├── list
│   ├── get <approval-id>
│   └── decide <approval-id>
├── session
│   ├── list
│   ├── get <session-id>
│   ├── tail <session-id>
│   └── export <session-id>
├── tool
│   ├── list
│   ├── show <tool-name>
│   └── dry-run
├── replay
│   └── run <work-order-id>
├── doctor
└── version
```

设计原则：

- 一级命令按控制对象分组，不按技术模块分组
- 所有命令都必须支持非交互式运行
- 所有查询类命令都必须支持稳定 `--json` 输出
- `--json/--jsonl/--tenant` 等全局参数必须写在资源命令前（`argparse` 全局参数规则）

## 3. 子命令用途

| 命令 | 用途 | 说明 |
|---|---|---|
| `config show` | 查看当前生效配置 | 用于确认 provider、tenant、profile、输出格式 |
| `config validate` | 校验配置合法性 | 检查缺失字段、冲突配置、密钥来源和租户边界 |
| `employee list` | 列出可用数字员工 | 展示角色、启用状态、默认模型、风险级别 |
| `employee show` | 查看单个数字员工画像 | 展示技能包、工具域、审批策略、知识域 |
| `employee test` | 以 dry-run 方式验证数字员工装配 | 不触发真实外部副作用，只输出计划与权限判断 |
| `work-order create` | 创建工作单 | 接收自然语言任务或结构化输入，返回工作单 ID |
| `work-order get` | 查看工作单详情 | 输出状态、当前步骤、负责人、预算、最近事件 |
| `work-order list` | 检索工作单列表 | 支持按状态、员工、时间、租户、风险等级过滤 |
| `work-order run` | 执行工作单 | 支持前台执行和 `--background` 后台执行 |
| `work-order watch` | 观察工作单进度 | 用于流式查看状态迁移、审批等待和工具执行摘要 |
| `work-order cancel` | 取消执行中的工作单 | 仅终止未完成步骤，不删除审计记录 |
| `work-order reclaim` | 回收陈旧后台任务 | 仅允许回收 stale background session 对应工作单 |
| `work-order resume` | 恢复暂停的工作单 | 用于审批通过后恢复，或人工补充信息后继续运行 |
| `work-order artifacts` | 查看交付物 | 列出文档、附件、导出文件和结构化结果 |
| `approval list` | 查看待审批项 | 供管理员或业务负责人处理高风险动作 |
| `approval get` | 查看审批详情 | 输出请求动作、风险说明、上下文摘要和建议决策 |
| `approval decide` | 批准或驳回审批项 | 支持 `--resume` 与 `--resume --background` 一步恢复 |
| `session list` | 查看会话列表 | 支持按工作单、员工、状态过滤 |
| `session get` | 查看会话摘要 | 输出参与者、开始时间、预算使用和当前阶段 |
| `session tail` | 实时查看会话事件 | 主要用于调试执行回合和工具观察结果 |
| `session export` | 导出会话记录 | 用于审计、复盘和问题定位 |
| `tool list` | 列出工具注册表 | 展示工具名称、风险级别、权限模式和适用员工 |
| `tool show` | 查看工具详情 | 输出输入 schema、资源类型、副作用说明和超时策略 |
| `tool dry-run` | 验证工具调用计划 | 只做参数解析和策略评估，不执行真实动作 |
| `replay run` | 回放工作单执行 | 用于复现失败、回归验证和训练审查 |
| `doctor` | 诊断系统一致性 | 检查配置、队列、锁、事件缺口、陈旧运行和集成健康 |
| `version` | 输出版本信息 | 返回 CLI 版本、API schema 版本、构建时间和 commit |

## 4. flags / args / env 优先级

### 4.1 总优先级

固定优先级：

`flag > env > active profile config > tenant config > default`

补充规则：

- 位置参数只用于唯一资源定位，例如 `<work-order-id>`、`<approval-id>`、`<session-id>`。
- 位置参数不允许由环境变量回退替代，避免脚本行为不明确。
- 与输出相关的选项也遵循同样优先级，例如 `--json` 优先于 `DE_OUTPUT=json`。
- 当前 CLI 基于 `argparse`，全局参数必须写在资源命令前：
  - ✅ `dectl --json config show`
  - ❌ `dectl config show --json`

### 4.2 建议全局 flags

| flag | 用途 |
|---|---|
| `--profile` | 指定配置 profile |
| `--tenant` | 指定租户 |
| `--json` | 单对象 JSON 输出 |
| `--jsonl` | 仅对流式命令启用，逐行 JSON 输出 |
| `--timeout` | 覆盖请求超时 |
| `--base-url` | 覆盖 API 地址 |
| `--no-input` | 禁止任何交互 |
| `--yes` | 跳过确认 |
| `--trace-id` | 注入链路追踪 ID |
| `--request-id` | 自定义请求 ID/幂等键 |

### 4.3 建议环境变量

| 环境变量 | 含义 |
|---|---|
| `DE_BASE_URL` | 平台 API 地址 |
| `DE_TENANT` | 默认租户 |
| `DE_PROFILE` | 默认 profile |
| `DE_TIMEOUT` | 默认请求超时 |
| `DE_OUTPUT` | 默认输出格式，`human` 或 `json` |
| `DE_NO_INPUT` | 默认禁用交互 |
| `DE_STATE_DIR` | 覆盖状态目录路径 |
| `OPENAI_API_KEY` | OpenAI provider 密钥 |
| `OPENAI_BASE_URL` | OpenAI provider 覆盖地址 |

### 4.4 关键命令参数建议

`work-order create`

- args：无必填位置参数
- flags：
  - `--employee <employee-id>`
  - `--input <text>`
  - `--input-file <path>`
  - `--budget <amount>`
  - `--coordinated`
  - `--participant <employee-id>`（可重复）

`work-order run` / `work-order resume`

- args：
  - `<work-order-id>`
- flags：
  - `--background`

`approval decide`

- args：
  - `<approval-id>`
- flags：
  - `--decision <approve|reject>`
  - `--reason <text>`
  - `--resume`
  - `--background`

`session tail`

- args：
  - `<session-id>`
- flags：
  - `--follow`
  - `--since <rfc3339>`
  - `--level <info|warn|error|debug>`
  - `--jsonl`

## 5. 交互式模式与非交互式模式差异

### 5.1 基本原则

- 所有命令都必须可脚本调用。
- 缺少必填输入时，仅在 TTY 环境下允许交互提示。
- 传入 `--no-input` 时，即使在 TTY 也禁止交互。

### 5.2 交互式模式

仅允许以下最小交互：

- `work-order create` 在缺少 `--input` 时提示补全（`--employee` 由参数解析层强制必填）
- `employee test` 在缺少 `--input` 时提示补全
- `approval decide` 在缺少 `--decision` 时，提示选择批准或驳回
- `work-order cancel` 在未传 `--yes` 时，要求确认
- `work-order reclaim` 在未传 `--yes` 时，要求确认

禁止事项：

- 不允许在交互过程中隐式修改租户、凭证或风险策略
- 不允许通过多轮交互补齐复杂结构化参数
- 不允许在执行中途弹出与业务无关的确认框

### 5.3 非交互式模式

- 缺少必填参数直接退出 `2`
- 默认关闭颜色、进度动画和提示性文案
- 任何需人工决定的动作都返回明确错误，不得卡住等待输入
- 长时运行命令只输出稳定事件流，不输出 spinner

## 6. stdout / stderr / --json 输出约定

### 6.1 通用规则

- 成功结果只写入 `stdout`
- 诊断、警告、重试提示、网络退避信息写入 `stderr`
- `--json` 时，`stdout` 只能输出单个 JSON 对象
- `--jsonl` 时，`stdout` 每行只能输出一个完整 JSON 对象

### 6.2 Human 输出规则

查询类命令：

- 第一行给结论
- 后续最多输出必要字段
- 字段顺序固定

变更类命令：

- 第一行输出动作结果
- 第二行输出关键 ID 和当前状态
- 若有后续动作，给出明确下一步提示

示例：

```text
Created work order wo_20260401_001
Status: waiting_approval
Next: dectl approval list --tenant acme
```

### 6.3 JSON 包裹格式

```json
{
  "schema_version": 1,
  "command": "work-order get",
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "request_id": "req_123",
    "trace_id": "tr_123"
  }
}
```

错误格式：

```json
{
  "schema_version": 1,
  "command": "approval decide",
  "ok": false,
  "data": null,
  "error": {
    "code": 6,
    "type": "approval_required",
    "message": "approval ap_123 requires a decision before the work order can continue",
    "hint": "run `dectl approval decide ap_123 --decision approve --reason ...`"
  },
  "meta": {
    "request_id": "req_123",
    "trace_id": "tr_123"
  }
}
```

### 6.4 流式输出约定

仅以下命令允许流式输出：

- `work-order watch`
- `session tail`

规则：

- human 模式按时间顺序输出稳定事件行
- `--jsonl` 时每行至少包含：
  - `ts`
  - `event_type`
  - `resource_id`
  - `status`
  - `payload`

## 7. Exit Code 设计

| Code | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 未分类错误 |
| `2` | 参数错误或输入校验失败 |
| `3` | 配置错误 |
| `4` | 权限/策略拒绝（例如工具被拒绝、Hook 阻塞） |
| `6` | 审批未完成或依赖资源不可用（例如 provider/tool 未注册） |
| `7` | 资源不存在或状态不允许该操作 |
| `8` | Provider/Tool/Budget/执行链路失败 |
| `10` | 内部错误 |

约束：

- 同一错误类型必须稳定映射到同一 exit code
- `--json` 与 human 模式的 exit code 必须一致
- 仅凭 stderr 文案不同，不能改变 exit code

## 8. 常见使用示例

创建工作单：

```bash
dectl --tenant acme --json work-order create \
  --employee sales-assistant \
  --input "给昨天未回复报价的客户生成跟进计划" \
  --budget 12000
```

后台执行工作单：

```bash
dectl --tenant acme --json work-order run wo_123 --background
```

查看待审批项：

```bash
dectl --tenant acme --json approval list
```

批准并在后台恢复：

```bash
dectl --tenant acme --json approval decide ap_123 \
  --decision approve \
  --reason "客户经理已确认内容可发送" \
  --resume \
  --background
```

观察工作单执行过程：

```bash
dectl --jsonl work-order watch wo_123 --follow
```

验证某个数字员工装配：

```bash
dectl --tenant acme --json employee test hr-assistant \
  --input-file ./examples/onboarding-task.md \
  --input "请生成入职周计划"
```

导出会话审计记录：

```bash
dectl --json session export sess_123
```

回放工作单事件时间线：

```bash
dectl --json replay run wo_123
```

诊断环境：

```bash
dectl --tenant acme --json doctor
```

## 9. 错误提示文案规范

### 9.1 基本要求

- 先说发生了什么，再说原因，最后给下一步建议
- 文案要短，可定位，可执行
- 不输出模型内部推理
- 不输出完整密钥、令牌、URL 签名或敏感负载

### 9.2 推荐结构

格式：

`[问题] + [对象] + [原因] + [下一步]`

示例：

- `approval ap_123 cannot be approved: reason is required; pass --reason`
- `work order wo_123 cannot resume: status is completed; use work-order get to inspect final artifacts`
- `provider openai is unavailable: request timed out after 30s; retry with --timeout 60s or switch profile`
- `tool send-email is denied for employee sales-assistant: policy high-risk-actions requires approval`

### 9.3 禁止写法

- `执行失败`
- `发生错误`
- `请检查配置`
- `系统繁忙，请稍后重试`

这些文案的问题是：

- 没有对象
- 没有原因
- 没有下一步动作

### 9.4 特殊场景要求

权限错误：

- 必须指出是 `allow/ask/deny` 中哪一种结果导致失败

状态冲突：

- 必须输出当前状态和值得执行的下一条查询命令

外部集成失败：

- 必须区分平台内部错误和第三方依赖错误

流式命令中断：

- 必须写明是用户中断、网络中断还是服务端关闭
