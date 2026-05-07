# LLM Quality Benchmark — Spec v0.2

> 一个用于评估 Claude Code phase-gated 多 agent 工作流 plugin 质量的 benchmark harness。
> 测的是 **plugin 相对 baseline 的增量(lift)**,以 **程序性质量(well-formedness)** 为主要测度,而非「设计好坏」这种主观判断。

---

## 1. 背景与动机

现有 LLM benchmark(SWE-bench、HumanEval、MMLU 等)绝大多数测的是 **模型** 在绝对任务上的能力,且关注点偏向速度与正确率。Plugin 类工件(Claude Code skill、subagent 工作流)缺乏专门的质量评估方法 — 「它在裸模型基础上贡献了多少?」「多 agent 的复杂度是否值得?」这类问题没有标准答案。

本 benchmark 不试图回答「哪个 design 更好」 — 这是品味问题。它回答的是 **「哪个系统更稳定地产出 well-formed design」** ,这是架构层面可测量的属性。

---

## 2. 核心实验问题

> **专精的 system prompt(每个 agent 一个 role)vs 角色作为读入内容(一个 generic agent 读 role markdown 来扮演)— 哪种架构在 phase-gated 工作流里产出质量更稳?裸 Claude Code 又在哪里?**

这是 LLM 工程里有争议的问题。本 benchmark 试图给出实证证据。

---

## 3. 范围

| 维度 | 决策 |
|---|---|
| 输出类型 | **Design 文档**,不进 implementation 阶段 |
| 输入 | 开放性 idea(故意有歧义) |
| Ground truth | **无**(open-ended,不存在唯一正确答案) |
| 输出格式 | **不约束** — 接受三个 arm 输出形态差异 |
| 范围外 | 速度/延迟、UI dashboard、CI 集成、并发跑、code 阶段评估 |

---

## 4. 三个 Arm

| Arm | 描述 | 调用方式 |
|---|---|---|
| **Vanilla** | 裸 Claude Code,不加任何引导 prompt | `claude -p "<idea 原文>"` (唯一允许的补偿:"请只输出 design 文档,不要写代码") |
| **ShipFlow Main** | 22 个 specialized agent(tech-lead / product-lead / build-lead 等),每个 role 在 system prompt 里 | ShipFlow `main` 分支,通过 Claude Agent SDK 触发 |
| **ShipFlow Mono** | 1 个 generic `shipflow-mono` agent,被 spawn 时读取 `agents/<role>.md` 来扮演角色 — role 作为 user content,不在 system prompt | ShipFlow `experiment/mono-agent` 分支,通过 Claude Agent SDK 触发 |

**关键**:Main 和 Mono 在 phase 编排、role 定义文件上是相同的。**唯一变量是 role 注入位置**(system prompt vs user content)。这是受控实验。

---

## 5. 评估维度(9 个)

### 5.1 程序性指标 — 主轴

这六条不依赖偏好判断,即使没有 ground truth 也成立。

| # | 维度 | 测量方式 |
|---|---|---|
| 1 | **Canon 一致性** | Q&A 阶段 simulator 给出的约束(B2B、AWS-only、预算上限等),design 里有没有真正兑现?canon 列表化后做 pattern check。**Deterministic**。 |
| 2 | **内部一致性** | Design 自己有没有自相矛盾(如「方案 A 用 Postgres」+「数据层用 DynamoDB」)?Judge 找 contradiction pair,**不判优劣**,只数矛盾。 |
| 3 | **决策密度** | Committed decision 在 design 中的占比。「我们用 X」是决策;「需要进一步调研」是 punt;「考虑 X 或 Y」是模糊。Extractor 自动统计。 |
| 4 | **Trace-ability** | 每个决策能否回溯到 idea 或 canon 里的某个具体原因?Judge 对每个决策标 `grounded` / `空降`。 |
| 5 | **Critical decision coverage** | Task 中预先标注的关键决策点(认证方案、数据存储、计费模型等),design 命中了几项?**Deterministic**。 |
| 6 | **Scope Discipline(指令遵循)** | Design 中每个主要决策是否能 trace 到 (a) idea / (b) canon / (c) `must_be_addressed` / (d) Q&A 中 simulator 主动确认?都不是 → unrequested。Unrequested 决策占比越低分越高。**抓 over-engineering / 范围漂移**,与 Trace-ability 互补(Trace-ability 看「该有的有没有依据」,Scope Discipline 看「不该有的有没有混进来」)。 |

