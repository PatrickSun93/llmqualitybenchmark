# Design Notes — 设计讨论与方法论

> 配套 [SPEC.md](./SPEC.md) 阅读。
> Spec 讲 **what**,本文档讲 **why** 和 **what we considered and rejected**。
>
> 写给以后的自己,以及任何想从这个 benchmark 的设计过程中学到通用方法论的人。
> 后续如果要扩展到新场景(评其他 plugin、评其他 multi-agent 系统、评 RAG pipeline 等),很多决策框架可以直接复用。

---

## 0. 起点:从「想评估 plugin」到「benchmark 应该是什么」

**初始动机**:现有 LLM benchmark 大多在比 *速度* 和 *绝对正确率*。但对一个 plugin(尤其是包装在 Claude Code 上的 phase-gated 工作流)来说,这两个都不是核心问题。核心问题是:**「这个 plugin 在裸模型基础上,真的有贡献吗?贡献在哪?值多少钱?」**

这个观察决定了 benchmark 的整个走向。

---

## 1. 普遍适用的方法论(可复用到其他 eval 项目)

下面六条不是这个 benchmark 独有的,而是 **任何 LLM 工件评估** 都会遇到的设计抉择。把它们抽出来单列,以后做新 eval 可以直接套。

### 1.1 测「lift over baseline」,而非绝对分

**问题**:你测出 plugin 拿了 0.82,这说明什么?

**答案**:什么也说明不了。Opus 本身就强,plugin 可能只是借了模型的光,甚至在拖后腿。

**通用规则**:任何评估「在底层模型基础上加了一层东西」的工件,都必须有一个 *baseline arm*(裸模型 / 无加工件 / 上一版工件)在同一任务上跑一遍。报告的不是 `score(treatment)`,而是 `score(treatment) − score(baseline)`。

**应用场景**:RAG vs 无 RAG;fine-tune vs 基模;新 prompt vs 旧 prompt;A 工具 vs B 工具。

**陷阱**:不要把 baseline 工程化(给它写引导 prompt 让它表现更好) — 那就不是 baseline 了,是「baseline + 你偷偷加的辅助」。本 benchmark 的 Vanilla arm 严格保持「裸 `claude -p`」,就是这个原则。

### 1.2 程序性质量 vs 实质性质量

**问题**:Open-ended 任务(写设计、写文章、做规划)没有 ground truth,怎么打分?

**框架**:把 quality 拆成两层:

- **实质性(substantive)**:这个产出是不是好的?— 通常涉及偏好、品味,**不可靠测量**。
- **程序性(procedural)**:这个产出是不是良构的?— 内部一致、忠实于约束、决策明确、可回溯到前提。**可测量**。

**应用**:
- 设计文档评估 → 测程序性
- 代码评估 → 测程序性(类型、测试通过率)+ 实质性(代码风格,主观)
- 文章评估 → 测程序性(论点结构、引用)+ 实质性(论点质量,主观)

**关键悟**:你以为是在测「这个东西好不好」,其实多半在测「这个东西良构不良构」。承认这件事比假装不是要诚实得多,而且对架构对照实验来说,程序性指标恰恰更敏感。

### 1.3 Pairwise > 绝对打分

**问题**:1-5 分这种 absolute score 在 LLM-as-judge 里偏见极大(锚点漂移、近期偏好、长度偏好...)。

**替代**:让 judge 看两到三个候选输出,**排个序** — 不要分别打分。

**为什么有效**:Chatbot Arena、MT-Bench 等大量实证表明 pairwise 偏见显著小于 absolute。人类直觉也支持 — 比较「A 和 B 谁好」比独立判断「A 是 4 分还是 5 分」容易。

**附加优势**:多个候选放一起比,judge 一次 call 就能产出 ranking,token 比独立打分更省。

**陷阱**:候选顺序会影响判断(position bias)。补救:每个 task 的 judge call 中随机打乱候选顺序;或同一组候选跑两次 judge,正反顺序各一次,取一致性。

### 1.4 Deterministic check 优先于 LLM judge

**问题**:LLM judge 又贵又有偏见,能不动则不动。

**框架**:**任何能被 deterministic 测量的属性,都不要交给 judge。**

本 benchmark 的应用:

