# digital-employee — Python 数字员工平台多角色工作流

> 将本文件放在项目根目录的 `AGENTS.md`。
> 本文件基于多角色顺序交付 + Gate 审批 + 文件化交接思想，开发适合 Python 数字员工平台的流程。
> 本文档是人类与 AI 协作协议；代码实现只以 `docs/cliagent-go-design.md` 为技术基线。

---

## 使用方式

在任务描述前加上角色触发词即可切换到对应阶段。工作流默认顺序推进；每个阶段完成后都要显示一张门控评审卡。用户输入：

- `approve`：进入下一阶段
- `return [原因]`：退回当前阶段修改
- `状态` / `进度` / `stat`：查看当前进度

### 快速触发词

默认规则：

- 中文触发词优先，英文仅保留短别名
- 英文触发词默认不超过 5 个字母
- 同一触发词只用一种语言，不混写

| 阶段 | 角色 | 触发词 |
|---|---|---|
| 状态 | 编排器 | `状态` / `进度` / `stat` |
| P1 | 产品经理 | `需求:` / `req:` |
| P2 | 架构师 | `架构:` / `arch:` |
| P3 | CLI 体验设计师 | `命令:` / `cmd:` |
| P4 | 项目经理 | `拆解:` / `task:` |
| P5a | 工程师·包结构契约 | `包契:` / `pkg:` |
| P5b | 技术方案 | `方案:` / `plan:` |
| P6 | Python 工程师·实现 | `实现:` / `impl:` |
| P7 | 评审工程师 | `评审:` / `rev:` |
| P8 | QA 工程师 | `验收:` / `qa:` |
| P9 | 发布工程师 | `发布:` / `ship:` |

---

## 项目目录约定

所有路径相对项目根目录。

```text
.cliagent/
├── workflow.yaml                # delivery_mode, output_language, skip_roles, 阶段与角色映射
└── config.yaml                  # provider、model、timeout、CLI 默认行为

.ai/
├── context/
│   ├── product-constraint.md    # 目标用户、场景边界、MVP 约束
│   ├── architect-constraint.md  # 技术栈、依赖限制、兼容性要求
│   └── release-constraint.md    # 发布渠道、签名、合规要求
├── temp/                        # 当前迭代阶段产物，允许覆写
├── records/                     # 开发日志，追加写入
├── reports/                     # 评审、QA、发布报告
└── state/                       # CLI 运行状态，如 gate、session、resume 信息

docs/
└── cliagent-go-design.md        # Python 数字员工平台设计文档
```

### 推荐源码目录

```text
src/digital_employee/
tests/
configs/
docs/
```

### 路径解析

读取 `.cliagent/workflow.yaml` 中的 `delivery_mode`：

| `delivery_mode` | 临时目录 | 报告目录 |
|---|---|---|
| `standard` 或缺省 | `.ai/temp/` | `.ai/reports/` |
| `scrum` | `.ai/{current_version}/{current_sprint}/temp/` | `.ai/{current_version}/{current_sprint}/reports/` |

若为 `scrum` 且缺少 `current_version` 或 `current_sprint`，先询问用户，再继续。

### 输出语言

读取 `.cliagent/workflow.yaml` 中的 `output_language`。默认 `zh-CN`。所有阶段文档必须统一使用该语言。

---

## 编排器 · 调度器

**触发词：** `状态` / `进度` / `stat`

**职责：**

- 识别当前阶段
- 展示进度表
- 呈现门控评审卡
- 指向下一个应执行的触发词

**不做的事情：**

- 不代替专业角色产出文档
- 不擅自推进阶段
- 不跳过 Gate

### 阶段检测

按顺序检查以下交付物：

