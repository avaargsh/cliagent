# Python 数字员工平台设计文档

> 日期：2026-04-01
> 状态：v2.0 基线（从 Go CLI 模板迁移至 Python 数字员工平台）
> 说明：本文件是实现基线。原 `cliagent Go CLI` 设计已归档，当前项目为 Python 数字员工控制面平台。

## 1. 结论与定位

- `digital-employee` 平台的定位是"可审计的企业数字员工执行平台"。
- 核心价值：把自然语言任务通过工作单驱动、审批可控、工具可审计的方式交给数字员工执行，并保留完整事件事实源。
- 后续取舍统一按一句话判断：这个能力是否显著提升"执行可审计性、可控性、可恢复性"。若不能，默认延后。

对外主张只保留三点：

1. `WorkOrder-first`：以工作单为一等业务对象，全生命周期可追踪
2. `Auditable`：所有执行、审批、工具调用均有事件账本
3. `CI-ready`：全链路支持非交互和稳定机读输出

明确不做：

1. 通用聊天助手替代品
2. IDE 全量体验竞争
3. 无人值守软件工厂
4. 通用多 Agent swarm 平台

## 2. 单一事实源

实现与运行时必须严格区分"人类协议"和"机器配置"：

| 载体 | 角色 | 规则 |
|---|---|---|
| `AGENTS.md` | 人类与 AI 协作协议 | 供人阅读和执行，不作为机器配置源 |
| `docs/cliagent-go-design.md` | 技术实现基线 | 分层、协议、状态模型的唯一标准 |
| `docs/runtime-constraints.md` | 运行时约束说明 | `domain/runtime_constraints.py` 的人类可读版 |
| `.cliagent/workflow.yaml` | 机器工作流配置 | 定义阶段、角色、输出语言、交付物路径 |
| `.cliagent/config.yaml` | 机器运行配置 | 定义 Provider、模型、超时、CLI 默认行为 |
| `configs/` | 结构化业务配置 | 系统、Provider、员工、策略的 YAML 配置 |
| `.ai/context/*.md` | 项目上下文 | 供角色输入使用，不承载机器判定逻辑 |
| `.ai/temp/` `.ai/reports/` `.ai/records/` | 运行产物 | 阶段交付物与报告 |

兼容性要求：

- 禁止直接解析自然语言 `AGENTS.md` 判断阶段、角色或路径。
- 机器配置必须来自结构化 YAML 文件和环境变量。

## 3. 设计原则

### 3.1 本地优先

- 工作流状态和证据保存在本地状态目录，不依赖外部数据库即可完成 MVP。
- 没有网络时，`mock` provider 仍可驱动主链路测试。

### 3.2 协议稳定优先

- 优先冻结命令面、错误码和 `--json` schema，再优化交互样式。
- 用户可依赖的输出不能随版本随意变更；变更必须通过 `schema_version` 演进。

### 3.3 状态一致性优先

- 所有关键写入采用"临时文件 + 原子替换"。
- 文件仓储使用 `fcntl` advisory lock 串行化并发写入。
- 所有关键动作采用"当前状态快照 + 追加事件账本"双记录模型。

### 3.4 轻依赖与清晰分层

- 优先标准库和轻依赖（唯一运行时依赖：`pyyaml>=6`）。
- `api/` 只做命令组装；业务逻辑进入 `application/`，执行逻辑进入 `runtime/`。
- 业务状态在 `work-order / approval / artifact / session projection` 中。
- 运行时状态在 `RuntimeCell / RuntimeManager` 中。

### 3.5 可测试与可脚本化

- 所有主命令必须可在非 TTY 环境运行。
- `unittest` 覆盖核心逻辑；集成测试覆盖 CLI 协议；Golden Test 覆盖稳定输出。
- Mock Provider 覆盖离线和 CI 场景。

### 3.6 安全默认值

- API Key 只从环境变量读取。
- 日志和状态文件默认脱敏，不记录完整密钥和认证头。
- 租户隔离：状态目录按租户分目录存储。

## 4. MVP 范围

### 4.1 v0.1.0 已实现

1. `config show|validate`
2. `employee list|show|test`
3. `work-order create|get|list|run|cancel|resume|watch|artifacts|reclaim`
4. `approval list|get|decide`（含 `--resume`）
5. `session list|get|tail|export`
6. `tool list|show|dry-run`
7. `replay run`
8. `doctor`
9. `version`
10. Provider：`mock`、`openai`
11. 文件仓储 + `fcntl` 并发锁
12. `RuntimeCell / RuntimeManager`
13. `TurnEngine` 多回合执行 + `TurnPipeline`
14. `EventLedger + WorkOrderSnapshot + SessionProjection`
15. `PolicyEngine`（allow / ask / deny）
16. `ContextCompactor + ToolExposurePlanner`
17. 后台执行 + 心跳 + stale 检测 + reclaim
18. `CoordinatorRuntime`（可选协调路径）
19. 租户隔离

