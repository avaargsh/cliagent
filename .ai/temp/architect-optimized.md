# Python 数字员工平台架构优化设计

## 1. 目标

- 本文档不是从零推翻现有设计，而是在保留 `work-order` 中心思想的前提下，解决当前代码已经暴露出的结构问题。
- 输入基线：
  - 当前项目：`/home/dev/pyagent`
  - 参考仓库 1：`/home/dev/CoPaw`
  - 参考仓库 2：`/home/dev/claude-code-source-code`
- 优化目标：
  - 保留“工作单中心、可审计、可审批、可回放”的产品方向
  - 降低运行时耦合，避免 `use case` 和 `turn engine` 继续膨胀
  - 为多租户、多员工、后台执行、会话观察和未来多 agent 协作留出稳定边界
  - 让当前代码结构能逐步迁移到正式持久化和正式执行平面，而不是再次推倒重来

## 2. 当前项目诊断

- 当前项目的方向是对的：一等对象已经从“聊天会话”切到了 `work-order`，这是企业数字员工平台比通用聊天 agent 更合理的重心。
- 但当前实现已经出现四个结构性收缩点：
  - `application/services/deps.py` 把 repo、router、engine、supervisor、tool registry、session repo 等全部塞进一个大容器，应用层没有“窄依赖”边界。
  - `runtime/turn_engine.py` 同时承担上下文压缩、工具曝光、Provider 调用、预算跟踪、hook 调度、tool 执行、session 更新，已经接近 God Object。
  - `application/use_cases/work_order_use_cases.py` 混合了 CRUD、同步运行、后台进程拉起、artifact 写入、session 落盘和失败恢复，编排层与执行层边界不清。
  - `application/services/request_context.py` 既做配置加载，又做校验，又做运行时装配，还直接决定 repo/provider/tool/runtime 组合方式，后续会成为所有改动的耦合点。
- 当前项目还有两个隐含风险：
  - `TaskSupervisor` 现在更像“进程内异步任务包装器”，不是“持久化业务状态机”；如果继续让它背负业务语义，后续做 worker/lease/retry 会很痛。
  - `ToolRegistry` 里还混着内置 tool builder 和 handler，`ProviderRouter` 也还是 bootstrap 形态，说明“目录分层已经有了，但运行时角色还没拆开”。

结论：

- 当前项目最需要的不是再加功能，而是把“控制面、编排面、执行面、资源面”四个层次拉开。
- 这次优化应当是“结构收敛”，不是“再堆子模块名词”。

## 3. 两个参考仓库可迁移的模式

- 从 `claude-code-source-code` 借三类模式：
  - 窄依赖注入：`src/query/deps.ts` 把运行时依赖收敛成小而稳定的依赖面，测试和重构成本明显更低。
  - 回合预算与工具可见性：`src/query/tokenBudget.ts` 和 `src/tools.ts` 体现了“预算跟踪”和“先过滤再暴露”的运行时纪律。
  - 远程会话与协调器边界：`src/remote/RemoteSessionManager.ts`、`src/coordinator/coordinatorMode.ts` 把“远程控制”和“协调器/执行者”清晰拆开。
- 从 `CoPaw` 借三类模式：
  - 运行时胶囊：`src/copaw/app/workspace/workspace.py` 把 runner、memory、MCP、cron、channel 作为一个可整体管理的运行时单元。
  - 懒加载与热重载：`src/copaw/app/multi_agent_manager.py` 的 lazy load + zero-downtime reload 非常适合“配置驱动的 agent runtime”。
  - 请求作用域上下文：`src/copaw/app/agent_context.py`、`src/copaw/app/routers/agent_scoped.py` 对多 agent 路由和 request scope 的处理值得借鉴。
- 不直接继承的部分：
  - 不把当前平台改成 `CoPaw` 那种“工作空间型个人助理平台”
  - 不把当前平台改回 `claude-code` 那种“单 session 驱动 + terminal/repl 中心”
  - 不引入全局单例式 `ProviderManager`
  - 不把 Workspace 变成一等业务对象

可迁移结论：

- `claude-code-source-code` 适合提供“执行回合和工具边界”的方法论。
- `CoPaw` 适合提供“运行时服务胶囊和热重载”的方法论。
- 当前项目应当保留 `work-order` 中心业务模型，同时吸收这两类工程模式。