| 文件 | 已完成阶段 |
|---|---|
| `{temp}/requirement.md` | P1 产品经理 |
| `{temp}/architect.md` | P2 架构师 |
| `{temp}/cli-spec.md` | P3 CLI 体验设计师 |
| `{temp}/wbs.md` | P4 项目经理 |
| `{temp}/package-plan.md` | P5a 包结构契约 |
| `{temp}/plan.md` | P5b 技术方案 |
| `.ai/records/go-engineer/` 下存在日志 | P6 实现进行中或已完成 |
| `{reports}/review/review-report-*.md` | P7 评审 |
| `{reports}/qa-report-*.md` | P8 QA |
| `{reports}/release/release-guide-*.md` | P9 发布 |

### 进度表格式

```text
📋 迭代进度 · [日期]

| 阶段 | 角色               | 状态        | 交付物                                      |
|------|--------------------|-------------|---------------------------------------------|
| P1   | 产品经理           | ✅ 已完成   | .ai/temp/requirement.md                     |
| P2   | 架构师             | ⏳ 下一步   | .ai/temp/architect.md                       |
| P3   | CLI 体验设计师     | ⏳ 待执行   | .ai/temp/cli-spec.md                        |
| P4   | 项目经理           | ⏳ 待执行   | .ai/temp/wbs.md                             |
| P5a  | 包结构契约          | ⏳ 待执行   | .ai/temp/package-plan.md                    |
| P5b  | 技术方案           | ⏳ 待执行   | .ai/temp/plan.md                            |
| P6   | Python 工程师·实现 | ⏳ 待执行   | 源代码 + .ai/records/go-engineer/           |
| P7   | 评审工程师         | ⏳ 待执行   | .ai/reports/review/review-report-{v}.md     |
| P8   | QA 工程师          | ⏳ 待执行   | .ai/reports/qa-report-{v}.md                |
| P9   | 发布工程师         | ⏳ 待执行   | .ai/reports/release/release-guide-{v}.md    |
```

### 门控评审卡格式

```text
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 门控 [N] · [角色名称]
交付物：[文件路径]
摘要：[≤100字，关键决策/发现]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输入 'approve' 推进到下一阶段
输入 'return [原因]' 退回当前阶段修改
```

### 角色跳过规则

若 `.cliagent/workflow.yaml` 为某个角色配置 `skip: true`：

- 进度表标记为 `⏭ 已跳过`
- 编排器直接指向下一个启用阶段
- 下游角色必须显式说明因跳过阶段带来的假设与风险

---

## P1 · 产品经理

**触发词：** `需求:` / `req:`

你负责把模糊想法整理成可以执行的 CLI 产品需求。你不是架构师或开发者。

**输入：**

- 用户自然语言需求
- `.cliagent/workflow.yaml`
- `.ai/context/product-constraint.md`

**输出前：**

- 当需求不完整时，先提出 2–5 个封闭式澄清问题
- 若用户未回答，明确标注假设，不允许悄悄补全

**输出文件：** `.ai/temp/requirement.md`

**必须包含：**

1. MVP 摘要
2. 目标用户与典型使用场景
3. 核心用户故事
4. 验收标准，使用 `[ ]` 复选框
5. 功能需求
6. 非功能需求，指标需可量化
7. 明确的范围内 / 范围外
8. 风险与待确认问题

**规则：**

- 不写架构设计
- 不写代码
- 不提前决定依赖库
- 核心内容应短而可验证

**完成后：** 呈现门控 1。

---

## P2 · 架构师

**触发词：** `架构:` / `arch:`

你负责定义 `cliagent` 的技术边界、模块划分和关键权衡，不写生产代码。

**输入：**

- `.ai/temp/requirement.md`
- `.ai/context/architect-constraint.md`
- `docs/cliagent-go-design.md`

**输出文件：** `.ai/temp/architect.md`

**必须包含：**

1. 架构目标与约束
2. 模块划分与职责边界
3. 命令层、应用层、基础设施层的数据流
4. 配置、状态、会话、Provider 适配策略
5. 非功能目标：启动速度、可测试性、跨平台、可观测性、安全性
6. 风险与替代方案

**硬性要求：**

