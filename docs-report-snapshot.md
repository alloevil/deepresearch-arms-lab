# 非训练方式实践 Deep Research 的技术调研报告

**日期**：2026-07-02
**调研范围**：2026 年发表的 deep research agent 相关论文（精读 10 篇）及主流开源项目
**约束条件**：无模型训练资源（不做 RL/SFT），仅通过推理时方法（prompt、架构、编排）实践
**目标场景**：长报告生成（对齐 OpenAI/Gemini Deep Research 产品形态）

---

## 摘要

Deep research agent 领域在 2026 年的研究主线已转向强化学习训练专用模型，但多项工作的消融实验独立证明：**推理时的外部结构设计（多 agent 编排、显式状态管理、验证机制、终止控制）在不修改模型权重的前提下，可带来 8–10 分量级的能力提升，部分系统超过商业 Deep Research 产品**。本报告将现有非训练方法归纳为四类技术路线（并行探索与验证选择、显式外部状态管理、任务委派与上下文隔离、prompt 自动优化），对 10 篇代表性论文进行综述与对比。针对长报告生成这一目标场景，选型结论为：**以 VeriTrace（认知图 + 三条显式调控回路）为目标方法，以 ScaffoldAgent（大纲树 + 效用引导）为低成本起步实现，以 EDR 的终止判据机制为必装组件**，并配套防污染评测方案。

---

## 1. 背景与目标

### 1.1 领域现状

Deep research 指 agent 在开放信息空间中进行长程探索（规划—检索—阅读—综合），最终产出有据可依的答案或报告。OpenAI Deep Research、Gemini Deep Research 等商业产品定义了这一任务形态，但均为闭源。

2026 年学术界的研究重心分布：

| 主线 | 代表工作 | 是否需要训练 |
|---|---|---|
| RL/SFT 训练专用模型 | QUEST、DEEPRUBRIC、MetaResearcher、LiteResearcher | 是（本报告排除） |
| 推理时架构与编排 | VeriTrace、ScaffoldAgent、AgentDisCo、EDR、FineVerify | 否 |
| 委派与上下文管理 | SearchSwarm、Argus | 部分（编排层免训练） |
| 评测与可信性 | Search-Time Contamination、LiveBrowseComp | 否 |

### 1.2 报告目标

在无训练资源的约束下：
1. 梳理非训练方法的技术路线，回答"不训练时能力从哪来";
2. 综述 2026 年代表性方法，识别长报告场景下能力最强的可实践方法;
3. 给出具体实践路线与评测方案。

### 1.3 核心可行性论据

非训练路线并非退而求其次，以下为各论文报告的实验证据（均为 2026 年发表，注明出处与发表时间）：

- **纯编排层即可 +10 分**：SearchSwarm（清华/北大/蚂蚁，arXiv:2606.09730，2026 年 6 月）的消融实验：对强基座模型 DeepSeek V3.2 仅施加委派编排（纯 prompt，不训练），BrowseComp 从 47.7 提升至 57.7（+10.0），其中 prompt 设计原则贡献 +7.7；
- **一段终止判据 prompt 换 +8.4 分**：EDR（Salesforce，arXiv:2604.24978，2026 年 4 月）的消融实验：仅增加"执行前预声明终止判据"机制，HAA 指标下降对照显示该单项贡献 8.4 分；
- **零训练验证机制超过 frontier 模型**：FineVerify（NUS，arXiv:2606.00660，2026 年 5 月）：候选验证选择机制使 GPT-5-mini 在 12 样本下达到 67.5%，超过 frontier GPT-5 单次作答的 67.0%（BrowseComp-Plus）；
- **架构优势可压过基座差距**：VeriTrace（Cambridge，arXiv:2605.26081，2026 年 5 月）：同基座重跑对比中胜过所有同类架构；其 DeepSeek 配置在 DeepResearch Bench 达 55.77，超过使用更强基座 Claude-Sonnet-4.5 的竞品系统 FS-Researcher（53.94）；
- **自动优化 prompt 超过专家手工调参**：Self-Optimizing MAS（Zeta Alpha，arXiv:2604.02988，2026 年 4 月）：GEPA 算法从一行极简 prompt 自动优化至 0.705，超过专家一年打磨的生产 prompt（0.667，ScholarQA-CS）。

同时存在一条反面约束：SearchSwarm 发现**弱基座模型不会自发使用委派工具**——非训练路线必须搭配足够强的基座模型，外部结构无法替代基座的 agentic 基础能力。

---

## 2. 概念框架：不训练时，能力从哪来

### 2.1 问题分解

Deep research 的失败模式可归为三类：

1. **找不全**（覆盖失败）：探索不充分，证据有缺口；
2. **装不下**（状态失败）：证据超出上下文窗口，或中间状态被低质量信息污染、错误沿依赖传播；
3. **停不对**（判断失败）：缺少"何时算完成"的显式标准，导致过早停止或无效空转。

训练路线将应对行为压入模型权重；非训练路线的核心假设是：**强基座已具备原料能力（会搜、会读、会判断），缺的是组织这些能力的外部结构**。梳理 2026 年的代表性工作，现有非训练方法可归纳为四类技术路线；它们作用于不同环节、相互独立，可以组合使用。

### 2.2 路线一：并行探索 + 验证选择