| 维度 | 原本可能做法 | Deterministic 替代 |
|---|---|---|
| Canon 一致性 | judge 看 design 是否兑现约束 | grep / pattern match canon 字段 |
| 决策密度 | judge 数 committed decision | extractor 分类 sentence 类型(committed / punt / fuzzy) |
| Critical decision coverage | judge 数命中关键决策 | 命中率统计 |
| Robustness | judge 比较多次输出的稳定性 | 提取 decision list,计算 set 重合度 |
| Grounding | judge 判断事实是否有依据 | 比对 transcript 是否有对应 Read tool call |

**通用规则**:每加一个新维度时,先问 *「这个能 deterministic 测吗?」* 不能再考虑 judge。

### 1.5 User Simulator + Ground Truth Canon(交互式任务的核心模式)

**问题**:任务需要多轮交互(arm 提问 → 用户回答 → arm 继续),但 benchmark 不能有真实用户。

**模式**:
1. 每个 task 有一个 *canon* — 假想用户脑子里的事实(约束、偏好、隐藏需求)
2. 一个 *user simulator*(独立 LLM)拿着 canon,arm 问什么它就根据 canon 回答
3. arm **不可见 canon**,只能通过提问获取信息

**关键工程细节**:
- **Simulator 模型不能太强**:用 Opus 当 simulator,会下意识帮 arm 把问题想透,污染对照。用 Sonnet,system prompt 显式约束「不要 infer,不要 helpful beyond canon」。
- **Canon 没覆盖时**:simulator 答「我没强偏好」「还没想好」,模拟真实用户。
- **三个 arm 必须共享同一 simulator 实例和 canon**:公平性的硬要求。
- **`max_turns` 上限**:防止 arm 无限提问把成本炸掉,同时是 Restraint 指标的隐含 cap。

**应用场景**:任何「LLM agent 与用户多轮交互」的评估都适用 — 客服 bot、代码 review bot、产品咨询 agent 等。

### 1.6 多 persona judge ensemble(主观维度兜底)

**问题**:有些维度天然主观(「架构是否优雅」「文风是否好」)。怎么办?

**模式**:用 3 个 persona 跑同一份输出。
- 三个一致 → 是 robust 优势,计入主分。
- 三个分歧 → 标注为 preference-dependent,**展示但不计入主分**。

**关键悟**:主观分歧本身也是有价值的信号 — 它告诉你这个维度上没有明确赢家,而不是假装出一个赢家。

---

## 2. 各项决策的来龙去脉

按讨论顺序记录。每条记录:**问题 → 我们的选择 → 为什么 → 拒绝的替代方案**。

### 2.1 范围:为什么停在 design phase,不进 code?

**问题**:Plugin 是个完整工作流,从 idea 到代码都管。Benchmark 要不要测整条链?

**选择**:**只测到 design phase**。

**为什么**:
- 用户告知核心比较场景就在 design 阶段,后面的 code 实现不是这个对照的兴趣点
- Code 阶段引入 *巨大的* 评估复杂度(测试用例编写、可执行环境、build 失败处理等),会冲淡架构层信号
- Design 阶段的输出更纯粹反映 reasoning 和 specialization 的差异

**拒绝的替代**:测全链路 — 太重,且语义混杂。

### 2.2 三个 arm 的来历

**问题**:对照实验的具体变量是什么?

**选择**:Vanilla / ShipFlow Main / ShipFlow Mono(三个 arm)。

**为什么**:
- ShipFlow Main 和 Mono 在 phase 编排、role 定义文件上完全相同,**唯一变量是 role 注入位置**(system prompt vs user content)。这是教科书式的受控实验。
- Vanilla 提供「不装 plugin」的自然下界,锚定 lift 的基准。

**拒绝的替代**:
- 只测 Main vs Vanilla — 测不出「specialized system prompt」是否真的产生增量
- 只测 Main vs Mono — 没有「plugin 是否值得装」的答案

### 2.3 输出格式要不要约束?

**问题**:三个 arm 输出的 design 文档结构差异巨大(Main 大概率结构化、Vanilla 可能就是几段散文),会不会让 judge 看 *外观* 而非 *实质*?

**选择**:**不约束格式**。

**为什么**:
- 约束格式 = 削弱 plugin 的格式优势(format 本身可能是 plugin 价值的一部分)
- 不约束 = 更接近真实使用场景

