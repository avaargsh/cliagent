# 评审报告 · 20260401-v2（回归评审）

## 0. 评审范围

本报告是 `review-report-20260401.md` 的回归评审。聚焦确认前次 4 个阻塞项是否修复，并扫描残余风险。

## 1. 前次阻塞项修复确认

### 阻塞项 1（已修复）：CLI 异常收口

- 修复位置：
  - `src/digital_employee/api/cli/main.py:109-122` — 新增 `DigitalEmployeeError` 和 `except Exception` catch-all
  - `src/digital_employee/api/cli/common.py:82-89` — `resolve_text_input` 将 `OSError` 包装为 `CommandFailure`
  - `src/digital_employee/bootstrap/container.py:57-61` — 配置加载阶段将 `OSError/KeyError/TypeError/ValueError/yaml.YAMLError` 统一转为 `ConfigError`
- 验证：
  - `test_unexpected_error_returns_exit_1_json` / `test_unexpected_error_returns_exit_1_human` 通过
  - `test_input_file_error_maps_to_exit_2_json` / `test_input_file_error_maps_to_exit_2_human` 通过
  - `test_malformed_config_returns_config_error` 通过
- 结论：**已修复，无残余**

### 阻塞项 2（已修复）：租户隔离

- 修复位置：
  - `src/digital_employee/infra/repositories/work_orders.py:14-18` — `FileWorkOrderRepository` 按 `tenant` 分目录存储
  - `src/digital_employee/infra/repositories/sessions.py:14-17` — `FileSessionRepository` 同样按 `tenant` 分目录
  - `src/digital_employee/infra/repositories/approvals.py` — 同样按 `tenant` 分目录
  - `src/digital_employee/bootstrap/factories.py:73-80` — `build_repositories()` 传递 `tenant` 参数
- 验证：
  - `test_different_tenants_see_different_data` / `test_default_tenant_is_isolated`（单元测试）通过
  - `test_tenant_b_cannot_see_tenant_a_work_orders`（CLI 集成测试，本轮新增）通过
- 结论：**已修复，无残余**

### 阻塞项 3（已修复）：配置校验阻断

- 修复位置：
  - `src/digital_employee/api/cli/main.py:90-95` — 非白名单命令遇到 `validation_issues` 时抛出 `ConfigError`
  - `src/digital_employee/application/use_cases/config_use_cases.py:33-39` — `validate_config()` 在有 issues 时抛 `ConfigError`
  - `src/digital_employee/domain/errors.py:19-26` — `ConfigError` 固定 `exit_code=3`
- 验证：
  - `test_work_order_create_blocked_on_bad_config` 通过（exit 3）
  - `test_employee_list_blocked_on_bad_config` 通过（exit 3）
  - `test_config_show_allowed_on_bad_config` 通过（exit 0，白名单放行）
  - `test_config_validate_allowed_on_bad_config` 通过（exit 3，检测到问题后报错）
- 结论：**已修复，无残余**

### 阻塞项 4（已修复）：文件仓储无锁

- 修复位置：
  - `src/digital_employee/infra/repositories/work_orders.py:24-29,56-74` — `save()` 通过 `_FileLock(fcntl.LOCK_EX)` 串行化写入
  - `src/digital_employee/infra/repositories/sessions.py:19-22` — `FileSessionRepository.save()` 同样使用 `_FileLock`
- 结论：**已修复**。当前使用 advisory file lock，在同一台机器的多进程场景下有效。跨机器或 NFS 场景下需要升级为分布式锁，但不属于当前 M1 范围。

## 2. 残余建议项

### 建议项 1：`employee test` 仍在 CLI 层使用 `asyncio.run()`

- 位置：`src/digital_employee/api/cli/employee_cmd.py:38`
- 现状：`employee test` 现在通过 `RuntimeManager.get_for_employee()` 获取 `RuntimeCell`，再调用 `cell.turn_engine.run()`，不再硬编码 `MockProvider`。provider 选择已正确。
- 残余风险：如果 REST 层复用同一 use case，在已有事件循环中 `asyncio.run()` 会抛 `RuntimeError`。
- 建议：在 REST 层接入前，把 `asyncio.run()` 下沉到 CLI 适配层的调度入口。当前不阻塞发布。

### 建议项 2：`--profile` 未接入分层配置源

- 位置：`src/digital_employee/infra/config/loader.py:113`
- 现状：`profile` 仅记录在 `LoadedConfig` 中，没有加载 profile-specific 配置文件。
- 影响：CLI 接受 `--profile` 但不会改变实际行为。
- 建议：在实现前考虑在 `--help` 中标注"仅记录，暂不生效"，或在 `config show` 的输出中显式标记。当前不阻塞发布。

### 建议项 3：仓储损坏恢复

- 位置：`src/digital_employee/infra/repositories/work_orders.py:43-49`
- 现状：如果 `work_orders.json` 内容损坏（非 JSON），`_load()` 会抛 `json.JSONDecodeError`，被 CLI catch-all 捕获为 `internal_error`。
- 建议：可以给出更明确的错误提示，指引用户检查状态目录。不阻塞发布。

## 3. 结论

- 前次 4 个阻塞项全部修复，且有对应测试覆盖。
- 残余 3 个建议项均不影响控制面协议稳定性。
- **建议进入 QA 验收。**