## 4. 优化后的总体结论

- 业务中心保持不变：平台仍以 `work-order` 为一等对象。
- 运行时组织方式需要改变：不再直接把所有组件挂到一个全局 `Deps` 上，而是引入 `RuntimeCell`。
- 运行时硬约束必须收敛到单一事实源：`src/digital_employee/domain/runtime_constraints.py` 与 `docs/runtime-constraints.md`。
- 新架构应采用“五层模型”：
  - `Control Plane`
  - `Application Orchestration`
  - `Execution Runtime`
  - `Resource Services`
  - `Infrastructure`
- 核心原则：
  - 业务状态在 `work-order / approval / artifact / session projection` 中
  - 运行时状态在 `RuntimeCell / SessionRuntime / Lease / TaskHandle` 中
  - 工具副作用必须经过 `PolicyGate`
  - 所有可观察事实都写入 `EventLedger`
  - 多员工协作是可选增强层，不是主链路前提
  - `execution_mode / dispatch_mode / background_state / coordinator event type` 不允许散落在多个模块各自定义

## 5. 核心分层与职责重排

建议改成如下职责结构：

| 层 | 作用 | 当前问题 | 优化后定位 |
|---|---|---|---|
| `api` | CLI / REST / WebSocket / Webhook 接入 | 还比较薄，但对容器耦合偏重 | 保持薄层，只依赖 application facade |
| `application` | 命令、查询、事务边界、编排 | 当前 use case 过肥 | 拆成 `commands/queries/services`，命令与查询分离 |
| `runtime` | 回合执行、后台执行、运行时状态 | 当前 `TurnEngine` 过重 | 拆成 `runtime/cell.py` + `turn/` + `coordinator/` |
| `resource services` | provider/tool/policy/memory | 当前边界混在 runtime 内 | 变成独立协作者，由 runtime 调用 |
| `infra` | config/repo/queue/locks/storage | 当前 bootstrap repo 比重过高 | 继续承接实现细节，但不侵入业务编排 |

建议保留现有顶层目录，不做激进重命名，只做内部重排：

- `application`
  - 新增 `commands/`
  - 新增 `queries/`
  - `use_cases/` 逐步下沉或拆分
- `runtime`
  - 新增 `cell.py`
  - 新增 `manager.py`
  - 新增 `turn/`
  - `task_supervisor.py` 保留，但只承担任务监督
- `providers`
  - 增加 `catalog.py`
  - 增加 `factory.py`
  - `router.py` 只管选择，不做实例生命周期和配置解析
- `tools`
  - `registry.py` 只存定义
  - `executor.py` 执行 handler
  - `exposure.py` 保留暴露规划
- `policy`
  - 正式变成一等包，不能继续只停留在设计文档里

## 6. 新的运行时模型

建议引入 `RuntimeCell` 作为运行时胶囊，但不改变 `work-order` 的业务中心地位。

`RuntimeCell` 的作用：

- 表示一个“按租户 + 员工画像 + 配置快照”装配完成的执行环境
- 封装以下对象：
  - `ProviderCatalog`
  - `ProviderRouter`
  - `ToolRegistry`
  - `ToolExecutor`
  - `PolicyEngine`
  - `MemoryManager`
  - `HookDispatcher`
  - `TurnPipeline`
- 生命周期：
  - 懒加载
  - 可热重载
  - 可按配置版本失效
  - 不直接持有业务工作单状态

建议新增 `RuntimeManager`：

- key 维度：`(tenant, employee_id, config_version)`
- 能力：
  - `get_cell()`
  - `reload_cell()`
  - `close_cell()`
  - `invalidate_by_tenant()`
  - `invalidate_by_employee()`
- 借鉴 `CoPaw MultiAgentManager` 的地方：
  - lazy load
  - 最小锁持有时间
  - hot reload
- 不借鉴的地方：
  - 不把整个工作区、频道、cron、所有 sidecar 都塞进 RuntimeCell

`TurnEngine` 建议拆成回合流水线：

1. `ContextAssembler`
2. `BudgetController`
3. `ToolExposurePlanner`
4. `ModelGateway`
5. `ActionInterpreter`
6. `ToolExecutor`
7. `SessionRecorder`