**怎么压偏见**:在所有 judge prompt 里写死「不要因为更结构化、更长、更多 header 就给高分」。具体见 SPEC 附录 B。

**拒绝的替代**:强制输出统一 schema(如必须含「问题 / 方案 / 备选 / 风险 / 决策」5 节)— 公平性提升不明显,且削弱了「format 是 plugin 价值一部分」的检验。

### 2.4 模式特定的失败模式 — 为什么单独测 Role bleed 和 Specialization silos

**问题**:Main 和 Mono 各自的失败模式不一样,通用维度抓不到。

**Mono 特有失败**:Role bleed / 人格漂移 — 同一 agent 跨 phase 复用 context,前一个 role 的语气和倾向会污染下一个 role。例:product-lead 的「用户视角」漏到 tech-lead 的技术决策段。

**Main 特有失败**:Specialization silos / 拼接感 — 22 个专精 agent 各自单看到位,但 tech-lead 给的方案没解决 product-lead 提的需求,逻辑断裂。

**测量**:
- Role bleed:对 Mono 输出按 phase 切片,judge 反向分类「这段听起来像哪个 role」,命中率低 = 严重
- Silos:整体内部一致性 + 反事实测试「只读 product-lead 那段,tech-lead 方案能闭环吗?」

**为什么这两条最有信息量**:它们直接对应「specialized system prompt 是否有实证价值」这个核心实验问题。如果 Mono role bleed 严重 + Main silos 不严重 → 专精架构胜。反之则相反。

### 2.5 关于「开放问题」:如何评估有歧义的 idea?

**问题**:用户给一个开放的 idea(「我想做个习惯追踪 app」),不同合理的人会问出不同的澄清问题、给出不同的 design。怎么评?

**选择**:把交互建模进 benchmark — User Simulator + Canon 模式(见 1.5)。把「提问质量」单列为评估维度。

**为什么不直接给完整需求**:那就退化成普通的「按 spec 写 design」任务,丢失了 plugin 在 *需求挖掘* 上的核心价值。多 agent 工作流(如 product-lead 角色)的核心 lift 之一就是「先问清楚再做」。

**Question Quality 单列的理由**:它是 phase-gated workflow 最有特色的一环,合并进 instruction-following 或 phase fidelity 会丢信号。它可能也是整个 benchmark **信噪比最高**的维度 — 提问质量比 design 输出质量更难靠后续 phase 救回来。

### 2.6 关于「没有 ground truth」:Procedural quality 转向

**问题**:开放任务下,「这个 design 是对的」是个伪命题(每个用户偏好不同)。那评分凭什么?

**选择**:把目标从 *「哪个 arm 给出最好的 design」* 改成 *「哪个 arm 系统性地给出更良构的 design」*。前者品味问题,后者可测属性。

**关键悟**:你以为你想测 substantive,其实你能测的只有 procedural,而且对于架构对照来说 procedural 反而更敏感 — 因为它直接反映系统层面的「能力」,而不是个例的运气。

**对应 6 个程序性维度**(见 SPEC §5.1):Canon 一致性、内部一致性、决策密度、Trace-ability、Critical decision coverage、Scope Discipline。

**主观维度**(架构优雅性等):用 multi-persona ensemble,一致就计分,分歧就标注但不计主分。

### 2.7 Robustness:用 deterministic 而非 judge

**问题**:同一 idea 跑 N 次,arm 输出有多稳?直觉做法:让 judge 比较 N 次输出。

**问题的问题**:N 次输出 × judge call,贵且噪。

**替代**:
- 每次输出 extract decision list(「我们用 Postgres」「部署到 Vercel」...这些的列表)
- 计算 N 次之间 decision list 的集合重合率
- 完全 deterministic,不动 judge

**附加好处**:这个一致率本身就是「系统是否在产出稳定 reasoning」的硬指标。

**只在主轴上跑**:不需要 8 维度都 ×3,只在 Canon 一致性、决策密度上跑就够。

### 2.8 关于 Vanilla arm:越裸越好

**问题**:Vanilla 不会主动按 phase 走、可能不问问题就直接出 design。要不要给它一个最低限度的引导 prompt 让对照「公平」?

**选择**:**不给**。Vanilla = `claude -p "<idea 原文>"`,不加任何引导。

