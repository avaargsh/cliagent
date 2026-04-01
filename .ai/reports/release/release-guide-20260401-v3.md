# 发布指南 · 2026-04-01-v3

## 0. 当前发布结论

**Go**

依据 `.ai/reports/qa-report-20260401-v3.md`，本轮 OpenAI provider 回归验收通过：

- 前次评审阻塞的 2 个问题已关闭
- 全量 `96` 个测试通过
- 当前仅剩 1 个非阻塞 P1 偏差：CLI 全局 flag 位置与规范示例不一致

## 1. 版本信息

- 包名：`digital-employee`
- CLI 命令：`dectl`
- 版本号：`0.1.0`
- Python 要求：`>=3.12`
- 当前回归环境：`Python 3.13.9`
- 唯一运行时依赖：`pyyaml>=6`

## 2. 发布前检查清单

- [x] `.ai/reports/qa-report-20260401-v3.md` 结论为 `Go`
- [x] 前次评审阻塞项已在 `.ai/reports/review/review-report-20260401-v4.md` 关闭
- [x] `python3 -m unittest discover -s tests -p 'test_*.py'` 通过（`Ran 96 tests`, `OK`）
- [x] `PYTHONPATH=src python3 -m digital_employee.api.cli.main --json config show` 通过
- [x] `PYTHONPATH=src python3 -m digital_employee.api.cli.main --json employee test sales-assistant --input 'Generate a follow-up draft'` 通过
- [x] `python3 -m unittest tests.unit.providers.test_openai_provider tests.unit.runtime.test_turn_engine tests.unit.memory.test_context_compactor` 通过（`Ran 18 tests`, `OK`）
- [x] 发布说明中已记录 P1 偏差：`--json/--jsonl` 当前必须放在子命令前
- [ ] Git Tag `v0.1.0` 已创建并指向待发布提交
- [ ] `python3 -m build` 已执行并生成 `sdist + wheel`
- [ ] 已生成 `checksums.txt`
- [ ] 已生成 checksum 签名文件
- [ ] GitHub Artifact Attestation 已创建
- [ ] 发布产物中不包含 `.de-state/`、`.ai/`、测试状态目录或真实凭证

## 3. 构建矩阵

| OS | ARCH | Python 版本 | 构建/验收要求 | 产物建议 |
|---|---|---|---|---|
| `darwin` | `amd64` | `3.12.x`, `3.13.x` | 安装 smoke test + CLI smoke test | `wheel` + `sdist` + `tar.gz` |
| `darwin` | `arm64` | `3.12.x`, `3.13.x` | 安装 smoke test + CLI smoke test | `wheel` + `sdist` + `tar.gz` |
| `linux` | `amd64` | `3.12.x`, `3.13.x` | 安装 smoke test + CLI smoke test | `wheel` + `sdist` + `tar.gz` |
| `linux` | `arm64` | `3.12.x`, `3.13.x` | 安装 smoke test + CLI smoke test | `wheel` + `sdist` + `tar.gz` |

说明：

- 当前 wheel 为纯 Python 包，建议至少在 `3.12` 与 `3.13` 做安装和 CLI smoke test。
- Windows 暂未纳入发布矩阵，因为当前文件锁实现依赖 `fcntl`。

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

### 4.3 签名与可信链

发布约束要求：

- 产物 checksum
- checksum 签名
- Artifact Attestation

建议步骤：

1. 生成 `checksums.txt`
2. 对 `checksums.txt` 生成签名文件，例如 `checksums.txt.sig`
3. 在 GitHub Release 上传：
   - `wheel`
   - `sdist`
   - `checksums.txt`
   - `checksums.txt.sig`
4. 启用 GitHub Artifact Attestation，并在发布说明中附验证入口

## 5. 分发方案

### 5.1 GitHub Releases

主发布渠道：`GitHub Releases`

上传内容：

- `digital_employee-0.1.0-py3-none-any.whl`
- `digital_employee-0.1.0.tar.gz`
- `checksums.txt`
- `checksums.txt.sig`
- Artifact Attestation 链接或校验说明

发布说明必须包含：

