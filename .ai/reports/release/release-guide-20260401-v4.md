# 发布指南 · 2026-04-01-v4

## 0. 当前发布结论

**Go**

依据 `.ai/reports/qa-report-20260401-v4.md`：

- 新增 `replay run` 已验收通过
- 背景恢复链路稳定性回归通过（20 次循环 0 失败）
- 全量回归 `Ran 98 tests` 且 5 轮稳定

## 1. 版本信息

- 包名：`digital-employee`
- CLI 命令：`dectl`
- 版本号：`0.1.0`
- Python 要求：`>=3.12`
- 当前回归环境：`Python 3.13.9`
- 唯一运行时依赖：`pyyaml>=6`

## 2. 发布前检查清单

- [x] `.ai/reports/qa-report-20260401-v4.md` 结论为 `Go`
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'` 通过（`Ran 98 tests`, `OK`）
- [x] `PYTHONPATH=src python3 -m unittest tests.integration.cli.test_replay_commands -v` 通过
- [x] `approval -> resume --background` 稳定性回归通过（20 次循环 0 失败）
- [x] 文档已对齐全局参数规则（全局参数前置）
- [ ] Git Tag `v0.1.0` 已创建并指向待发布提交
- [ ] `python3 -m build` 已执行并生成 `sdist + wheel`
- [ ] 已生成 `checksums.txt`
- [ ] 已生成 checksum 签名
- [ ] 已生成 Artifact Attestation
- [ ] 发布产物不包含 `.ai/`、`.de-state/`、测试状态目录、凭证

## 3. 构建矩阵

| OS | ARCH | Python 版本 | 产物建议 |
|---|---|---|---|
| `darwin` | `amd64` | `3.12.x`, `3.13.x` | `wheel` + `sdist` |
| `darwin` | `arm64` | `3.12.x`, `3.13.x` | `wheel` + `sdist` |
| `linux` | `amd64` | `3.12.x`, `3.13.x` | `wheel` + `sdist` |
| `linux` | `arm64` | `3.12.x`, `3.13.x` | `wheel` + `sdist` |

说明：Windows 暂未纳入矩阵（当前文件锁依赖 `fcntl`）。

## 4. 打包与校验和策略

### 4.1 构建

```bash
python3 -m pip install --upgrade build
python3 -m build
```

预期产物：

- `dist/digital_employee-0.1.0.tar.gz`
- `dist/digital_employee-0.1.0-py3-none-any.whl`

### 4.2 校验和

macOS:

```bash
shasum -a 256 dist/* > checksums.txt
```

Linux:

```bash
sha256sum dist/* > checksums.txt
```

### 4.3 可信链

- 上传 `checksums.txt` 与签名文件（如 `checksums.txt.sig`）
- 配置并发布 Artifact Attestation

## 5. 分发方案

### 5.1 GitHub Releases

上传以下文件：

- `digital_employee-0.1.0-py3-none-any.whl`
- `digital_employee-0.1.0.tar.gz`
- `checksums.txt`
- `checksums.txt.sig`

发布说明需明确：

- 支持命令范围（含 `replay run`）
- 已知限制（REST 未完成、Windows 未支持、`--profile` 仅记录）
- 全局参数规则：`dectl --json config show`（参数前置）

### 5.2 压缩包分发

- 同步提供 `sdist` 压缩包
- 安装示例：

```bash
python3 -m pip install digital_employee-0.1.0-py3-none-any.whl
```

### 5.3 Homebrew / Scoop

- 本版本不启用 Homebrew / Scoop 正式分发
- 条件：Windows 兼容完成、发布流程稳定后再评估

## 6. 配置与凭证说明

配置优先级：`flag > env > config file > default`

关键环境变量：

| 变量 | 说明 |
|---|---|
| `DE_BASE_URL` | API 基础地址 |
| `DE_TENANT` | 默认租户 |
| `DE_PROFILE` | 默认 profile（当前仅记录） |
| `DE_TIMEOUT` | 请求超时秒数 |
| `DE_OUTPUT` | 默认输出格式 |
| `DE_NO_INPUT` | 禁止交互 |
| `DE_STATE_DIR` | 自定义状态目录 |
| `OPENAI_API_KEY` | OpenAI provider 密钥 |
| `OPENAI_BASE_URL` | OpenAI provider 覆盖地址 |

安全规则：

- 不写入真实密钥到文档、日志、状态文件
- 发布产物中不打包本地状态目录

## 7. 回滚与兼容策略

- `0.1.0` 为首个公开版本，状态文件格式不承诺跨大版本兼容
- 回滚步骤：

```bash
python3 -m pip uninstall digital-employee
python3 -m pip install digital-employee==<previous-version>
```

- 回滚后需恢复对应版本的状态目录备份

## 8. 发布后验证步骤

```bash
dectl version
dectl --json config show
dectl --json config validate
dectl --json employee test sales-assistant --input "release smoke"
dectl --json work-order create --employee sales-assistant --input "release replay smoke"
dectl --json replay run <work-order-id>
```

判定标准：

- 命令退出码符合 CLI 规范
- JSON 输出稳定可解析
- `stderr` 无 traceback
- `replay run` 返回结构化事件时间线