### 4.2 延后到后续版本

1. REST API 端到端
2. WebSocket 实时事件推送
3. 数据库持久化（PostgreSQL / Redis）
4. Windows 平台支持
5. `--profile` 分层配置加载
6. 正式 SDK 包（`digital_employee_sdk`）

## 5. 命令模型与协议

### 5.1 命令树

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
│   ├── resume <work-order-id>
│   ├── artifacts <work-order-id>
│   └── reclaim <work-order-id>
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

### 5.2 交互规则

1. 非 TTY：严禁交互提问，缺参直接退出 `2`
2. TTY：只允许最小必要确认
3. `--no-input`：强制禁用任何交互

### 5.3 输出规则

- 成功结果写入 `stdout`
- 诊断、警告、调试写入 `stderr`
- `--json` 时，`stdout` 只能输出单个 JSON 对象
- `--jsonl` 仅对流式命令（`session tail`、`work-order watch`）有效
- 全局参数（如 `--json`、`--jsonl`、`--tenant`）需写在资源命令前

统一机读包裹：

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

### 5.4 Exit Code

| Code | 含义 |
|---|---|
| `0` | 成功 |
| `1` | 未分类错误 |
| `2` | 参数或输入校验失败 |
| `3` | 配置错误 |
| `4` | 认证或授权失败 / Hook 阻塞 |
| `6` | 策略拒绝 / 审批未完成 / 资源不存在 |
| `7` | 资源不存在 |
| `8` | Provider / Tool / Budget 执行失败 |
| `10` | 内部错误 |

## 6. 目录与分层设计

### 6.1 目录树

```text
src/digital_employee/
├── api/                          # 接入层
│   ├── cli/                      # argparse 命令组装
│   └── rest/                     # FastAPI 占位
├── application/                  # 应用层
│   ├── commands/                 # 写操作
│   ├── queries/                  # 读操作
│   ├── dto/                      # 数据传输对象
│   ├── services/                 # facade、编排支撑
│   └── use_cases/                # 兼容 shim（迁移期保留）
├── domain/                       # 领域模型与约束
├── contracts/                    # 抽象协议
├── bootstrap/                    # Composition root
├── runtime/                      # 执行运行时
│   ├── cell.py                   # RuntimeCell
│   ├── manager.py                # RuntimeManager
│   ├── coordinator_runtime.py    # 协调器
│   ├── coordinator_selector.py   # 员工选择
│   ├── task_supervisor.py        # 任务监督
│   ├── turn_engine.py            # 兼容 wrapper
│   ├── hooks.py                  # Hook 调度
│   ├── budget.py                 # 预算跟踪
│   └── turn/                     # 回合流水线
├── agents/                       # 员工画像装配
├── skills/                       # 技能包加载
├── memory/                       # 上下文压缩
├── tools/                        # 工具注册/执行/暴露
├── providers/                    # Provider 目录/工厂/路由
├── policy/                       # 策略引擎/审批/脱敏
├── infra/                        # 基础设施
│   ├── config/                   # 配置加载/校验
│   └── repositories/             # 文件版仓储
└── observability/                # 事件账本/投影
```

### 6.2 分层职责

| 层 | 职责 | 禁止事项 |
|---|---|---|
| `api.cli` | 参数解析、TTY 判断、exit code 映射 | 不直接写业务文件，不直接拼 Provider 请求 |
| `application.commands` | 写操作编排：create/run/cancel/resume/approve | 不直接依赖 infra 具体实现 |
| `application.queries` | 读操作：get/list/tail/export/doctor view | 不写库或调用外部动作 |
| `runtime.cell` | 运行时胶囊：provider/tool/policy/memory/hook/turn 组装 | 不直接依赖业务 repo |
| `runtime.turn` | 单回合流水线 | 不依赖 CLI/HTTP |
| `providers` | 模型调用 | 不做工作流判定 |
| `tools` | 工具定义与执行 | 不做业务编排 |
| `policy` | allow / ask / deny | 不做网络调用 |
| `observability` | 事件账本与投影 | 不做业务决策 |
| `infra` | 配置、仓储、锁 | 不侵入业务编排 |
| `bootstrap` | Composition root、工厂 | 不包含业务规则 |