**唯一可接受的补偿**:告诉它「请只输出 design 文档,不要写代码」 — 因为 benchmark 范围只到 design,不能让 Vanilla 跑去写代码导致输出不可比。

**为什么严格**:加了引导就不是 baseline 了,是「baseline + 你偷偷加的辅助」。如果 Vanilla 不问问题就输出 design,**这件事本身就是结论** — Question Quality 那项拿 0 分是 it deserves 的。

**这是反直觉但关键的原则**:不要为了「让对照看起来公平」就工程化你的 baseline。Baseline 的意义就在于「真实用户没装 plugin 时会得到什么」。

### 2.9 指令遵循:差点漏掉的维度

**问题**:用户最初列出的四大维度里有「Instruction-following」。在向 procedural quality 转向时,我下意识把它「分散」进了 Canon 一致性、Trace-ability、Critical decision coverage 三个维度,觉得已经覆盖了。

**用户审 spec 时抓到了**:仔细一看,有一类失败模式仍然漏网 ——

> idea 说「习惯追踪 app」,canon 没说要 onboarding。design 提案变成「habit tracker + AI coach + 社区 + onboarding 流程 + 付费墙 ...」。

这些「多出来」的功能 *可以* trace 到「一般产品最佳实践」,所以 Trace-ability 不会扣分。但 **idea / canon / Q&A 都没要求它们**。这正是 over-engineering 的典型形态。

**为什么这是 Main 特有的失败模式风险**:22 个 specialized agent 各自「在自己领域尽职」,合起来必然倾向于「把所有最佳实践都加上」。这是 specialization 的代价之一。**如果不专门测,benchmark 等于装作看不见这个真实弱点**,有 pro-Main 偏向。

**选择**:加 Scope Discipline 作为第 6 个程序性维度(总维度从 8 → 9)。

**测量**:复用 decision extractor 抽决策,然后对每个决策做四源分类(idea / canon / must_be_addressed / Q&A 主动确认)。都不是 → unrequested。Unrequested 占比 = 反向 Scope Discipline 分。

**学到的元教训**:
- 转换框架(从「绝对评分」到「procedural」)时,**容易丢掉一些原本想测的东西**,而且因为新框架自洽,丢失感不强烈。需要回头核对原始需求清单。
- 维度之间的「互补性」很重要 — Trace-ability 看「该有的有依据」,Scope Discipline 看「不该有的没混进来」,两者必须配对,只有一个不完整。

### 2.10 公平性:Vanilla 在 Q&A-Mediated 维度上的结构性歧视

**问题(用户实测时发现)**:跑出第一份报告会注意到,Vanilla 在 Canon 一致性、Critical decision coverage、Question Quality 这几个维度上得分远低于 ShipFlow。**初看像是 plugin 大胜,但其实是 rubric 设计的副作用**:

- Vanilla 不会主动问问题(没有 phase-gated workflow 推它)
- 不问就不知道 canon 约束(讨厌游戏化、预算上限...)
- 不知道约束 → Canon 一致性低
- 没 Q&A → Question Quality coverage = 0

**这是循环论证**:rubric 把「会做 Q&A」编码成「质量好」,然后比较「会做 Q&A 的 plugin」和「不会做 Q&A 的 baseline」,得出「plugin 质量更好」的结论。这是 tautology,不是 finding。

**修复 — 三层叠加**:

1. **加第 4 个 arm `vanilla-with-canon`** 作为公平基线 — 把 canon 直接注入 user message,模拟「假如 Vanilla 有完美 Q&A 能力」。这把「Q&A 这件事本身值多少」从「多 agent 编排值多少」分离开。

2. **报告分组** — 维度分成 Intrinsic(全员公平)和 Q&A-Mediated(用 vanilla-with-canon 做 baseline 而非 vanilla)。**不合并总分**,免得把两类质量混淆。

3. **N/A 语义** — 不适用于某 arm 的维度(如 Question Quality 给没 Q&A 的 arm)返回 `None`,从聚合和排名中排除,不悄悄打 0 分。

**修复后的结论格式更诚实**:
- `vanilla → vanilla-with-canon` 的 lift = Q&A 这件事的价值,与 plugin 选择无关
- `vanilla-with-canon → main` 的 lift = **多 agent 编排在同等 context 下的真实价值**(这才是你想测的)
- `main vs mono` = specialized vs role-as-content 的纯架构差异