### 5.2 提问质量(1)

| # | 维度 | 测量方式 |
|---|---|---|
| 6 | **Question Quality** | 综合四个子维度:Coverage(命中 task 标注的 key ambiguity 数)、Precision(judge 二分:vague vs sharp)、Restraint(总轮数和问题数,过多扣分)、Non-redundancy(后问的是否被前问/idea 覆盖)。 |

### 5.3 模式特定指标(2)— 检测假设的核心证据

| # | 维度 | 测量方式 |
|---|---|---|
| 7 | **Role bleed**(Mono 特有) | 把 Mono 输出按 phase 切片,每段交 judge 反向分类:「这段听起来像哪个 role?」命中率低 = role bleed 严重。 |
| 8 | **Specialization silos**(Main 特有) | Judge 整体打「内部一致性」,加反事实测试:「只读 product-lead 那段,tech-lead 的方案能闭环吗?」 |

---

## 6. 任务结构(Task Schema)

每个 task 是一份 YAML,包含:

```yaml
id: 01_habit_tracker
idea: |
  我想做一个习惯追踪 app。

# 仅 simulator 可见
canon:
  target_user: 25-35 岁互联网从业者,不爱社交
  platform: 优先 web,移动端晚点
  business_model: 个人付费订阅(不做 B2B)
  key_dislike: 讨厌游戏化(积分、徽章、排行榜)
  constraint_tech: 我会 React,后端尽量简单
  constraint_budget: 前 6 个月每月成本 < $50
  out_of_scope: 不做社交功能,但 arm 问起来可以说"也许以后"

# 评 critical decision coverage 用
must_be_addressed:
  - 用户认证方案
  - 数据存储选型
  - 订阅 / 计费机制
  - 部署平台
  - 习惯打卡的交互形式

# 评 question coverage 用
key_ambiguities:
  - 个人 vs 团队
  - web / mobile / both
  - 免费 / 订阅 / 一次买断
  - 游戏化 vs 极简           # canon 里明确反对游戏化,trap
  - 技术栈约束

# 可选:用于评 simulator 的回答策略
canon_silent_on:
  - 是否需要 onboarding 流程
  - 是否需要数据导出
```

**第一批 task 计划**:5 个 — 3 简单 + 1 中等 + 1 trap(canon 故意与 idea 表面冲突的)。

---

## 7. User Simulator + Canon 机制

### 7.1 流程

```
arm 收到 idea
  ↓
arm 提问(可能多轮)
  ↓
harness 拦截每个问题
  ↓
simulator(独立 Claude call)用 canon 回答
  ↓
答案塞回 arm
  ↓
arm 进入 design 阶段,产出 final design
```

### 7.2 Simulator 配置

- **模型**: `claude-sonnet-4-6`(*不用 Opus* — 避免 simulator 比真实用户更聪明,污染对照)
- **System prompt** 关键约束:

  ```
  You play a real user with the facts in <canon>. You do not know what's
  outside the canon. If asked something the canon does not cover, answer
  vaguely like a real user would: "I don't have a strong preference",
  "haven't thought about that yet", "you decide". Do not infer. Do not
  be helpful beyond the canon. Keep answers to 1-3 sentences.
  ```

- **`max_turns`**: 5(防止 arm 无限提问)— 该上限同时是 Restraint 指标的隐含 cap

### 7.3 三个 arm 共享同一个 simulator instance + canon

公平性的硬要求。

---

## 8. 评分策略

### 8.1 Pairwise Tournament(主)

每个维度,judge 一次看 (Vanilla, Main, Mono) 三个输出,产出 ranking,而非分别打 1-5。

理由:pairwise 偏见小,且 token 消耗低于三次独立打分。

### 8.2 Multi-persona ensemble(主观维度兜底)

对天然主观的判断(如「架构是否优雅」),用 3 个 persona 跑同一份 design:

- 产品向 judge
- 工程向 judge
- 保守 ops 向 judge

**三个 persona 一致偏好同一 arm → 该结论计入主分。**
**三个分歧 → 标注为 preference-dependent,在报告里展示但不计入主分。**

### 8.3 Deterministic checks(优先用)

能 deterministic 就不用 judge。具体:

