# 架构约束

## 工具链

- Python 版本：`>=3.12`
- 格式化：项目标准 Python 风格
- 基础验证：`python3 -m unittest discover -s tests -p 'test_*.py'`
- 类型注解：使用 `from __future__ import annotations` + 标准库类型

## 依赖策略

- 优先标准库
- 唯一运行时依赖：`pyyaml>=6`
- 仅在明显降低复杂度时引入轻依赖
- 禁止为了未来扩展预埋重抽象
- REST 层依赖（`fastapi`、`pydantic`）采用懒加载，不阻塞 CLI 主链路

## 工程规则

- `api/` 仅做命令组装和接入适配
- 业务编排进入 `application/commands/` 和 `application/queries/`
- 执行逻辑进入 `runtime/`
- 错误统一保留上下文，使用领域错误层（`DigitalEmployeeError` 及子类）
- 诊断信息输出到 `stderr`
- 所有运行时状态名和事件名统一定义在 `domain/runtime_constraints.py`

## 安全要求

- API Key 仅从环境变量读取
- 日志默认脱敏
- 租户隔离：状态目录按租户分目录存储
- 禁止把 `AGENTS.md` 当作机器配置源