**机制**：同一问题跑 K 条独立轨迹，通过验证机制选出正确答案或组装互补证据。核心难点在聚合：majority voting 对稀疏正确答案失效；拼接全部轨迹会撑爆聚合器上下文。

**代表**：FineVerify（分解为子问题逐条三值核查）、Argus（DAG 证据图 + 缺口驱动派发）。

**上限**：受限于单次探索的召回——K 条轨迹都未触及的信息无法通过验证产生。提升的是答案正确率，而非探索深度。

**适用**：短答案、唯一 ground truth 任务（BrowseComp 类）。**对本报告的长报告场景收益不直接**，但其验证配方可用于报告的引用核查环节。

### 2.3 路线二：显式外部状态管理

**机制**：将"研究进行到哪了"从 LLM 隐式上下文中取出，外化为显式数据结构（大纲树、证据库、认知图），由固定规则维护：新证据如何合并、矛盾如何记录、缺口如何补齐、结构何时重组。

**代表**：ScaffoldAgent（大纲树 + UCB 效用选点）、VeriTrace（认知图 + 三条调控回路）、AgentDisCo（blueprint + document bank）。

**上限**：状态结构的表达力与维护规则的质量。

**适用**：长报告、开放式任务（DeepResearch Bench 类）——**正是本报告的目标场景**。长报告区别于短答案深搜的本质，就在于中间状态（研究进度、证据组织、章节结构）必须跨越远超上下文窗口的探索过程而不丢失、不腐化。

### 2.4 路线三：任务委派 + 上下文隔离

**机制**：主 agent 将"token 昂贵但认知浅"的信息收集委派给子 agent；子 agent 在独立上下文执行，仅回传压缩报告。等价于为系统引入内存分页。

**代表**：SearchSwarm 编排层（call_sub_agent + 详尽 brief + 引用锚定）、EDR（Plan DAG + 依赖门控：每步仅接收依赖步骤输出）。

**上限**：主 agent 的委派判断力。该路线对基座强度最敏感（强模型 +10 分，弱模型完全不使用委派工具）。

**适用**：横向宽（多独立子主题）的任务。与路线二互补：路线二管纵向状态积累，路线三管横向任务分工——长报告场景两者都需要。

### 2.5 路线四：prompt 自动优化

**机制**：前三条路线均由 prompt 实现，而手写 prompt 脆弱且不可迁移。用 LLM 依据评分与执行轨迹迭代改写系统内各角色的 prompt（GEPA 遗传优化 / Claude-Code 外层优化器）。

**代表**：Self-Optimizing MAS、AgentDisCo meta-harness。

**定位**：非独立方法，是前三条路线的放大器；换基座/换领域时可自动重新适配。

---

## 3. 文献综述

### 3.1 方法总览

| 论文 (arXiv, 发表时间) | 所用方法 | 免训练 | 每题成本 | 关键结果 |
|---|---|---|---|---|
| FineVerify (2606.00660, 2026-05) | 候选分解核查与选择 | ✅ | <$0.8 | 4样本 +8.2 分；12样本超 GPT-5 |
| Argus (2605.16217, 2026-05) | 并行搜索 + DAG 证据图聚合 | ❌（调度器需 SFT+GRPO） | 25.6M token (K=64) | BrowseComp 55→86.2；架构思想可借鉴 |
| ScaffoldAgent (2606.20122, 2026-06) | 大纲树 + UCB 效用选点 | ✅ | 26.3k token / 117s | RACE +2.24；成本最低 |
| VeriTrace (2605.26081, 2026-05) | 认知图 + 三条显式调控回路 | ✅ | $0.6–2 / 40–65min | 同基座全胜；DRB 55.77 开源可复现最强 |
| AgentDisCo (2605.11732, 2026-05) | Critic/Generator 解耦 + 证据库 | ✅ | 未报告 | RACE 51.44 超 Gemini-DR 官方产品 |
| EDR (2604.24978, 2026-04) | Plan DAG + 预声明终止判据 | ✅ | 未报token | 终止判据单项 +8.4；DAG 提速 4.7× |
| Self-Optimizing MAS (2604.02988, 2026-04) | GEPA 自动优化各角色 prompt | ✅ | $50/优化轮 | 自动优化超专家 prompt |
| SearchSwarm (2606.09730, 2026-06) | 子 agent 委派 + 上下文隔离 | ⚠️ 编排层免训练 | 高 | 编排层纯推理时 +10 分 |
| Search-Time Contamination (2606.05241, 2026-06) | 三级搜索污染检测 | ✅ | $221/6800题 | 答案泄漏使准确率 7.7%→89.7% |
| LiveBrowseComp (2605.28721, 2026-05) | 闭卷基线 + 证据屏蔽诊断 | ✅ | — | 证据屏蔽后全员 26.1→6.2 |

### 3.2 并行探索与验证选择

**FineVerify**（NUS，2026-05）提出 propose-verify 框架：verifier 将问题分解为 m 个可核查子问题（全体候选共用，保证跨候选可比），对每个候选逐条检索证据给出三值判断 {supported, not_found, contradicted}，规则映射打分后选最高分候选，满分早停、重复候选缓存复用。GPT-5-mini 4 样本平均 59.2→67.4；BrowseComp-Plus 上 1→16 样本 49.5%→70.0%，而各 baseline 在 12–16 样本处饱和。关键发现："生成弱 ≠ 验证弱"（Pass@1 仅 45% 的设置下选择准确率达 80.3%）。缺陷：验证信号不反馈给生成，缺口信息未引导下一轮搜索。