| 维度 | 方式 |
|---|---|
| Canon 一致性 | Pattern match canon 字段在 design 里的呈现 |
| 决策密度 | Decision extractor(committed / punt / fuzzy 三类计数) |
| Critical decision coverage | 命中率统计 |
| Robustness | 同 arm 跑 3 次,比较 decision-list 一致率 |
| Grounding 部分 | 把 design 中事实声明 extract,比对 transcript 是否有对应 Read tool call |

### 8.4 Judge 反偏见条款(写入所有 judge prompt)

> Do not reward output for being more structured, longer, or having more headers. Reward only substantive content. A 200-word focused decision document beats a 2000-word document with the same decisions buried in scaffolding.

理由:Main arm 大概率输出更长更分节的文档,这个偏见不压住会污染整个结果。

### 8.5 Judge 模型

- **主 judge**: `claude-opus-4-7`
- **Persona ensemble judge**: `claude-opus-4-7`(三次跑,不同 system prompt)
- **Decision extractor**: `claude-haiku-4-5-20251001`(便宜,任务结构化)

---

## 9. Robustness

### 9.1 测量

每个 task 的每个 arm 跑 3 次。提取 decision list,计算三次之间的一致率(set 重合度)。

完全 deterministic,**不动 judge**。

### 9.2 范围

不是 9 个维度都跑 3 次。**只在 Canon 一致性、决策密度、Scope Discipline** 这三个最关键的轴上跑 robustness check,降本同时保留信号。

---

## 10. 成本追踪

### 10.1 数据来源

**用户手动提供**,而不是 harness 自动捕获 — 减少实现复杂度。

### 10.2 报送格式

```
Task: 01_habit_tracker   Run: 1

Vanilla:  $0.12    model: claude-opus-4-7
Main:     $0.84    model: claude-opus-4-7 (+ subagents)
Mono:     $0.42    model: claude-opus-4-7

Notes (optional): Main 4 min, Mono 2 min
```

### 10.3 衍生指标

| 指标 | 定义 |
|---|---|
| **Cost-adjusted lift** | Quality lift / cost multiple |
| **Pareto frontier** | x: 总成本,y: quality 综合分,三个 arm 是图上三点 |
| **Token anomaly detection** | Mono design phase token 反常高 → 可能是 role bleed 副作用,与 Role bleed 维度交叉验证 |

---

## 11. 报告结构(三层)

### Layer 1: 一句话结论

> 跑了 N 个 task。在 [维度] 上,[arm A] 显著优于 [arm B](p < α);[arm C] 优势小或不显著。

### Layer 2: Per-dimension 表

| 维度 | Vanilla | Main | Mono | Main lift over Vanilla | Main lift over Mono | Cost-adjusted lift |
|---|---|---|---|---|---|---|
| Canon 一致性 | 0.45 | 0.82 | 0.61 | +0.37 | +0.21 | ... |
| Question coverage | 0.10 | 0.74 | 0.50 | +0.64 | +0.24 | ... |
| ... | | | | | | |

每行带置信区间(开放任务,单点没意义,看分布)。

### Layer 3: Representative Examples

挑 2-3 个 task,贴出三个 arm 的输出,标注 judge 找到的具体证据,如:

> "Mono 在 phase 3 的 tech-lead 段落里出现「用户视角」措辞,疑似 product role bleed"

这部分**最让人信服** — 数字之外要有人类可读的证据。

---

## 12. Pilot 策略

**第一次 pilot**:

```
1 task × 3 arm × 1 run × 4 核心维度
```

4 核心维度建议:Canon 一致性、Critical decision coverage、Question Quality、决策密度。

约 30-40 个 Claude call,几美金,半小时内跑完。验证:

- pipeline 是否打通
- simulator 行为是否符合预期(不太聪明也不太笨)
- judge 是否被 format 偏见污染(spot check 几次输出和 judge rationale)
- 三个 arm 的 cost 量级是否符合预期

Pilot 通过后,扩到 5 task / 3 run / 9 维度。再通过后,扩到 15-20 task。

---

## 13. 实现栈