## 7. 核心模型与接口

### 7.1 Provider

```python
class Provider(Protocol):
    name: str
    async def complete(self, request: CompletionRequest) -> CompletionResult: ...
```

### 7.2 RuntimeCell

```python
@dataclass(frozen=True, slots=True)
class RuntimeCellKey:
    tenant: str | None
    employee_id: str
    config_version: str

@dataclass(slots=True)
class RuntimeCell:
    key: RuntimeCellKey
    provider_router: ProviderRouter
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    policy_engine: PolicyEngine
    context_compactor: ContextCompactor
    tool_exposure_planner: ToolExposurePlanner
    turn_engine: TurnEngine
    # ...
```

### 7.3 核心状态模型

| 类型 | 说明 |
|---|---|
| `WorkOrder` | 工作单：状态、负责人、审批点、配置快照 |
| `SessionRecord` | 会话：状态、事件列表、预算使用 |
| `LedgerEvent` | append-only 事件：类型、时间戳、负载 |
| `SessionProjection` | 会话查询视图 |
| `Approval` | 审批请求与决策 |
| `CoordinatorPlan` | 协调计划快照 |

## 8. 状态、一致性与并发控制

### 8.1 状态目录

```text
.de-state/
├── {tenant}/
│   ├── work_orders.json
│   ├── work_orders.lock
│   ├── sessions/
│   │   ├── {session_id}.json
│   │   └── {session_id}.lock
│   ├── approvals.json
│   ├── events.jsonl
│   ├── events.lock
│   └── projections/
└── _default/
    └── (same structure)
```

### 8.2 一致性规则

1. 所有写操作使用 `_FileLock(fcntl.LOCK_EX)` 串行化
2. 写入使用"临时文件 + `replace()`"原子替换
3. 事件账本 append-only
4. 每个工作单记录 `config_snapshot_id`，运行时依赖快照而非可变配置

### 8.3 租户隔离

- 状态目录按 `tenant` 分子目录
- 默认租户使用 `_default/`
- 仓储实例在构造时绑定租户，查询不会跨租户

## 9. 配置系统

### 9.1 配置优先级

1. flags
2. env
3. `configs/*.yaml`
4. default

### 9.2 配置目录

```text
configs/
├── system.yaml           # 运行时参数、API、CLI、可观测性
├── providers/            # Provider 定义
│   ├── mock.yaml
│   └── openai.yaml
├── agents/               # 员工画像
│   ├── sales-assistant.yaml
│   └── outreach-specialist.yaml
└── policies/             # 策略规则
    └── high-risk-actions.yaml
```

### 9.3 关键环境变量

| 变量 | 说明 |
|---|---|
| `DE_BASE_URL` | API 基础地址 |
| `DE_TENANT` | 租户标识 |
| `DE_PROFILE` | 配置画像 |
| `DE_TIMEOUT` | 请求超时秒数 |
| `DE_OUTPUT` | 默认输出格式 |
| `DE_NO_INPUT` | 禁止交互 |
| `DE_STATE_DIR` | 自定义状态目录 |
| `OPENAI_API_KEY` | OpenAI 密钥 |

## 10. 安全、测试与发布

### 10.1 安全

1. API Key 仅从环境变量读取
2. 日志、状态文件默认脱敏
3. `doctor` 检查 stale session 和 orphan runner

### 10.2 测试

1. 单元测试：领域模型、配置加载、runtime 子组件、policy engine
2. 集成测试：CLI 端到端、错误协议、租户隔离、后台执行
3. Golden Test：`config-show-json.json`
4. Mock Provider：保证离线和 CI 可重复
5. 当前回归基线：`python3 -m unittest discover -s tests -p 'test_*.py'`，`Ran 98 tests`

### 10.3 发布

1. `python3 -m build` 生成 `sdist` + `wheel`
2. 产物附带 `sha256sum` checksum
3. 首批支持 `darwin/linux` 的 `amd64/arm64`
4. Python >= 3.12

## 11. 实施顺序

按 WBS 定义的 7 个迁移阶段推进：

1. A1：收紧 composition root — **已完成**
2. A2：拆分 commands / queries — **已完成**
3. A3：引入 RuntimeCell / RuntimeManager — **已完成**
4. A4：拆 TurnEngine 为回合流水线 — **已完成**
5. A5：落 EventLedger + Projection — **已完成**
6. A6：收紧 Provider / Tool / Policy — **已完成**
7. A7：补 CoordinatorRuntime — **已完成**

当前处于 M1 骨架完成、QA Go 状态。