**Argus**（MiroMind，2026-05）以共享 DAG 证据图为聚合中介：Navigator 将并行 Searcher 的轨迹解析入图（证据节点 URL 去重、claim 节点、support/contradict 边），针对"未验证/矛盾/未覆盖"三类缺口定向派发验证查询，合成时清空工作上下文仅读图的紧凑视图（1200:1 压缩）。K=64 时 BrowseComp 达 86.2% 且未饱和。**注意：Navigator 经 SFT+GRPO 训练（64×H200），本报告仅借鉴其架构思想**（证据图、缺口驱动派发）；纯 prompt 复现的效果保留度论文未验证。

### 3.3 显式外部状态管理

**ScaffoldAgent**（北大，2026-06）将大纲树同时用作写作计划和证据索引，每节点带效用统计。核心循环：UCB 选点（优先修低效用节点、兼顾探索）→ 三操作选一（Expansion 拆分 / Contraction 合并 / Revision 刷新）→ 三分量效用回填（检索效用：embedding 相关性+新颖度；结构效用：连贯+平衡−冗余；生成效用：**试写**后 NLI claim 支撑率+覆盖度）→ 边际效用 < ε 终止。消融显示去 Revision 掉 5.18 分、仅留 Expansion 会大纲无限膨胀不终止。每题仅 26.3k token，比同类省 29–49%。工程上仅需 LLM API + 搜索 API + embedding + 可选小型 NLI 模型。

**VeriTrace**（Cambridge，2026-05）是显式状态管理的最完整形态。将中间层建模为认知图（节点=概念，带验收准则、UNKNOWN/PARTIAL/KNOWN 状态、CRAAP 质量分；边=探究关系），四角色（Planner/并行 Searcher/Reader/Manager）围绕共享图协作，三条显式调控回路：
1. **解释性更新**：新发现分类为满足准则/冗余/矛盾/意外，结构化折叠入节点；
2. **偏差反馈**：四维偏差信号（相关性、可信度、可达性、意外强度）路由到五种搜索策略 {SUBSTITUTE, EXPLOIT, VERIFY, PIVOT, EXPLORE}；
3. **图式修订**：矛盾累积触发五种结构操作，受两条不变式保护（证据只增不删、用户维度不可删）。

证据以原文引文+URL 机械式入库（不经 LLM 二次加工），根治引用漂移。同 27B 基座下超所有重跑的同类架构（WebWeaver、EnterpriseDR、FS-Researcher），Insight 维度 +4.22 pp；消融揭示机制间的互补性：去偏差反馈则搜索量膨胀 1.31×，去解释性更新则系统"以为存满了"提前收工（搜索萎缩至 0.42×）。重要教训：**小模型下图结构比平铺列表更脆（错误沿依赖级联），必须配修复机制才能兑现图的优势**。

**AgentDisCo**（小红书，2026-05）将探索与利用解耦为 Critic（评大纲、输出 blueprint：要点+针对性查询组）与 Generator（执行检索、修订大纲）的交替循环，辅以 document bank（证据片段化、并行打分、跨轮索引）。RACE 51.44 超 Gemini-2.5-Pro-DeepResearch 官方产品（49.71），引用准确率 89.06（+10.7）。其外层优化器用 Claude-Code 自动迭代搜索策略并自发构建 policy bank，验证了"便宜的中间指标（Search Coverage）与端到端分数正相关"，可用于低成本迭代。

### 3.4 任务委派与信息流控制

**EDR**（Salesforce，2026-04）三机制对应三类失败模式：① 检索前先出大纲并反思（防检索分布带偏方向）；② Plan DAG + 依赖门控（每步仅接收依赖步骤输出，无依赖步骤并行）；③ **预声明终止判据**：每个 agent 执行前先声明"须收集到哪些具体信息才算完成"，循环取证自评直至满足。消融为全 10 篇最扎实：去终止判据 HAA −8.4（工具调用 327→224，行为学证实早停）；去 DAG HAA −5.7 且耗时 47→222 分钟。附带发现：固定模板任务上 GPT-4.1 反超 GPT-5.1——强推理模型在受约束任务上会"画蛇添足"。

**SearchSwarm**（清华/北大/蚂蚁，2026-06）的核心概念是**委派智能**：分解任务、决定何时委派什么、整合回传结果的能力。其编排层四原则（免训练部分）：鼓励委派、**详尽 brief**（把子 agent 当"刚加入调查的新同事"：任务+理由+已确认+不确定+已排除方向）、主 agent 保留核心判断、引用锚定报告（主 agent 可沿 URL 验证子结论）。消融证明纯编排层对强基座 +10 分。其 SFT 部分（将委派行为蒸馏进 30B 小模型）超出本报告约束，不采用。附录 B 开源了主/子 agent 全量 system prompt，可直接复用。

### 3.5 prompt 自动优化