| 组件 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | Anthropic SDK 一等支持,数据处理生态成熟 |
| Claude 调用 | Claude Agent SDK | 程序化调用 + 结构化 transcript + subagent spawn 可见 |
| Vanilla arm | `claude` CLI headless mode (`-p` flag) | 真实 baseline,不做任何工程 |
| Main / Mono arm | Claude Agent SDK + 指定 ShipFlow 分支 | 透出 phase / subagent 事件 |
| 数据存储 | JSON per-run + DuckDB(汇总查询) | 简单,本地,无需服务 |
| 报告渲染 | Markdown(主) + matplotlib(Pareto 图) | 易 review,易嵌入 PR |

---

## 14. 路线图

### v1(MVP — 跑通 pilot)

- [ ] Task schema 定义 + 1 个 task 写完整
- [ ] User Simulator 实现
- [ ] 三个 arm 的 invocation adapter
- [ ] Canon 一致性 deterministic check
- [ ] Critical decision coverage deterministic check
- [ ] Decision density extractor(Haiku)
- [ ] Scope Discipline check(复用 decision extractor + 四源分类)
- [ ] Question Quality 评分(Coverage deterministic + Precision via judge)
- [ ] Pairwise tournament judge
- [ ] Layer 1 + Layer 2 报告

### v2(完整版)

- [ ] 5 个 task
- [ ] 3 个 run × robustness check
- [ ] 全 9 维度
- [ ] Multi-persona ensemble
- [ ] Layer 3 representative examples
- [ ] Pareto 图
- [ ] Token anomaly detection
- [ ] Mode-specific check (Role bleed, Silos)

### 之后(待定)

- 自动 cost capture(SDK usage hook)
- Phase 边界自动检测(替代 manual phase marker)
- Human eval 校准 LLM judge
- Web dashboard

---

## 15. 诚实声明(写入 README)

> This benchmark does not measure whether designs are *good* in any absolute sense. It measures whether designs are *well-formed*: internally consistent, faithful to elicited user constraints, decision-dense rather than handwaving, traceable to premises. A high score means a system reliably produces well-formed designs; it does not mean those designs are the ones a particular user would have chosen.

中文:

> 本 benchmark 不衡量 design 在绝对意义上的「好坏」 — 那是品味问题。它衡量 design 是否 **良构**:内部自洽、忠实于用户表达的约束、决策密度高而非 handwaving、可回溯到前提。高分意味着该系统稳定地产出良构 design,不意味着那个 design 是任何具体用户会选的方案。

---

## 附录 A:决策路径速查

| 决策 | 选择 | 关键考量 |
|---|---|---|
| 是否要 baseline 对照 | 是,3-arm | 没有 baseline 没法识别 plugin 真实 lift |
| 范围到哪 | 停在 design phase | 用户实际比较场景就在这里;且避开 code 测试的额外复杂度 |
| 是否约束输出格式 | 不约束 | 真实使用场景就有差异,在 judge 反偏见条款里压制 |
| 是否假定 ground truth | 否,转 procedural | 开放任务没有唯一答案,假装有反而引入偏见 |
| Robustness 怎么测 | Deterministic decision-diff | 比 judge 便宜且更稳 |
| 怎么模拟用户 | Sonnet simulator + canon | Opus 太聪明会污染对照 |
| Judge 偏见怎么压 | 显式反偏见条款 + multi-persona ensemble | 单一 judge 偏见不可避免,多视角能稀释 |
| Vanilla 要不要工程 | **不工程** | 加了引导就不是 baseline 了 |
| 成本怎么算 | 用户手动粘 per-arm total | 真实账单,免去 SDK usage 累加复杂度 |
| 指令遵循怎么测 | 单列 Scope Discipline 维度 | Trace-ability 只抓「该有的有依据」,不抓「不该有的混进来」(over-engineering),需要互补维度 |

## 附录 B:Judge 反偏见条款(完整版,写入所有 judge prompt)

```
You are evaluating design documents. Critical guidelines:

1. Do not reward output for being more structured, longer, or having
   more headers. Reward only substantive content. A 200-word focused
   decision document beats a 2000-word document with the same decisions
   buried in scaffolding.

2. Do not reward formality of tone. A casual but precise design beats
   a formal but vague one.

3. Do not penalize an output for stating "I don't know" or "this needs
   further discussion" if those are honest assessments. Penalize ONLY
   when the document handwaves on a question it should have answered
   given the available canon.

4. When comparing outputs, focus on:
   - Did each address the same set of decisions?
   - Are decisions traceable to inputs (idea + Q&A)?
   - Are there internal contradictions?
   - Are constraints from the canon honored?
```
