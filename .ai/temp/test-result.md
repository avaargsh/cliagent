# P8 QA 测试结果（2026-04-01-v4）

## 1. 执行概览

- 执行日期：2026-04-01
- 执行人：QA 工程师阶段
- 结论：当前交付物满足进入发布文档阶段条件

## 2. 用例结果

| ID | 结果 | 退出码 | 实际结果摘要 |
|---|---|---|---|
| P0-01 | 通过 | `0` | `tests.integration.cli.test_replay_commands` 通过（`Ran 2 tests`），`replay run` 返回结构化时间线 |
| P0-02 | 通过 | `0` | `test_approval_decide_can_auto_resume_background` 单次执行通过 |
| P0-03 | 通过 | `0` | 上述用例循环 20 次：`failures=0/20` |
| P0-04 | 通过 | `0` | 全量回归通过：`Ran 98 tests`、`OK` |
| P1-01 | 通过 | `0` | 全量回归循环 5 次：`total_failures=0/5` |
| P1-02 | 通过 | `0/2` | `dectl --json config show` 成功；`dectl config show --json` 返回 `exit 2`，与文档一致 |

## 3. 关键执行记录

### 3.1 通过项

`PYTHONPATH=src python3 -m unittest tests.integration.cli.test_replay_commands -v`

- 结果：成功
- 输出摘要：
  - `Ran 2 tests`
  - `OK`

`PYTHONPATH=src python3 -m unittest tests.integration.cli.test_approval_commands.CLIApprovalCommandsTest.test_approval_decide_can_auto_resume_background -v`

- 结果：成功
- 输出摘要：
  - `Ran 1 test`
  - `OK`

`python3` 循环 20 次执行 `test_approval_decide_can_auto_resume_background`

- 结果：成功
- 输出摘要：
  - `failures=0/20`

`PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'`

- 结果：成功
- 输出摘要：
  - `Ran 98 tests`
  - `OK`

全量回归连续 5 次

- 结果：成功
- 输出摘要：
  - `total_failures=0/5`

### 3.2 观察项

- `dectl config show --json` 仍返回 `exit 2`（`argparse` 全局参数顺序约束），但已在 `.ai/temp/cli-spec.md` 明确要求全局参数前置，当前不视为缺陷。

## 4. 缺陷统计

- P0 缺陷：`0`
- P1 缺陷：`0`
- 产品缺陷：`0`
- 体验问题：`0`
- 技术债：`0`

## 5. 未覆盖场景

- 真实 OpenAI API 联调
- OpenAI 路径审批后 `resume` 的专项端到端
- REST 入口端到端
- 跨机器 / NFS 文件锁
- Windows 平台兼容性

## 6. 已知限制

- 当前默认员工仍使用 `mock` provider；`openai` 主要通过自动化回归验证
- `--profile` 参数仅记录，不改变实际配置加载行为
- 构建命令 `python3 -m build` 依赖本地安装 `build` 包

## 7. 发布建议

**Go**

原因：

- 本轮新增能力（`replay run`）已通过集成回归
- 后台恢复链路稳定性经循环验证通过
- 全量测试基线提升到 `98` 且连续 5 轮无失败
- 无 P0/P1 缺陷