**Self-Optimizing MAS**（Zeta Alpha，2026-04）将四角色流水线（Orchestrator/Reader/Aggregator/Writer）的 system prompt 视为可优化参数，用 29 条带专家 rubric 的查询驱动 LLM 迭代改写。GEPA（遗传+Pareto 前沿采样）显著优于 TextGrad 贪心：极简 prompt 0.513→0.705，超过专家一年打磨的 0.667。两个实操结论：meta-prompt 必须任务定制（默认 0.685 → 定制 0.705，附录提供 DR 任务模板）；对已经很强的 prompt 收益递减（+0.005），适合冷启动而非精调。风险：LLM-as-judge 有偏，优化可能在"讨好 judge"。

### 3.6 评测与可信性

**Search-Time Contamination**（NTU/阿里，2026-06）定义三级污染：BML（URL 暴露 benchmark 托管站，正则检测）→ QCL（页面含原题措辞，归一化 LCS 检测）→ EAL（原题+答案同页，LLM-judge 检测，人工校验精确率 94.85–100%）。用时变 Cox 模型量化：EAL 发生前后准确率 7.69%→89.74%（HR 2.20–8.92）；**BML 单独不构成污染受益（HR 多 <1），推翻了前人仅凭仓库 URL 匹配的检测结论**；QCL 显著催化后续 EAL。商业系统实测：Gemini Deep Research 在 MedQA 上泄漏率 60%；受限检索源也不安全（Valyu 在 PubMedQA 上 65–78%），风险本质是检索语料与 benchmark 来源语料的重叠。

**LiveBrowseComp**（哈工大/小红书，2026-05）揭示比污染更隐蔽的**内在知识依赖（IKD）**：静态榜高分可能是"参数化知识先猜答案、搜索只做验证"。三个诊断实验：闭卷 pass@4（静态榜平均 38.9 分——不搜也能拿近半分）；证据屏蔽搜索（剔除 gold 文档后全员 26.1→6.2，**搜不到支持证据时搜索比不搜更差**）；轨迹溯源（>50% 查询由模型自生假设驱动；**检索到关键证据后使用率不足 1/3**）。其 335 题时效性评测集（答案依赖 90 天内事实）将闭卷分数压到 <2%，模型排名大幅洗牌，而人类求解率与静态榜一致——证明掉分纯粹来自去除记忆捷径。

### 3.7 领域共识（多篇独立收敛的设计）

1. **显式中间表示 + 显式完成判据**：blueprint（AgentDisCo）≈ 大纲子问题+终止判据（EDR）≈ 大纲树（ScaffoldAgent）≈ 认知图（VeriTrace）；
2. **验证比生成容易**：FineVerify 与 Argus 共同押注，且有实证；
3. **上下文隔离**：子 agent 只见 brief（SearchSwarm）≈ DAG 步骤只见依赖输出（EDR）；
4. **机器优化替代人工调 prompt**：GEPA 与 Claude-Code 外层优化器殊途同归。

---

## 4. 方案选型

### 4.1 目标场景确定主路线

本报告的目标场景是**长报告生成**：能力定义为报告的全面性、洞见深度与引用可靠性，主评测为 DeepResearch Bench（RACE+FACT）类 benchmark。

该场景下的主路线是**显式外部状态管理**（路线二）：长报告的探索过程远超上下文窗口，中间状态（研究进度、证据组织、章节结构）必须外化才能不丢失、不腐化；相关方法（VeriTrace、ScaffoldAgent、AgentDisCo）也全部以长报告 benchmark 为主战场并取得最强结果。

其余路线的定位：任务委派（路线三）与主路线互补，其信息流控制机制（EDR）直接吸收；并行验证（路线一）面向短答案任务，仅其验证配方用于引用核查环节；prompt 自动优化（路线四）作为后期放大器。

（附注：若未来场景转向短答案深搜（BrowseComp 类），主路线应换为任务委派——SearchSwarm 编排层是该场景下单方法增益最大的非训练方法（+10 分），可叠加 FineVerify（+8 分）。）

### 4.2 选型结论

**目标方法：VeriTrace**。理由：
1. **能力最强**：非训练系统中同基座对比全胜（DeepConsult 胜率 81.1%），DeepSeek 配置为可复现开源系统的最高纪录（DRB 55.77），且超过使用更强基座的竞品——证明其架构增益真实；
2. **机制可解释**：三条调控回路各有独立消融，"为什么有效"有明确答案，便于报告论证与逐步复现；
3. **完全符合约束**：纯提示词驱动，成本 $0.6–2/题。

**起步实现：ScaffoldAgent 骨架**。理由：成本低一个数量级（26.3k token vs 数百万 token/题）、机制极简（UCB 选点几十行代码 + 三操作 + 边际效用终止），适合先跑通全流程建立 baseline。其大纲树可视为 VeriTrace 认知图的退化形态（无横向边、标量效用替代多维信号），升级路径自然。

**必装组件：EDR 终止判据**（一段 prompt 换 8.4 分，与任何架构兼容）。

**不选的方案及原因**：
- SearchSwarm 编排层：面向短答案深搜，与长报告目标不匹配；其"详尽 brief""引用锚定"原则作为通用工程实践吸收；
- FineVerify：面向唯一 ground truth 的候选选择，不直接适配长报告；其"分解-三值核查"配方可用于报告的引用验证环节；
- Argus：核心组件依赖训练，纯 prompt 复现效果无证据；仅借鉴证据图与缺口派发思想；
- AgentDisCo：能力弱于 VeriTrace（同基座量级下 RACE 51.44 vs 52.28，且 VeriTrace 消融更完整），自评 reward 存在自我偏好风险；document bank 设计作为备选插件。