- 本次为 `0.1.0`
- OpenAI provider 已完成最小运行时接入
- 已知限制：
  - 未进行真实 OpenAI API 联调
  - OpenAI 路径的 `approval -> resume` 尚未做专项 QA
  - Windows 暂不支持
  - `--profile` 当前仅记录，不改变配置加载行为
  - `--json/--jsonl` 当前必须写在子命令前，例如 `dectl --json config show`

### 5.2 压缩包分发

压缩包分发采用 GitHub Release 同步发布：

- 源码压缩包：`digital_employee-0.1.0.tar.gz`
- 如需附带离线安装说明，发布说明中补充：

```bash
python3 -m pip install digital_employee-0.1.0-py3-none-any.whl
```

源码运行 smoke test：

```bash
PYTHONPATH=./src python3 -m digital_employee.api.cli.main version
```

### 5.3 Homebrew

本次版本 **不启用 Homebrew 正式分发**。

策略：

- 本版本以 GitHub Releases + 压缩包为正式渠道
- Homebrew formula 进入待办，触发条件：
  - CLI 全局 flag 使用方式与规范统一
  - 连续版本保持 QA `Go`

若后续启用 Homebrew，建议：

- 使用独立 tap，如 `org/tap`
- formula 安装 `wheel` 或受控源码包
- `test do` 至少执行：

```bash
dectl version
dectl --help
```

### 5.4 Scoop

本次版本 **不启用 Scoop 正式分发**。

原因：

- Windows 尚未进入支持矩阵
- 当前文件锁实现依赖 `fcntl`

若后续启用 Scoop，需先完成：

- Windows 兼容实现
- `session/work-order` 状态目录行为在 Windows 下的专项验收

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
| `DE_OUTPUT` | 默认输出格式（`human` / `json`） |
| `DE_NO_INPUT` | 禁止交互式输入 |
| `DE_STATE_DIR` | 自定义状态目录 |
| `OPENAI_API_KEY` | OpenAI provider 密钥 |
| `OPENAI_BASE_URL` | OpenAI provider 覆盖地址 |

说明：

- 发布包和发布说明中不得包含真实密钥
- 示例命令只使用占位符，不写真实 token
- 发布 smoke test 默认优先走 `mock` provider，不要求现场配置真实 `OPENAI_API_KEY`

## 7. 回滚与旧版本兼容策略

- 当前为首个 `0.1.0` 发布版本，无历史稳定版可回退
- 状态文件格式不承诺长期兼容；后续如变更 session / ledger / projection 结构，必须附迁移说明
- 本次回滚策略：
  - 若发布后发现阻塞问题，撤回安装引导，保留 Release 但标记 `yanked` 或在说明中显式标红
  - 对已安装环境，执行：

```bash
python3 -m pip uninstall digital-employee
```

  - 如存在上一内部验证包，回装指定版本：

```bash
python3 -m pip install digital-employee==<previous-version>
```

  - 恢复前一份状态目录备份

兼容提示：

- 当前 QA 已确认 1 个非阻塞 CLI 体验偏差：全局 flag 需前置
- 若后续版本修正该行为，需在发布说明中标注 CLI 用法兼容变化

## 8. 发布后验证步骤

建议在干净环境执行：

```bash
dectl version
dectl --json config show
dectl --json employee test sales-assistant --input "release smoke"
python3 -m unittest tests.unit.providers.test_openai_provider tests.unit.runtime.test_turn_engine tests.unit.memory.test_context_compactor
```

若按源码入口验证，使用：

```bash
PYTHONPATH=src python3 -m digital_employee.api.cli.main --json config show
PYTHONPATH=src python3 -m digital_employee.api.cli.main --json employee test sales-assistant --input "release smoke"
```

判定标准：

- 命令退出码符合 CLI 规范
- `stdout` 中 JSON 结构稳定
- `stderr` 无 traceback
- `config show` 可看到 `providers.openai`
- `employee test` 主链路输出稳定

## 9. 发布备注

- 本次发布建议把 `QA-005` 写入 release notes，避免用户按文档示例把 `--json` 放在子命令后导致 `exit 2`
- 若决定在发布前顺手修正文档示例，可同步更新 `.ai/temp/cli-spec.md` 与外部 README，再创建 tag