这样 `TurnEngine` 本身只负责调度顺序，不再自己承载全部细节。

## 7. 配置、租户与运行时装配

当前配置系统只有“加载 YAML -> 校验 -> 挂进 Deps”，对长期演进不够。

建议把配置拆成四个域：

1. `system config`
   - 平台默认超时
   - 默认 budget
   - observability 开关
   - queue/lease 参数
2. `tenant config`
   - 默认 provider policy
   - integration endpoint
   - approval routing
   - redaction policy
3. `employee profile`
   - default provider
   - skill packs
   - allowed tools
   - knowledge scopes
   - approval policy
4. `runtime override`
   - CLI flag
   - env
   - request override

关键优化：

- 每次创建 `work-order` 时都记录 `config_snapshot_id` 或 `profile_version`
- `RuntimeCell` 依赖的是快照，而不是“当前正在变化的配置文件”
- `build_deps()` 应改造成真正的 composition root：
  - 只负责读取配置和组装 facade
  - 不把所有运行时对象直接暴露给每一个 use case

建议把当前 `build_deps()` 继续拆成：

- `build_control_plane_deps()`
- `build_runtime_manager()`
- `build_repositories()`
- `build_observability_services()`

再由 application facade 按需组合。

## 8. 会话、事件与审计模型

当前项目已经有 `ConversationSession` 和 `SessionRecord`，方向是对的，但还不够清晰。

建议区分三类持久化对象：

1. `WorkOrderSnapshot`
   - 当前状态
   - 当前步骤
   - 当前审批点
   - 最新 session id
   - 输出摘要
2. `SessionProjection`
   - 当前对话/执行阶段的查询视图
   - 面向 `session get/list/tail`
3. `EventLedger`
   - append-only
   - 用于回放、审计、诊断

不要再把“session + events”只作为一个临时打包对象来理解。更合理的关系是：

```text
work_order snapshot
  <- projected from event ledger

session projection
  <- projected from event ledger

artifact metadata
  <- linked from work order + session
```

事件建议固定类型族：

- `work_order.created`
- `work_order.queued`
- `work_order.started`
- `turn.started`
- `context.compacted`
- `tools.exposed`
- `completion.completed`
- `tool.requested`
- `tool.allowed`
- `tool.approval_requested`
- `tool.executed`
- `approval.decided`
- `session.closed`
- `work_order.completed`
- `work_order.failed`

这样后续的 `watch / tail / replay / doctor` 都有统一事实源。

## 9. Tool / Provider / Policy 三层边界

当前项目最容易继续耦合的就是这三层。

建议明确：

- `Provider` 只负责“模型输入输出”
- `Tool` 只负责“能力定义和执行包装”
- `Policy` 只负责“allow / ask / deny”

三者不能互相吞边界。

推荐职责：

### `ProviderCatalog`

- 从配置中加载 provider 定义
- 不直接发请求
- 提供 planner/executor/reviewer 的模型槽位选择信息

### `ProviderRouter`

- 根据回合类型与员工画像选 provider/model
- 不持有租户业务逻辑
- 不负责工具权限

### `ToolRegistry`

- 只维护定义：
  - name
  - schema
  - risk level
  - side effects
  - capability tags

### `ToolExecutor`

- 负责真正调 handler / gateway
- 统一输出 observation
- 负责幂等键、超时、重试包装

### `PolicyEngine`

- 输入：
  - tenant
  - employee profile
  - tool definition
  - payload
  - risk context
- 输出：
  - `allow`
  - `ask`
  - `deny`

借鉴 `claude-code-source-code` 的关键点：

- deny 规则应当在“暴露给模型之前”先过滤一次
- 执行前还要再做一次 policy check
- 暴露层和执行层都要受 policy 约束

## 10. 多员工与协调器策略

当前项目不应直接走向“全局多 agent swarm”，但应该为复杂任务预留协调器层。

建议模式：

- 默认模式：`single-employee runtime`
- 增强模式：`coordinator runtime`

`CoordinatorRuntime` 的职责：

- 把工作单拆成多个 `sub-task`
- 为每个 `sub-task` 选择员工画像
- 聚合结果
- 控制并发和预算

`CoordinatorRuntime` 不直接做：