### 4.3 基座模型要求

必须使用强基座（SearchSwarm 的反面证据：弱模型不会执行复杂编排指令）。候选：DeepSeek-V4 系（VeriTrace 验证过）、Qwen3.5-27B+ 级（VeriTrace 的低成本配置）、或商业 API（GPT/Claude/Gemini）。VeriTrace 的角色分层用法可控成本：强模型做 Planner/Searcher/Writer，快模型做 Manager/Reader。

---

## 5. 实践路线

### 阶段一：跑通 baseline（1–2 周）

1. 实现 ScaffoldAgent 骨架：大纲树数据结构 + UCB 选点 + Expansion/Contraction/Revision 三操作 + 三分量效用（embedding 相关性/新颖度可直接调 API；NLI 可用 LLM 兜底）+ 边际效用终止；
2. 接入搜索（Serper/Tavily/Bocha）与网页抽取（Jina）；
3. 叠加 EDR 终止判据 prompt 与"先大纲后检索 + reflection"；
4. 在 DeepResearch Bench 抽样 20–30 题建立 baseline 分数。

### 阶段二：逐机制升级至 VeriTrace（3–4 周）

按消融贡献从大到小逐个添加，**每加一个机制跑一次对比**（该递增消融过程本身构成报告的核心实验章节）：
1. 机械证据溯源（原文引文+URL 旁路入库）——解决引用漂移，实现成本最低；
2. 偏差反馈路由（相关性×可信度二维打分 → VERIFY/PIVOT/EXPLOIT 等五策略）——消融显示同时省搜索、提质量；
3. 解释性更新（新发现分类折叠 + 矛盾/意外显式记录）；
4. 图式修订 + 两条结构不变式——注意 VeriTrace 教训：不配修复机制则图结构在小模型下反而更脆。

### 阶段三：自动调优与扩展（可选，2 周）

1. 用 GEPA 优化全系统 prompt（需准备 ~30 条带 rubric 的查询，$50/轮）；
2. 可选插件：FineVerify 式引用核查（对报告中的 claim 逐条三值验证）、AgentDisCo document bank。

### 成本预估

- 阶段一：每题 ~3–5 万 token（约 $0.1–0.3），30 题 × 多轮迭代 ≈ $50–150；
- 阶段二：每题升至 $0.6–2，完整评测轮 ≈ $100–300/轮；
- 阶段三 GEPA：$50/优化轮 × 3–5 轮。
- 总预算量级：**$500–1500**，无 GPU 需求。

---

## 6. 评测方案（三道防线）

评测严谨性是本报告方法论的组成部分，直接引用两篇评测论文的结论设计：

**防线一：防外部泄漏（依据 Search-Time Contamination）**
- 搜索结果进入 context 前，用 BML 正则黑名单过滤 benchmark 托管站 URL（HuggingFace/GitHub/题库站），该过滤器同时作为消融开关；
- 全程记录搜索轨迹（query、URL、访问页面），事后跑 QCL（归一化 LCS）与 EAL（LLM-judge）检测，按污染子集切分汇报分数；
- 注意：仅 URL 匹配不可靠（BML 单独 HR<1），必须做到 EAL 级。

**防线二：防内部泄漏（依据 LiveBrowseComp）**
- 报告**闭卷基线**：拆掉工具测 pass@4，若闭卷分数不可忽略则带工具分数不能声称测的是搜索能力；
- 若用 BrowseComp-Plus 类受控索引，加**证据屏蔽消融**验证系统是证据驱动而非假设验证驱动。

**防线三：过程指标**
- 证据使用率（检索到关键证据后是否被引用——现有系统 <33%，是明确的改进空间）；
- model-originated query 率（假设驱动 vs 证据驱动的探索比例）；
- 工具调用次数（早停的行为学证据，EDR 方法论）；
- Search Coverage 类中间指标（AgentDisCo 验证过与端到端分数正相关，可用于低成本迭代）。

**Benchmark 选择**：DeepResearch Bench（RACE+FACT，主指标）+ DeepConsult（pairwise 胜率）+ 可选自建 50 题时效性私有集（LiveBrowseComp 配方：6 个带时间戳的免费 API + 90 天窗 + 长尾过滤）。

### 对照组设计（三方对照）

系统的每轮评测与两个对照组同场对比，三个 arm 各自回答一个独立问题：

| 对照组 | 构成 | 回答的问题 |
|---|---|---|
| 写死工作流 | 固定顺序流水线：出大纲 → 逐节检索 → 逐节写作，无任何动态决策 | 下界：agent 自主决策（选缺口、判终止、调大纲）的净贡献是多少 |
| 通用 agent harness | Claude Code 等通用编排框架 + 搜索工具 + 一段研究指令 | 强基线：专用架构是否优于通用 harness 的泛化机制（其子 agent 委派、文件系统记忆、任务清单已泛化覆盖本报告的多数机制） |
| 本系统 | 第 5 节的专用架构 | 专用状态管理 + 终止判据 + 委派的组合收益 |