**学到的元教训**:
- **「baseline 在所有维度上都该公平」是错的认识**。有些维度的设计会intrinsic 地依赖某 arm 的能力。这种维度不该用全局 baseline,而该有该维度自己的公平基线。
- **N/A 不是 0**。把「没做这事」编码成「做得差」是常见的 silent bias,需要显式处理。
- **Tautology 是 benchmark 设计最隐蔽的 failure mode**。当 rubric 跟其中一个 arm 的设计哲学高度一致时,要警惕「这是发现还是循环论证」。

### 2.11 成本数据:用真实账单,不要估

**问题**:每个 task 多少 token / 多少钱?

**最初想法**:harness 在每次 SDK call 后捕获 `usage` 字段,自动累加。

**简化后选择**:用户手动粘 per-arm 总账单(Claude Code session `/cost` 命令直接出),harness 不做 cost capture。

**为什么简化**:
- 实现成本几乎为零
- per-arm total 已经够算 Pareto 图、cost-adjusted lift 等所有 top-level 指标
- 真实账单 > 自己累加的估算

**牺牲了什么**:per-phase 粒度的诊断(如「Mono design phase 反常烧 token = role bleed 副作用」)。如果以后想要这个,再加 SDK usage hook。

---

## 3. 失败模式:我们在防什么

罗列 benchmark 设计中的几个常见陷阱,以及本 benchmark 是怎么防的。

| 陷阱 | 怎么防 |
|---|---|
| **结果是模型的功劳,不是 plugin 的** | Vanilla baseline arm + lift 计量 |
| **Judge 偏好长 / 结构化 / 正式的输出** | 显式反偏见条款写入所有 judge prompt |
| **Simulator 比真实用户更聪明,污染对照** | Simulator 用 Sonnet 而非 Opus,system prompt 显式约束「不要 infer」 |
| **Robustness 测量本身贵又不稳** | Deterministic decision-set diff 替代 judge |
| **架构假设找证据偏好** | 设计 mode-specific 失败模式 check(Role bleed / Silos),让两种架构都有暴露弱点的机会 |
| **单 task 的偶然结果当系统结论** | 至少 15-20 task,带置信区间;单 task 只能进 representative examples |
| **假装有 ground truth** | 明确转向 procedural quality,在 README 写 honest disclaimer |
| **Baseline 被工程化** | Vanilla 严格 `claude -p`,只加「输出 design 不写 code」的最小补偿 |
| **格式偏见** | Judge 反偏见条款 + 不约束输出格式,让公平性靠 judge 教育而非格式约束 |

---

## 4. 可扩展的方向(后续学习入口)

每条都是一个独立的小项目,做完能学到对应方向的实质内容。

### 4.1 Phase 边界自动检测

**当前**:依赖 transcript 里的 phase marker(skill 自己 emit `[PHASE: research]` 之类)。

**扩展**:从 agent spawn / tool call 序列里自动推断 phase 转换。涉及 trace pattern matching、可能要做小模型分类器。

### 4.2 Human eval 校准 LLM judge

**当前**:全靠 LLM judge,且我们承认有偏见。

**扩展**:用人类对小批量(20-30 个 pairwise 对比)打分,用 Cohen's kappa 或 Pearson 相关系数衡量 LLM judge 与人类的一致性。如果某维度 judge 与人类 < 0.5,说明这个维度不可靠,要么改 rubric 要么去掉。

**学到什么**:Judge calibration 是 eval 工程的核心问题之一。

### 4.3 自动 cost capture(SDK usage hook)

**当前**:用户手动粘账单。

**扩展**:在 SDK call wrapper 里 hook usage,per-phase 累加,自动生成 cost 表。除了省事,还能拿到 per-phase 粒度,做更细的诊断(如检测 token anomaly)。

### 4.4 把 benchmark 套到其他 plugin

**当前**:针对 ShipFlow 的 Main vs Mono 对照。

**扩展**:把 task spec、judge rubric、维度定义都抽出 plugin-agnostic,让任何 phase-gated 工作流 plugin 都能套。这本身就是个好的开源工具。

### 4.5 把方法套到非 design 任务

**当前**:停在 design phase。

