# P8 QA 测试用例（2026-04-01-v4）

## 1. 测试依据

- 当前仓库仍缺少正式 `.ai/temp/requirement.md`，本轮按“产品化回归验收 + 当前迭代目标”执行。
- 本轮测试依据：
  - `.ai/temp/cli-spec.md`
  - `.ai/temp/wbs.md`
  - `.ai/temp/architect.md`
  - `.ai/reports/review/review-report-20260401-v5.md`
- 本轮新增关注点：
  - `replay run` 已从占位切到可用实现
  - 后台恢复链路稳定性（避免偶发挂起与目录清理失败）
  - 文件仓储读写并发一致性（原子落盘 + 读写加锁）
  - 全量回归基线更新为 `98` 测试

## 2. 测试环境

- 时间：2026-04-01
- 工作目录：`/Users/musun/pyagent`
- Python：`3.13.9`
- 运行约定：
  - CLI 通过 `PYTHONPATH=src python3 -m digital_employee.api.cli.main` 执行
  - 全局参数写在资源命令前，例如 `dectl --json config show`
- 环境限制：
  - 未进行真实 OpenAI 网络联调
  - 未覆盖 REST 入口
  - 未覆盖 Windows 平台

## 3. 测试用例

| ID | 优先级 | 验证点 | 前置条件 | 执行方式 | 预期结果 |
|---|---|---|---|---|---|
| P0-01 | P0 | `replay run` 可回放工单事件时间线 | 已创建并执行至少 1 个工作单 | `PYTHONPATH=src python3 -m unittest tests.integration.cli.test_replay_commands -v` | 退出码 `0`；`replay.run` 返回 `event_count>0` 且包含 `turn.completed` |
| P0-02 | P0 | 后台审批恢复主链稳定可完成 | 具备默认配置与 `mock` provider | `PYTHONPATH=src python3 -m unittest tests.integration.cli.test_approval_commands.CLIApprovalCommandsTest.test_approval_decide_can_auto_resume_background -v` | 退出码 `0`；单次用例稳定通过 |
| P0-03 | P0 | 后台恢复链路无明显随机抖动 | 同 P0-02 | 循环执行 P0-02 共 20 次 | `failures=0` |
| P0-04 | P0 | 文件仓储并发一致性改动无回归 | 全量测试可执行 | `PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'` | 退出码 `0`；`Ran 98 tests`、`OK` |
| P1-01 | P1 | 全量回归在短周期内稳定 | 同 P0-04 | 全量测试连续执行 5 次 | 5/5 全通过 |
| P1-02 | P1 | CLI 全局 flag 使用说明与实现一致 | CLI 可执行 | 正向：`dectl --json config show`；反向：`dectl config show --json` | 正向成功、反向 `exit 2`，与文档约定一致 |

## 4. 本轮不覆盖

- 真实 OpenAI API 联调
- OpenAI 路径的审批后 `resume` 端到端验收
- REST 入口端到端
- 跨机器 / NFS 文件锁场景
- Windows 平台兼容性
