# 发布指南 · 2026-04-01-v2

## 0. 当前发布结论

**Go**

依据 `.ai/reports/qa-report-20260401-v2.md`，前次 4 个 P0 阻塞项全部修复，87 个测试通过，无新增 P0/P1 缺陷。

## 1. 版本信息

- 包名：`digital-employee`
- CLI 命令：`dectl`
- 版本号：`0.1.0`
- Python 要求：`>=3.12`
- 唯一运行时依赖：`pyyaml>=6`

## 2. 发布前检查清单

- [x] `.ai/reports/qa-report-20260401-v2.md` 结论为 `Go`
- [x] 所有 P0 缺陷关闭
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'` 通过（87 tests OK）
- [x] `dectl --json config show` 输出稳定且可解析
- [x] `dectl --json config validate` 对坏配置返回 `exit 3` + `ok=false`
- [x] `dectl --json employee test sales-assistant --input "smoke"` 通过
- [x] 租户隔离回归通过：`tenant-b` 不能读取 `tenant-a` 工单
- [x] 文件仓储并发写入已通过 `fcntl` advisory lock 保护
- [ ] `pyproject.toml` 中版本号与 Git Tag 一致（待创建 tag）
- [ ] CHANGELOG 或发布说明准备完成
- [ ] Release 产物生成后已计算 checksum
- [ ] 发布包中不包含真实密钥、测试数据或本地状态目录

## 3. 构建矩阵

| OS | ARCH | Python 版本 | 产物建议 |
|---|---|---|---|
| `darwin` | `amd64` | `3.12.x` | `wheel` + `tar.gz` |
| `darwin` | `arm64` | `3.12.x` | `wheel` + `tar.gz` |
| `linux` | `amd64` | `3.12.x` | `wheel` + `tar.gz` |
| `linux` | `arm64` | `3.12.x` | `wheel` + `tar.gz` |

注意：Windows 暂未纳入构建矩阵（`fcntl` 不可用），后续版本补齐。

## 4. 打包与校验和策略

### 4.1 构建

```bash
python3 -m pip install --upgrade build
python3 -m build
```

产物：

- `dist/digital_employee-0.1.0.tar.gz`
- `dist/digital_employee-0.1.0-py3-none-any.whl`

### 4.2 校验和

```bash
sha256sum dist/* > checksums.txt
```

## 5. 分发方案

### 5.1 GitHub Releases

1. 创建 tag：`v0.1.0`
2. 上传 `sdist`、`wheel`、`checksums.txt`
3. 发布说明需明确：
   - 当前为 M1 骨架版本
   - 支持的命令范围（config / employee / work-order / session / approval / tool / doctor / replay）
   - 已知限制（REST 未落地、Windows 未支持、`--profile` 仅记录）
   - 唯一运行时依赖为 `pyyaml>=6`

### 5.2 本地安装

```bash
python3 -m pip install digital_employee-0.1.0-py3-none-any.whl
```

或源码模式：

```bash
PYTHONPATH=./src python3 -m digital_employee.api.cli.main version
```

### 5.3 Homebrew / Scoop

暂不接入。待 QA 连续两个版本 `Go` 后考虑。

## 6. 配置与凭证说明

配置优先级：`flag > env > config file > default`

关键环境变量：

| 变量 | 说明 |
|---|---|
| `DE_BASE_URL` | API 基础地址 |
| `DE_API_TOKEN` | API 访问令牌 |
| `DE_TENANT` | 租户标识 |
| `DE_PROFILE` | 配置画像（当前仅记录） |
| `DE_TIMEOUT` | 请求超时秒数 |
| `DE_OUTPUT` | 默认输出格式（human / json） |
| `DE_NO_INPUT` | 禁止交互式输入 |
| `DE_STATE_DIR` | 自定义状态目录路径 |
| `OPENAI_API_KEY` | OpenAI provider 密钥 |

默认状态目录：项目根下 `.de-state/`，按租户分子目录隔离。

## 7. 回滚与旧版本兼容策略

- 当前为首次发布（`0.1.0`），无前序版本需要兼容
- 状态文件格式不承诺长期兼容，后续版本若切换存储方案需提供迁移说明
- 回滚步骤：`pip install digital_employee==<上一版本>` 并恢复状态目录备份

## 8. 发布后验证步骤

```bash
dectl version
dectl --json config show
dectl --json config validate
dectl --json employee test sales-assistant --input "release smoke"
dectl --json --tenant tenant-a work-order create --employee sales-assistant --input "isolation test"
dectl --json --tenant tenant-b work-order list  # 应返回空列表
```

判定标准：

- 所有命令退出码符合 CLI 规范
- `stdout` 可稳定解析为 JSON
- `stderr` 不出现 traceback
- `tenant-b` 不得看到 `tenant-a` 资源