- 不直接执行真实工具
- 不直接绕过审批
- 不直接持久化底层 session 细节

推荐触发条件：

- 只有当任务明显跨多个能力域时才启用协调器
- 协调器是高级策略，不是默认入口

这部分应当借 `claude-code-source-code` 的“coordinator/worker separation”，但不借它的 terminal 会话中心模型。

## 11. 建议目录调整

在不推翻现有顶层目录的前提下，建议如下：

```text
src/digital_employee/
├── api/
├── application/
│   ├── commands/
│   ├── queries/
│   ├── dto/
│   └── services/
├── domain/
├── runtime/
│   ├── manager.py
│   ├── cell.py
│   ├── coordinator_runtime.py
│   ├── task_supervisor.py
│   ├── session_runtime.py
│   └── turn/
│       ├── engine.py
│       ├── context_assembler.py
│       ├── budget_controller.py
│       ├── action_interpreter.py
│       ├── session_recorder.py
│       └── result_mapper.py
├── agents/
├── skills/
├── tools/
│   ├── registry.py
│   ├── executor.py
│   ├── exposure.py
│   └── handlers/
├── providers/
│   ├── catalog.py
│   ├── factory.py
│   ├── router.py
│   └── adapters/
├── policy/
│   ├── engine.py
│   ├── approvals.py
│   └── redaction.py
├── memory/
├── infra/
│   ├── config/
│   ├── repositories/
│   ├── queue/
│   ├── locks/
│   └── storage/
└── observability/
    ├── ledger.py
    ├── replay.py
    └── streaming.py
```

对应当前代码的具体调整建议：

- `application/use_cases/work_order_use_cases.py`
  - 拆成 `commands/work_order_commands.py` + `queries/work_order_queries.py`
- `runtime/turn_engine.py`
  - 拆到 `runtime/turn/`
- `application/services/request_context.py`
  - 逐步改造成 `bootstrap/container.py` 或 `application/services/composition.py`
- `tools/registry.py`
  - 把内置 handler 挪到 `tools/handlers/`
- `providers/router.py`
  - 从 bootstrap helper 进化成真正的 model/router 边界

## 12. 迁移顺序

建议按以下顺序做，不要并行乱拆：

1. 收紧 composition root
   - 先把 `Deps` 拆成窄依赖 facade
2. 拆 `work_order_use_cases.py`
   - 让命令/查询分离
3. 引入 `RuntimeCell` 和 `RuntimeManager`
   - 先保留现有行为，只改变装配方式
4. 拆 `TurnEngine`
   - 先拆 `ContextAssembler`
   - 再拆 `ToolExecutor`
   - 最后拆 `SessionRecorder`
5. 引入 `EventLedger`
   - 先双写 projection + ledger
6. 把 `PolicyEngine` 从设计稿变成真实实现
7. 最后再做 `CoordinatorRuntime`

迁移纪律：

- 每一轮只做一类边界收敛
- 每一轮都要补 integration tests
- 不要在“架构拆分过程中”同时接入太多真实 provider/integration

## 13. 不建议引入的模式

- 不建议把 `CoPaw Workspace` 直接照搬成业务一等对象
- 不建议引入全局单例 `ProviderManager`
- 不建议把所有后台执行都外包给 `TaskSupervisor`
- 不建议在现阶段引入 Temporal / Celery 大编排
- 不建议把自由文本 memory/skills 直接当机器配置
- 不建议让 `CoordinatorRuntime` 成为默认运行模式

## 14. 最终建议

如果只保留一句话结论：

- 当前项目应该从“一个大 `Deps` 驱动的一组功能模块”，收敛成“`work-order` 中心业务模型 + `RuntimeCell` 运行时胶囊 + `EventLedger` 审计事实源”的三段式架构。

最重要的三个改动是：

1. 引入 `RuntimeCell / RuntimeManager`
2. 把 `TurnEngine` 拆成回合流水线
3. 把 `session/event/work-order projection` 从临时对象升级为正式数据模型

这样做的结果是：

- 你能继续保留当前项目最有价值的 `work-order` 思路
- 能借到 `CoPaw` 的运行时管理能力
- 能借到 `claude-code-source-code` 的执行回合和工具治理能力
- 又不会把系统演化成另一种不适合企业数字员工的产品形态
