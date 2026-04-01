# 评审报告 · 20260401-v5（产品化推进回归评审）

## 0. 评审范围

- 本轮评审聚焦文档对齐与产品化阻塞项修复后的代码事实：
  - `src/digital_employee/infra/repositories/sessions.py`
  - `src/digital_employee/infra/repositories/projections.py`
  - `src/digital_employee/infra/repositories/events.py`
  - `src/digital_employee/api/cli/event_stream.py`
  - `src/digital_employee/api/cli/replay_cmd.py`
  - `src/digital_employee/application/use_cases/replay_use_cases.py`
  - `src/digital_employee/application/services/facades.py`
  - `src/digital_employee/bootstrap/factories.py`
  - `tests/integration/cli/test_replay_commands.py`

## 1. 阻塞项

### 未发现阻塞问题

- `replay run` 已实现并接入 CLI 主链：
  - `src/digital_employee/api/cli/replay_cmd.py:6-16`
  - `src/digital_employee/application/use_cases/replay_use_cases.py:12-46`
- 文件仓储并发一致性增强：
  - `src/digital_employee/infra/repositories/sessions.py:19-41`
  - `src/digital_employee/infra/repositories/projections.py:19-41`
  - `src/digital_employee/infra/repositories/events.py:30-40`
- 后台恢复链路收尾稳定性增强：
  - `src/digital_employee/api/cli/event_stream.py:72-140`

## 2. 建议项

### 建议项 1：`events.jsonl` 全量读取为 O(n)，后续可考虑增量游标读取

- 位置：
  - `src/digital_employee/infra/repositories/events.py:30-46`
- 影响：
  - 当前规模下可接受；当单租户事件量明显增长时，`watch/tail/replay` 的读放大将上升。
- 建议：
  - 后续迭代加入按 offset 或时间窗口的增量读取接口，并在 `EventLedgerRepository` 合约中标准化。

### 建议项 2：后台 runner 存活判定仍是进程级启发式

- 位置：
  - `src/digital_employee/api/cli/event_stream.py:114-140`
- 影响：
  - 目前已覆盖本地回归与测试清理问题，但不是跨主机、跨运行时的通用 lease 协议。
- 建议：
  - 若后续引入多实例执行，优先切到显式 lease 记录或进程心跳 TTL 作为判定依据。

## 3. 分类扫描补充

### 3.1 正确性问题

- 未发现阻塞级正确性问题。

### 3.2 分层与依赖问题

- 本轮改动保持分层边界：`replay` 走 `use_cases + facade`，CLI 未直接访问仓储实现。

### 3.3 并发 / 取消 / 超时风险

- 并发读写一致性风险较前版下降（原子写 + 读锁）。
- 残余扩展性风险见建议项 1/2。

### 3.4 配置与密钥泄露风险

- 未发现新增明文凭证输出或落盘行为。

### 3.5 输出协议与 CLI 规范偏差

- `replay run` 现在返回标准 JSON 包裹，已消除“命令已声明但未实现”的协议偏差。

### 3.6 缺失测试与回归风险

- 本轮新增了 `replay` 集成测试：
  - `tests/integration/cli/test_replay_commands.py:18-77`
- 全量回归基线已提升到 `98` 测试并稳定通过。

## 4. 结论

- 未发现阻塞项。
- 建议进入 QA / 发布文档更新阶段。
- 残余风险主要在规模化与跨主机场景，不阻塞当前版本交付。