三种可能结果均有明确行动含义：本系统显著领先 → 专用架构增益成立；与通用 harness 持平 → 工程路线改为"将机制实现为通用 harness 的 skill/subagent 配置"，省去自建编排；与写死工作流持平 → 机制未生效，回查实现。

**公平性控制**：
1. 通用 harness 绑定其默认模型（如 Claude Code 绑定 Claude），本系统须增加一个同档模型配置，该组才构成有效对比（否则架构差异与基座差异混淆）；
2. 搜索后端对齐（给通用 harness 挂载与本系统相同的搜索工具，而非其内置搜索），无法对齐时在报告中注明；
3. 三个 arm 统一预算上限（token/美元）、统一输出格式要求、每配置至少 3 次取均值；
4. 裁判盲评：打乱顺序、隐去系统标识；
5. 防线二的闭卷基线对三个 arm 同样执行（通用 harness 也须测"不给搜索工具直接作答"，区分其得分来自搜索还是参数化知识）。

---

## 7. 实证研究：从选型到八方案对照的迭代实验

> 本章记录报告完成选型后（7-03 至 7-06）的实证工作。完整代码与产物见
> `~/deepresearch-lab/`（git 管理），实验设计细节见该目录 `EXPERIMENTS.md`。

### 7.1 实验设计

自建评测框架：10 道中文深度研究题（产业分析/政策对比/行业评估），RACE 风格
四维盲评（全面性/深度/指令遵循/可读性，裁判 claude-opus-4-8 与执行模型不同档，
匿名乱序呈现），全部方案共用同一执行模型与同一搜索后端（统一 CLI 封装，agent
类方案禁用内置联网工具），每次运行落盘完整 trace 供归因。

对照方案分三系九个（详表见 EXPERIMENTS.md §2；代码与产物目录使用短代号：
Pipeline=A，Workflow-v1..v4=C/Workflow-v2/Workflow-v3/Workflow-v4，Agent-ClaudeCode=B，Agent-OpenCode=D，
Agent-Codex=E，Hybrid-v1/v2=Hybrid-v1/Hybrid-v2）：

- **workflow 系**（自研，机制来自第 3-4 章选型）：Pipeline 固定流水线；Workflow-v1 机制组合 v1
  （EDR 判据 + VeriTrace 证据库 + SearchSwarm 工人 brief + ScaffoldAgent 大纲）；
  Workflow-v2/Workflow-v3/Workflow-v4 为三轮单变量迭代版
- **agent 系**（现成通用 harness 无头模式）：Agent-ClaudeCode（Claude Code）、Agent-OpenCode（opencode）、Agent-Codex（codex）
- **合流系**：Hybrid-v1/Hybrid-v2 = agent 基座 + workflow 机制外挂（协议 prompt + 输出端验证器 +
  修订回路）

### 7.2 主要发现

**发现一：agentic loop 显著优于 workflow 编排，且跨模型、跨 harness 成立。**
Round 1（claude-sonnet-5，10 题）：Agent-ClaudeCode 8.93 十战全胜 > Workflow-v1 7.89 > Pipeline 7.66。
Round 2（MiMo-2.5-pro，典型 3 题）：Agent-ClaudeCode 8.71 > Agent-OpenCode 8.38 > Workflow-v2 7.21 > Pipeline 6.54。
Agent-OpenCode（opencode）几乎追平 Agent-ClaudeCode，说明是范式优势而非单一产品优势。

**发现二：编排刚性与模型敏感性正相关。** 换弱模型的跌幅梯度
Pipeline（−2.72）≫ Workflow-v1（−1.24）> Agent-ClaudeCode（−0.93）：固定流水线把每步产出格式写死，弱模型
一步走样全程放大；agent loop 每步看到真实产出可自我纠偏，为弱模型兜底。
推理模型进一步放大 workflow 劣势：多调用编排在 MiMo 下延迟 3 倍（思考税逐调用征收）。

**发现三：workflow 差距可大幅弥合，且每步增益可分解。**
三轮单变量迭代（同预算 14 轮）：Workflow-v1→Workflow-v2（预算上限/补搜池/续写/去重/结论综合）；
Workflow-v2→Workflow-v3（判据硬核对：点名实体子串匹配、数量要求"LLM 抽取+代码数数"）+0.33；
Workflow-v3→Workflow-v4（写作提示强制"深度四要素"：数据点/多方对比/机制解释/批判性评估）
**+0.63，depth 7.17→8.17**。最终 Workflow-v4 达 8.46，距 Agent-ClaudeCode 仅 0.42，且在评估型难题
q09 上（8.62）超过 opencode（8.25）。两条高回报设计原则：
**"LLM 做抽取、代码做判断"**（消除自评乐观）与**"深度要素显式化"**（depth 可通过提示工程提升）。

**发现四：合流系（agent 基座 + 机制外挂）是最佳质量-成本平衡点。**
Hybrid-v1/Hybrid-v2（Agent-ClaudeCode + 协议 prompt + 输出端验证器 + 修订回路）与裸 Agent-ClaudeCode 总分打平
（8.83/8.84 vs 8.88），但 depth 8.5 为全场最高（Hybrid-v1），q01_F 9.0 为全实验最高
单题分；耗时 ~650s 为 Workflow-v1 系的 1/3。机制外挂的作用不是抬高总分天花板，而是
**重塑得分结构**（深度提升、指令遵循顶格、可审计性增强），并给 fail-silent
的 agent 补上验证护栏。Hybrid-v2 相对 Hybrid-v1 的增量（信源多样性检查、修订分诊、会话续跑）
在指令遵循上体现（9.33 追平 Agent-ClaudeCode）。