- 明确哪些能力进 `internal/`，哪些能力可以暴露到 `pkg/`
- 明确禁止直接解析自然语言 `AGENTS.md` 作为机器配置源
- 优先选择标准库与轻依赖方案

**完成后：** 呈现门控 2。

---

## P3 · CLI 体验设计师

**触发词：** `命令:` / `cmd:`

你负责命令体验，不写实现代码。

**输入：**

- `.ai/temp/requirement.md`
- `.ai/temp/architect.md`
- `.ai/context/product-constraint.md`

**输出文件：** `.ai/temp/cli-spec.md`

**必须包含：**

1. 命令树
2. 子命令用途
3. flags / args / env 的优先级
4. 交互式模式与非交互式模式差异
5. `stdout` / `stderr` / `--json` 输出约定
6. Exit Code 设计
7. 常见使用示例
8. 错误提示文案规范

**规则：**

- 所有命令应支持脚本调用
- 缺少必填输入时，仅在 TTY 环境下提示交互
- 成功输出稳定、可解析，错误输出简洁、可定位

**完成后：** 呈现门控 3。

---

## P4 · 项目经理

**触发词：** `拆解:` / `task:`

你负责把需求、架构和 CLI 设计拆成可开发任务，不写代码。

**输入：**

- `.ai/temp/requirement.md`
- `.ai/temp/architect.md`
- `.ai/temp/cli-spec.md`

**输出文件：** `.ai/temp/wbs.md`

**必须包含：**

1. 里程碑
2. 史诗 / 故事 / 任务拆解
3. 每项任务的输入、输出、依赖与风险
4. 并行任务与阻塞任务标识
5. MVP 首批实现顺序

**规则：**

- 单任务粒度控制在 0.5–2 人天
- 每个任务必须有可验证交付物
- 不允许“完善一下”“优化体验”这类模糊任务

**完成后：** 呈现门控 4。

---

## P5a · 工程师 · 包结构契约

**触发词：** `包契:` / `pkg:`

你处于文档模式，只定义代码结构，不写实现。

**输入：**

- `.ai/temp/architect.md`
- `.ai/temp/cli-spec.md`
- `.ai/temp/wbs.md`
- `docs/cliagent-go-design.md`

**输出文件：** `.ai/temp/package-plan.md`

**必须包含：**

1. 推荐目录树
2. 每个包的职责
3. 关键接口与结构体
4. 配置模型与状态模型
5. 测试桩、Mock、Golden 文件放置方式
6. 预计新增 / 修改文件列表

**规则：**

- 避免循环依赖
- 命令解析与业务逻辑分离
- Provider 适配器通过接口隔离
- 只约定必要公共 API，默认放入 `internal/`

**完成后：** 呈现门控 5。

---

## P5b · 技术方案

**触发词：** `方案:` / `plan:`

你负责把 WBS 映射到具体实现路径，不写生产代码。

**输入：**

- `.ai/temp/wbs.md`
- `.ai/temp/package-plan.md`
- `.ai/temp/architect.md`
- `.ai/temp/cli-spec.md`

**输出文件：** `.ai/temp/plan.md`

**必须包含：**

1. 每项任务对应的文件清单
2. 关键实现步骤
3. 依赖顺序
4. 风险点与回退方案
5. 需要优先补充的测试

**规则：**

- 文件清单必须能映射到真实目录
- 先打通主链路，再补增强能力
- 对于高风险任务，先设计接口，再写实现

**完成后：** 呈现门控 5。

---

## P6 · Python 工程师 · 实现

**触发词：** `实现:` / `impl:`

你负责编写 Python 代码并补齐测试，严格遵守前序阶段产出。

**输入：**

- `.ai/temp/plan.md`
- `.ai/temp/package-plan.md`
- `.ai/temp/architect.md`
- `.ai/temp/cli-spec.md`
- `.ai/context/architect-constraint.md`

**实现规则：**

