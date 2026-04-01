# P6 实现日志 · 2026-04-01

## 已完成任务

- 建立 Python 项目骨架与 `pyproject.toml`
- 实现零外部依赖的 CLI 骨架：`config`、`employee`、`work-order`、`version`
- 实现 YAML 配置加载与校验
- 实现基础领域模型：`WorkOrder`、`EmployeeProfile`、`TaskStep`、`Approval`
- 实现文件版工作单仓储，支持 `create/get/list`
- 实现 `mock provider` 与最小 `TurnEngine`
- 补充 `unittest` 测试与 Golden 样例

## 关键取舍

- 当前机器缺少 `pydantic`、`fastapi`、`pytest`，因此首批实现采用 `dataclasses + argparse + unittest`
- `api/rest/app.py` 以懒加载方式保留 FastAPI 入口，不在依赖缺失时阻塞 CLI 主链路
- `infra/repositories/work_orders.py` 目前采用文件存储以打通 M1，后续可按计划替换为数据库实现

## 后续建议

- 下一轮优先补 `TaskSupervisor`、`ToolRegistry`、`PolicyEngine`
- 完成数据库仓储替换和审批闭环前，不建议把当前实现视为生产级主链路

## 2026-04-01 第二轮补充

- 引入领域错误层：`DigitalEmployeeError`、配置/查询/Provider/Tool/Budget/Hook 细分错误
- 把 provider 选择从 use case 中抽离到 `ProviderRouter`
- 把最小 `ToolRegistry` 升级为可构建的注册表，补 `build_tool` 工厂和内置工具定义
- 把 `TurnEngine` 升级为多回合 runtime，加入 budget tracking、hook 分发和运行事件收集
- `employee test` 现在走统一 runtime 主链，不再在应用层直接实例化 provider

## 2026-04-01 第三轮补充

- 实现 `tool list`、`tool show`、`tool dry-run` CLI 主链
- 新增最小工具 schema 校验，非法 payload 现在会返回结构化错误
- `tool dry-run` 会基于员工 allow-list 和工具权限模式给出 `allowed` / `approval_required` 判定

## 2026-04-01 第四轮补充

- 参考 Claude Code 的 harness 机制，引入 `ContextCompactor`、`ToolExposurePlanner`、`TaskSupervisor`
- `TurnEngine` 现在会在每回合生成压缩上下文和渐进式工具暴露结果，再交给 provider
- 运行时配置新增上下文窗口、压缩目标和后台任务超时参数

## 2026-04-01 第五轮补充

- 引入文件版 `SessionRepository`，把 session + events 持久化到状态目录
- 实现 `work-order run`，通过 `TaskSupervisor` 监督 `TurnEngine` 执行，并把结果写回工作单与会话
- 实现 `session list/get/tail/export`，打通最小可观察闭环

## 2026-04-01 第六轮补充

- 新增 `work-order run --background`，通过独立 Python 子进程执行隐藏 `_execute` 命令
- `TurnEngine` 支持复用外部 session，并通过 progress callback 持续落盘事件
- `session tail --follow --jsonl` 现在会按事件流协议输出 `ts/event_type/resource_id/status/payload`
- 补齐 `work-order watch` 与 `work-order artifacts`，把事件观察和交付物查询上移到工作单入口
- 抽出共享事件流 helper，保证 `session tail` 与 `work-order watch` 的 `--jsonl` 协议一致
- `work-order run --background` 现在会记录 `last_session_id`，并引导用户优先使用 `work-order watch`
- 引入最小 `PolicyEngine` 和文件版 `ApprovalRepository`，把工具风险判断从 `tool dry-run` 扩展到 runtime
- `TurnEngine` 现在会在命中高风险工具时创建审批请求、暂停 session，并在审批通过后继续执行
- 实现 `approval list/get/decide` 与 `work-order resume`，打通 `run -> waiting_approval -> decide -> resume -> artifacts` 主链
- 实现 `work-order cancel`，支持取消后台执行中的工作单，并在等待审批时自动把待处理审批标记为 `expired`
- 后台 runner 现在会记录 `runner_pid`，控制面可按进程组发送终止信号；同时修复了 `_execute` 路径遗漏 `runtime_cell` 的问题
- `session tail` / `work-order watch` 对 `cancelled` / `expired` 事件会输出稳定状态，background streaming 测试也补了完成态断言
- 实现 `work-order resume --background`，复用原 session 重新排队执行，不再创建第二条恢复会话
- background resume 会写入 `session.resumed` 事件并更新新的 `task_id` / `runner_pid`，因此 `watch/tail/cancel` 可以继续沿用同一条观察链
- `approval decide` 现在支持 `--resume` 和 `--resume --background`，审批通过后可以直接衔接恢复，不必再手动执行第二个命令
- 自动恢复保留旧协议兼容：不传新 flag 时 `approval decide` 行为不变；传入时返回 `approval + resume` 组合结果
- 后台执行链新增 session heartbeat：`work-order _execute` 会周期性追加 `session.heartbeat`，并在 queued/running/completed/waiting_approval/failed/cancelled 各阶段刷新背景元数据
- `session get` 现在会返回结构化 `background` 视图，包含 `task_id`、`runner_pid`、`lease_timeout_seconds`、最近心跳时间和派生的 `heartbeat_status`
- 事件合并从简单拼接改成去重合并，避免后台心跳与 progress callback 并发写回时丢失或重复事件
- 抽出共享背景状态解释逻辑，`session get`、`work-order get/watch` 和 `doctor` 现在统一使用同一套 lease/stale 判定
- `doctor` 命令已落地，会汇总 background session 数量并显式报告 stale session，便于发现 orphaned runner
- 新增集成测试通过改写状态文件模拟 stale heartbeat，覆盖 `doctor`、`work-order get` 和 `session get` 的诊断输出
- 新增 `work-order reclaim`，仅允许回收 stale background work order；会尝试终止旧 runner、补 `work-order.reclaimed` 事件，并把 session/work-order 一起收敛到 failed 终态
- `work-order reclaim` 复用确认门控，非 TTY 下必须显式传 `--yes`
- 修复 background `_execute` 的 metadata 同步常量引用错误，恢复 `session tail --follow` 与后台 runner 主链稳定性
- stale 测试辅助已抽到 `tests/integration/cli/support.py`，并在 reclaim 用例里等待 work-order 完整收尾后再注入 stale 状态，消除全量跑时序抖动

## 2026-04-01 第七轮补充（QA 阻塞项回归修复）

- 修复 `infra/config/loader.py` 中 YAML null section 导致 `AttributeError` 的问题（`system_payload.get("runtime", {})` 改为 `system_payload.get("runtime") or {}`）
- 新增 CLI 集成测试 `test_tenant_b_cannot_see_tenant_a_work_orders`，覆盖 QA-004 租户隔离在 CLI 层面的验证
- 新增单元测试 `test_null_yaml_sections_do_not_crash`，覆盖 YAML null section 边界情况
- 确认前次 4 个 P0 阻塞项（QA-001 ~ QA-004）全部修复
- 生成回归评审报告 `review-report-20260401-v2.md`
- 生成回归 QA 报告 `qa-report-20260401-v2.md`，结论：Go
- 生成回归发布指南 `release-guide-20260401-v2.md`

## 验证记录

- `python3 -m unittest discover -s tests -p 'test_*.py'`
  - `Ran 87 tests`
  - `OK`