**发现五（事故所得）：fail-loud vs fail-silent 与裁判盲区。** 搜索后端配额中途
耗尽形成天然压力测试：证据门控系统诚实报告"证据为空"（得分 4-6），agent 系
静默切换参数化知识编造"看似有据"的报告（得分 7-8），**LLM 裁判无法识破零证据
编造**——Time to REFLECT（arXiv 2605）警告的裁判盲区的实证案例。结论：
(a) 评测必须辅以过程指标（trace 真实检索行为）与引用可验证性抽查；
(b) 高可信场景中 workflow 的可审计性/诚实失败仍是真实优势，正是 Hybrid-v1 系验证器
外挂试图补给 agent 的能力。

### 7.3 最终对照表（典型 3 题，MiMo-2.5-pro，统一裁判，2026-07-07）

| 方案 | overall | 全面性 | 深度 | 指令遵循 | 可读性 | 均耗时 |
|---|---|---|---|---|---|---|
| **Hybrid-v4**（内省验证+统一 rubric） | **8.96** | 9.0 | **8.5** | **9.5** | 8.83 | ~700s |
| Agent-ClaudeCode（裸 harness） | 8.88 | 9.0 | 8.33 | 9.33 | 8.83 | 284s |
| Agent-ClaudeCode+委派 | 8.88 | 9.0 | 8.33 | 9.33 | 8.83 | ~640s |
| Hybrid-v2 | 8.84 | 9.0 | 8.17 | 9.33 | 8.83 | ~670s |
| Hybrid-v1 / v3 | 8.83 | 9.0/8.93 | 8.5/8.33 | 9.17/9.33 | 8.67/8.73 | ~630/1170s |
| Workflow-v4 | 8.46 | 8.5 | 8.17 | 8.83 | 8.33 | ~2160s |
| Agent-OpenCode（裸 harness） | 8.13 | 8.17 | 7.67 | 8.17 | 8.5 | 299s |
| Workflow-v3 / v2 | 7.83 / 7.5 | | | | | ~1900s |
| Pipeline | 6.86 | 7.17 | 6.33 | 6.67 | 7.27 | 326s |

三个终局要点：

1. **Hybrid-v4 首次超越裸 agent**（8.96 > 8.88，指令遵循 9.5，q05 单题 9.38 全实验
   最高）。Hybrid 迭代轨迹 8.83→8.84→8.83→8.96：前三版噪声内打平，v4 的
   "内省验证（验证器作为工具交 agent 自检）+ 统一 rubric（研究目标与验收标准同源）"
   才真正突破——**质量杠杆在目标对齐与验收，不在外部把关的次数**。
2. **委派负结果**：放开子 agent 委派（+Task 工具与委派指引）后与裸 agent 三题四维
   完全同分，且单题搜索次数暴涨 5 倍分数不动——文献中委派编排的 +10 分（BrowseComp
   深搜）**不迁移**到长报告场景，长报告瓶颈在综合与验收而非检索吞吐。
3. **引用真实性可机械审计**：搜索工具审计日志上线后，各方案报告引用 URL 与真实检索
   行为的重合率（ev_used_ratio）达 0.97-1.0，为 fail-silent 风险提供常态化监控。

注：①同批次同裁判内部可比；裁判提示微调曾引起 ±0.3-0.6 漂移，绝对分不可跨批次
比较；②Workflow 系耗时含推理模型"思考税"；③Agent-Codex 未入本批（省预算）。

### 7.3b 全量 10 题终局（Hybrid-v6 vs 裸 agent）

3 题子集的测量分辨率在 8.9-9.0 区间耗尽后，对生产候选做 10 题确认：
**Hybrid-v6 均分 8.85 > 裸 Agent-ClaudeCode 8.76（胜 6 平 3 负 1）**——
方向为正但均分差未达显著（配对 bootstrap 95% CI [-0.06, +0.21] 跨 0，
n=10 不足以检出 0.09 量级效应）。分布上更关键：
F6 下限 8.5、集中在 8.8±0.15，而裸 agent 三题掉至 8.5-8.6——**外挂验证器的
结构性价值是托住下限、提供可预测性**，而非抬高上限（两者上限均 9.1）。

v6 包含三个正确性修复（任务动作验收、agent 自检与门禁标准同源、引用真实性
纳入风险门控、诚实交卷标记）；后续 v7 的任务类型条件化协议（评估型任务强制
条件化判断/最强反方/先行指标）在质量上获裁判点名认可且将 q09 的 depth 推至
全场最高（9.0），但总分与 v6 打平——v6 已耗尽该题 headroom，v7 留作可选增强。

### 7.4 对第 4 章选型的修订

实证结果部分推翻了 4.2 的选型结论：

1. **基座选择修订**：自建 workflow（ScaffoldAgent 起步骨架）不再是推荐起点——
   强通用 harness（Claude Code/opencode）是被文献系统性低估的 baseline，
   应作为默认基座；