**扩展**:把 procedural quality + simulator + pairwise 那套搬到 *写代码* 任务上。挑战在于怎么把「程序性质量」对应到代码上(类型、测试、风格、grounding 到 spec)。涉及静态分析 + LLM judge 混合。

### 4.6 多轮 design 改进

**当前**:single-shot,arm 出 design 就结束。

**扩展**:让 simulator 在看完 design 后给反馈,arm 可以改一版。测的是 *recovery* 能力。这一维度对 multi-agent workflow 尤其重要(单 agent 改 design 容易,多 agent 协调改 design 难)。

---

## 5. 参考与延伸阅读(非穷举)

### Eval 方法论
- **Chatbot Arena**(LMSYS):pairwise 大规模人类偏好,本 benchmark 的 judge 策略受其启发
- **MT-Bench**:LLM-as-judge 多维度,对 rubric 写法有参考价值
- **HELM**(Stanford):多指标 holistic eval,多维度报告思路
- **AlpacaEval**:pairwise 对固定 baseline,固定 baseline 的概念有价值
- **G-Eval / G-Eval-PT**:LLM-as-judge 的 calibration 方法

### Benchmark 设计中的常见问题
- **Position bias / verbosity bias / familiarity bias**:LLM judge 的系统性偏见
- **Holistic Evaluation 的 disclaimer 文化**:HELM、BIG-Bench 的报告里都有「this is not a proxy for X」式声明,本 benchmark 的诚实声明跟这个传统一脉相承

### Multi-agent specific
- 多 agent 的 evaluation 还相对年轻,SWE-agent、AutoGen、CrewAI 等系统的 eval 实践可以借鉴

### 软件工程
- **Architecture Decision Records (ADRs)**:本文档结构受 ADR 启发,「问题 / 选择 / 为什么 / 拒绝的替代」是核心模式

---

## 6. 一些 meta 反思(可选阅读)

### 这次设计过程的几个有用习惯

1. **始终问「这个能 deterministic 测吗」** — 每次想拉 LLM judge 上,先停一下,看能不能用 pattern match / 计数 / 静态分析替代。能,就用。
2. **「为什么这个不该测」是好问题** — 砍掉 latency、UI、并发、CI 这些范围,benchmark 才能聚焦在自己宣称的事(quality)上。
3. **承认无法测量的东西** — 实质性 quality 测不了就别测,与其假装有 ground truth,不如写诚实声明。
4. **从受控实验角度看对照** — 三个 arm 不是随便挑的,Main vs Mono 严格只差 role 注入位置,这是教科书式的 single-variable 设计。这种严格性在 LLM eval 里其实少见。
5. **Failure mode 驱动的 metric 设计** — Role bleed / Silos 不是凭空想出来的维度,是「Mono 这种架构理论上会怎么坏」「Main 这种架构理论上会怎么坏」推导出来的。先想 failure mode,再设计 metric 去检测它,而不是先 metric 后找用法。

### 后续做新 eval 时,把这份当 checklist

- 我有 baseline arm 吗?
- 我在测程序性还是实质性?搞清楚
- 能 deterministic 就别 judge
- Judge 用 pairwise 不用 absolute
- 主观维度用 multi-persona 兜底
- Baseline 不要工程化
- 单 task 不能下结论,看分布
- 写 honest disclaimer

---

## 7. 待办与开放问题

这些是 spec 阶段没拍板,留到 build 阶段再决定的:

- [ ] **Phase marker 机制**:让 ShipFlow 主动 emit 还是从 transcript 推断?(spec §13 隐含选了前者,但留可能性)
- [ ] **Decision extractor 的具体 prompt**:Haiku 的 prompt 怎么写才能稳定区分 committed / punt / fuzzy?需要手动标几个例子做 few-shot
- [ ] **Critical decision matching 的 fuzzy 程度**:如果 design 用「JWT 认证」回答了「认证方案」,exact match 会漏 — 是用 embedding 相似度还是 LLM-aided match?
- [ ] **置信区间怎么算**:小样本下标准 CI 不够稳,可能要 bootstrap
- [ ] **Pilot 的 success criteria**:跑通 pipeline 之外,还要看什么数据才算 pilot 成功?
- [ ] **多 persona judge 的 persona 究竟怎么写**:「产品向」「工程向」「保守 ops 向」需要具体 prompt

这些都不影响 spec 的整体结构,build 时再细化。