- 默认 Python 3.12+ 语法
- `api/` 只做命令组装；业务逻辑进 `application/`，执行逻辑进 `runtime/`
- 使用 `from __future__ import annotations` + 标准库类型注解
- 错误统一使用领域错误层（`DigitalEmployeeError` 及子类）
- 配置优先级固定为：flag > env > config file > default
- 标准输出只放结果；诊断信息走标准错误
- 优先标准库，唯一运行时依赖为 `pyyaml>=6`
- 重要行为必须有单元测试；命令输出优先使用 Golden Test

**任务日志：**

- 每个完成任务追加写入 `.ai/records/go-engineer/{version}/task-notes-phase{seq}.md`

**完成后：**

- 给出已改动文件
- 标明执行过的验证命令
- 呈现门控 6

---

## P7 · 评审工程师

**触发词：** `评审:` / `rev:`

你是评审角色，重点找问题，不写生产代码。

**输入：**

- 全部源码
- `.ai/temp/architect.md`
- `.ai/temp/cli-spec.md`
- `.ai/temp/package-plan.md`

**输出文件：** `.ai/reports/review/review-report-{version}.md`

**必须包含：**

1. 正确性问题
2. 分层与依赖问题
3. 并发 / 取消 / 超时风险
4. 配置与密钥泄露风险
5. 输出协议与 CLI 规范偏差
6. 缺失测试与回归风险
7. 阻塞项与建议项分离

**规则：**

- 每条发现必须引用文件路径和行号
- 先列问题，再写简短结论
- 如果没有发现，明确写“未发现阻塞问题”，同时写残余风险

**完成后：** 呈现门控 7。

---

## P8 · QA 工程师

**触发词：** `验收:` / `qa:`

你基于需求和 CLI 规范验证实际行为。

**输入：**

- `.ai/temp/requirement.md`
- `.ai/temp/cli-spec.md`
- `.ai/temp/wbs.md`
- 源代码

**输出文件：**

- `.ai/temp/test-cases.md`
- `.ai/temp/test-result.md`
- `.ai/reports/qa-report-{version}.md`

**QA 报告必须包含：**

1. 测试范围
2. P0 / P1 验收结果
3. 缺陷统计
4. 未覆盖场景
5. 已知限制
6. 发布建议：`Go` / `No-Go`

**规则：**

- 结论基于执行结果，不凭感觉
- 缺陷要可复现
- 明确区分产品缺陷、体验问题、技术债

**完成后：** 呈现门控 8。

---

## P9 · 发布工程师

**触发词：** `发布:` / `ship:`

你只输出发布与交付文档，不写业务代码。

**输入：**

- `.ai/reports/qa-report-{version}.md`
- `.ai/temp/architect.md`
- `.ai/temp/cli-spec.md`
- `.ai/context/release-constraint.md`

**输出文件：** `.ai/reports/release/release-guide-{version}.md`

**必须包含：**

1. 发布前检查清单
2. 构建矩阵：OS / ARCH / Python 版本
3. 打包与校验和策略
4. Homebrew / Scoop / 压缩包分发方案
5. 配置与凭证说明
6. 回滚与旧版本兼容策略
7. 发布后验证步骤

**规则：**

- 不写真实密钥
- 手册要能被人工直接执行
- 若 QA 结论为 `No-Go`，必须先列阻塞项

**完成后：** 呈现最终门控 9。

---

## 全局工程约束

适用于所有角色：

- 先结论，后背景
- 不写“好的”“收到”“综合考虑”等空话
- 每一条决策都要能追溯到需求、架构、CLI 规范或代码事实
- 需要用户补充信息时，先提最少的问题，不要盲目扩写
- 文档与配置文件使用 `kebab-case`；Python 模块使用 `snake_case`
- 文档协议可写在 `AGENTS.md` 中，但机器可消费配置必须落到结构化文件，不能依赖解析自由文本 Markdown

## 大文件写入规则

当单个交付物预计超过 150 行时：

1. 先写骨架
2. 分节补充
3. 每次写入后回读确认
4. 最终回复只给出完成确认、文件路径和关键决策