2. **机制的正确定位**：第 3 章综述的 training-free 机制（判据终止、证据库、
   验证选择）价值成立，但正确宿主是"agent 基座上的外挂"（协议 prompt +
   输出端验证门），而非独立编排系统；
3. **保留的判断**：EDR 终止判据"必装"判断成立（Workflow-v3 的硬核对版本贡献 +1.0）；
   评测三道防线判断成立且被事故强化（新增：裁判日期注入、搜索后端降级链 +
   fail-loud 保险丝均已实装）。

### 7.5 迭代方法论

每轮迭代 = 失分 trace 归因 → 区分实现缺陷/机制缺失 → 单变量修改 → 冻结旧版 →
同预算重跑 → 分差归因到该变量。对照 harness 的 trace 作为"正确行为参考"
（如 Agent-ClaudeCode 在补搜时自发换语言换角度，直接启发了 Workflow-v2 补搜 brief 的设计）。
该纪律使 Workflow-v1→Workflow-v2→Workflow-v3 的每步增益可分解、负结果（Workflow-v2 证据量误伤）可解释。

## 8. 结论

**调研阶段结论（第 1–6 章）**：

1. **方向可行**：非训练路线有充分实验证据（编排层 +10、终止判据 +8.4、验证选择超 frontier 模型、架构增益压过基座差距），前提是使用足够强的基座模型；
2. **技术路线**：非训练方法归纳为四类（并行验证/显式状态管理/委派隔离/prompt 优化）；长报告场景的主路线是显式状态管理，委派与信息流控制作为互补；
3. **评测**：三道防线（搜索污染检测、闭卷基线+证据屏蔽、过程指标）+ 三方对照，保证结论可信。

**实证阶段结论（第 7 章，部分修订调研结论）**：

4. **架构默认选择修订**：通用 agentic harness（Claude Code/opencode）是被文献系统性低估的强基线，两模型、多 harness 上一致压过自建 workflow 编排——**新系统应以 agent loop 为默认基座**，而非从 ScaffoldAgent 式自建编排起步（修订 4.2 选型）；
5. **training-free 机制的价值成立，但正确宿主是"外挂"**：同一批机制（判据终止、证据核对、深度要素）以外挂形式装上 agent 基座（方案 Hybrid-v1/Hybrid-v2），以 1/3 成本得到 workflow 最优版（Workflow-v4）之上的质量，depth 全场最高；装进自建编排（Workflow-v1 系）则需三轮迭代才接近同等水平；
6. **两条高回报设计原则**（实验中可分解验证）："LLM 做抽取、代码做判断"（判据/验证环节 +0.3–1.0）；"深度四要素显式化"（写作环节 +0.63）；
7. **可靠性与评测警示**：agent 系 fail-silent（检索故障时静默编造且 LLM 裁判识不破）、workflow 系 fail-loud——高可信场景必须给 agent 配输出端验证器；评测结论只能依赖同批次盲评 + 过程指标 + 引用抽查，绝对分数不可跨批次比较。

## 附录：可直接复用的公开资产

| 资产 | 来源 | 用途 |
|---|---|---|
| FineVerify 代码与数据 | github.com/XuZhao0/fineverify | 引用核查模块参考实现 |
| 主/子 agent 全量 system prompt | SearchSwarm 附录 B | 委派 brief 写法参考 |
| DR 任务定制 meta-prompt 模板 | Self-Optimizing MAS 附录 | GEPA 调优 |
| 三级污染检测 prompt + URL 匹配表 | Search-Time Contamination 附录 | 评测防线一 |
| 时效性评测集构建配方 | LiveBrowseComp 附录 | 自建私有评测集 |
| open_deep_research（LangGraph） | github.com/langchain-ai/open_deep_research | 工程脚手架参考 |
| DeepResearch Bench / DeepConsult | 公开 benchmark | 主评测 |

## 参考文献

1. FineVerify: Scaling Test-Time Compute with Fine-Grained Self-Verification for Agentic Search. arXiv:2606.00660, 2026-05.
2. Argus: Evidence Assembly for Scalable Deep Research Agents. arXiv:2605.16217, 2026-05.
3. ScaffoldAgent: Utility-Guided Dynamic Outline Optimization for Open-Ended Deep Research. arXiv:2606.20122, 2026-06.
4. VeriTrace: Evolving Mental Models for Deep Research Agents. arXiv:2605.26081, 2026-05.
5. AgentDisCo: Towards Disentanglement and Collaboration in Open-ended Deep Research Agents. arXiv:2605.11732, 2026-05.
6. Don't Stop Early: Scalable Enterprise Deep Research with Controlled Information Flow and Evidence-Aware Termination. arXiv:2604.24978, 2026-04.
7. Self-Optimizing Multi-Agent Systems for Deep Research. arXiv:2604.02988, 2026-04.
8. SearchSwarm: Towards Delegation Intelligence in Agentic LLMs for Long-Horizon Deep Research. arXiv:2606.09730, 2026-06.
9. Search-Time Contamination in Deep Research Agents: Measuring Performance Inflation in Public Benchmark Evaluation. arXiv:2606.05241, 2026-06.
10. LiveBrowseComp: Are Search Agents Searching, or Just Verifying What They Already Know? arXiv:2605.28721, 2026-05.
