# Deep Research Agent 文献精读笔记（Training-Free 视角）

> 调研日期：2026-07-02。共精读 10 篇 2026 年论文，全部拉取 arXiv 全文。
> 团队约束：无训练资源，方向锁定推理时架构（test-time / harness 层）+ 严谨评测。

## 总览表

| # | 论文 | 机构 | 方向 | 是否 training-free | 每题成本 | 核心增益 |
|---|---|---|---|---|---|---|
| 1 | FineVerify (2606.00660) | NUS | 推理时验证/选择 | ✅ 完全免训练，代码开源 | <$0.8 | 4样本 +8.2 分；12样本让 GPT-5-mini 超 GPT-5 |
| 2 | Argus (2605.16217) | MiroMind | 并行证据组装 | ❌ Navigator 需 SFT+GRPO（64×H200） | 极高（K=64 时 25.6M token） | K=64 时 BrowseComp 55→86.2；架构思想可 prompt 复现 |
| 3 | ScaffoldAgent (2606.20122) | 北大 | 动态大纲优化 | ✅ 完全免训练 | 26.3k token / 117s | RACE +2.24，比 WebWeaver 省 29% token |
| 4 | VeriTrace (2605.26081) | Cambridge | 认知图/心智模型 | ✅ 完全免训练 | $0.6–2，40–65 min | 同基座 +1.49~+4.22 pp，DeepConsult 胜率 81.1% |
| 5 | AgentDisCo (2605.11732) | 小红书 | 探索/利用解耦 | ✅ 完全免训练 | 未报告 | RACE 51.44 超 Gemini-DR；引用准确率 +10.7 |
| 6 | Don't Stop Early / EDR (2604.24978) | Salesforce | 信息流控制+终止判据 | ✅ 完全免训练 | 未报token，DAG 使耗时 222→47 min | 终止判据单项 +8.4 HAA |
| 7 | Self-Optimizing MAS (2604.02988) | Zeta Alpha | prompt 自动优化 | ✅ 免梯度（GEPA 优化 prompt） | 每轮优化 ~$50 | 极简 prompt 0.513→0.705，超专家 prompt 0.667 |
| 8 | SearchSwarm (2606.09730) | 清华/北大/蚂蚁 | 委派智能 | ⚠️ 最终模型需 SFT；**harness 部分免训练 +10 分** | 高（未报） | 30B 模型 BrowseComp 68.1（追平 671B DeepSeek） |
| 9 | Search-Time Contamination (2606.05241) | NTU/阿里 | 评测污染 | ✅（检测流水线免训练） | judge ~$221/6800题 | EAL 污染使准确率 7.7%→89.7%；Gemini-DR 泄漏率 60% |
| 10 | LiveBrowseComp (2605.28721) | 哈工大/小红书 | 评测方法论 | ✅（诊断实验纯 API） | — | 证据屏蔽后全员 26.1→6.2；静态榜闭卷能拿近半分 |

---

## 方向一：推理时扩展与验证

### 1. FineVerify: Scaling Test-Time Compute with Fine-Grained Self-Verification for Agentic Search
arXiv 2606.00660，NUS。代码：github.com/XuZhao0/fineverify

- **问题**：test-time scaling 中正确答案在采样候选里稀疏，majority voting 失效；best-of-N / 整体验证分把多条件压成单一分数，噪声大、跨候选不可比、依赖模型校准。
- **方法**（纯推理时 propose-verify）：
  1. verifier 把问题分解为 m 个可核查子问题（全体候选共用同一套，保证可比）；
  2. 最多 T 轮：proposer agentic search 生成候选，verifier 对每个子问题检索证据给三值判断 {supported, not_found, contradicted}；
  3. 规则映射打分（严格版 [0,0,1]）求平均；满分早停；重复候选复用缓存判断。
- **实验**：BrowseComp-Plus / DeepSearchQA / xbench-DeepSearch / GAIA-Search；gpt-5-mini 和 gemini-3-flash（proposer=verifier）；baseline 为 Majority/Weighted Voting、Best-of-N、Solution Aggregation、Confidence Verify。
- **结果**：4 样本 GPT-5-mini 平均 59.2→67.4（+8.2）；BrowseComp-Plus 1→16 样本 49.5%→70.0%，12 样本即超 frontier GPT-5（67.0%）；baseline 12–16 样本饱和。选择准确率 90.7%。"生成弱 ≠ 验证弱"：xbench Pass@1 仅 45% 但选择准确率 80.3%。规则映射比 LLM 直接打分好 2 分。
- **可复用**：分解→逐条三值判定→规则聚合的配方即插即用；早停+缓存省钱；验证轨迹可审计数据集（发现 BrowseComp-Plus 200 题中 10 处标注错误）。
- **缺陷/机会**：验证不反馈给生成（proposer 每轮独立采样，缺口信息未引导下轮搜索）——正是与 Argus 思想互补的拼接点；子问题等权；分解无质量校验；只覆盖短答案。

### 2. Argus: Evidence Assembly for Scalable Deep Research Agents
arXiv 2605.16217，MiroMind AI。**注意：需要训练**（Searcher SFT ~1万条轨迹；Navigator SFT 热身 + GRPO，64×H200 跑 1.5 天）。

- **问题**：K 条并行 ReAct rollout 检索到重复而非互补的证据，收益饱和；"先消费后聚合"方法被聚合器上下文封顶。
- **方法**：Searcher（无状态 ReAct，可任意并行）+ Navigator（维护 DAG 证据图：证据节点带 URL 去重、claim 节点、support/contradict 边）。Navigator 三阶段循环：派发 query → 解析 trajectory 入图、给 claim 标 supported/contradicted/unverified、针对"未验证/矛盾/未覆盖"三类缺口批量生成 verification query 再派发 → 清空工作上下文，仅对 (q, G) 紧凑视图合成答案。
- **结果**：Solo +5.5 / Parallel(K=8) +12.7 分；K=64 时 BrowseComp 55.0→86.2%（log-linear 无饱和）；Searcher 25.6M token vs Navigator 合成上下文 21.5K（1200:1 压缩）；结构化表示消融贡献 +5.2 分；比 Majority-Vote 高 6–11.6 分。
- **可复用（架构思想，不依赖训练）**：共享证据图作聚合中介（解耦并行度与聚合器上下文）；缺口驱动派发（预算花在互补处）；合成前清空上下文；shadow synthesis 做离线诊断。
- **缺陷**：training-free 复现时图构建质量全靠 prompt，需自加格式状态机校验；推理成本巨大；论文未给 prompt-only Navigator 的消融，纯提示能保留多少收益未知。

---

## 方向二：中间表示 / 大纲的显式管理

### 3. ScaffoldAgent: Utility-Guided Dynamic Outline Optimization for Open-Ended Deep Research
arXiv 2606.20122，北大。✅ training-free。**三个系统里最便宜（26k token/题）**。

- **问题**：大纲要么写前固定（STORM），要么局部启发式更新（WebWeaver）→ C1 脚手架漂移（冗余分支、粒度失衡）；C2 延迟反馈（改大纲的价值要到写作才显现）。
- **方法**：大纲树节点带（意图 h、证据 E、效用统计 θ=(n, ū)）。核心循环：
  1. **UCB 选点** v = argmax(−ū + c√(lnN/n_v))：优先修低效用节点、兼顾探索；
  2. 三操作选一（AGM 信念修订启发）：Expansion 拆分 / Contraction 合并 / Revision 原位刷新；
  3. **效用反馈** U = ⅓U_ret（embedding 相关性+新颖度）+ ⅓U_str（连贯+平衡−冗余）+ ⅓U_gen（**试写** trial writing：NLI claim 支撑率+意图覆盖−冗余）；
  4. 近 k 步平均效用增益 < ε 终止（上限 20 轮）。
- **实验**：DeepResearch Bench + DeepResearch Gym + 自建多轮 follow-up 集；Qwen3-32B / DeepSeek-V3.2。
- **结果**：Qwen3-32B RACE 44.70（+2.24）、引用准确率超 WebWeaver 13.42 分；DeepSeek-V3.2 48.27 五个子维度全第一。消融：去 Revision −5.18；仅留 Expansion 出现大纲无限膨胀不终止；去 U_gen −4.69（引用准确率 −11.38）。多轮 follow-up 局部子树更新 72.60 vs 全文重写 59.70。比 WebWeaver 省 29% token、49% 搜索，比 EDR 快 4.3×。
- **可复用**：UCB 选点+增量均值更新（几十行代码）+ 边际效用终止条件；试写作廉价前瞻解决延迟反馈；混合评估器（公式能算的绝不用 LLM）。
- **缺陷**：11 个权重全手调；树无横向边，无法表达证据冲突；embedding 对"语义相近但事实矛盾"不敏感。

### 4. VeriTrace: Evolving Mental Models for Deep Research Agents
arXiv 2605.26081，Cambridge。✅ training-free（$0.6–2/题，200+ LLM 调用，40–65 min）。

- **问题**：中间层被混杂质量信息污染、错误沿依赖传播；现有系统靠 LLM 隐式演化中间表示，"用模型规模弥补缺失的调控"。
- **方法**：认知图（节点=概念，带验收准则、UNKNOWN/PARTIAL/KNOWN 状态、CRAAP 质量分；边=探究关系）。四角色（Planner / 并行 Searcher / Reader / Manager）+ 三条显式调控回路：
  1. **解释性更新**：新发现分类为 满足准则/冗余/矛盾/意外，结构化折叠入节点；
  2. **偏差反馈**：四维偏差信号 δ=(相关性, 可信度, 可达性, 意外强度) → 路由到五策略 {SUBSTITUTE, EXPLOIT, VERIFY, PIVOT, EXPLORE}；
  3. **图式修订**：偏差聚集/矛盾累积触发五种结构操作，受两条不变式保护（证据只增不删、用户维度不可删）。
  证据机械式入库（原文引文+URL，不经 LLM 二次加工）。
- **结果**：同 27B 基座 DRB Overall 52.28（+1.49）、Insight +4.22；DeepConsult 胜率 81.1%；DeepSeek 配置 55.77 为可复现开源最强（超 Claude-Sonnet-4.5 基座的 FS-Researcher 53.94）。消融：去偏差反馈 −1.65 且搜索量 1.31×；去解释性更新 −1.52 且搜索萎缩 0.42×（"以为存满了"提前收工）；重构子集上去图式修订 −4.75。
- **可复用**：偏差信号→策略路由（相关但不可信→VERIFY，不相关但意外→PIVOT）纯提示工程即可实现，省搜索又提质量；机械证据溯源解决引用漂移；结构不变式防 LLM 自毁状态。**重要教训：小模型下图结构比平铺列表更脆，没有修复机制就别用图。**
- **缺陷**：启发式触发阈值；无跨任务迁移；工程复杂度高、延迟近 1 小时。

### 5. AgentDisCo: Towards Disentanglement and Collaboration in Open-ended Deep Research Agents
arXiv 2605.11732，小红书。✅ training-free。

- **问题**：探索（生成 query）与利用（改大纲/报告）纠缠在同一模块，迭代无显式优化目标，在过度/不足修改间震荡。
- **方法**：Planner（query 分类+风格推断）→ Critic（评大纲、输出 **blueprints**：要点+针对性 query 组）⇄ Generator（执行检索、修订大纲）交替循环 + Document bank（证据片段化、并行打分、跨轮索引、连续性约束）→ Writer 分节写作 → Render。**Meta-optimization harness**：用 Claude-Code 做外层优化 agent，按四准则给 critic 的 query 打分迭代，自发构建 policy bank（BM25 检索历史 trace）实现搜索策略自进化。
- **结果**：RACE 51.44 > Gemini-2.5-Pro-DR 49.71；+harness 52.11；Opus 基座 54.02；引用准确率 89.06（+10.7 超 Gemini-DR）；DeepConsult win rate 56.86%。中间指标 Search Coverage 62.5→82.05 与端到端分数同步上升。
- **可复用**：critic/generator 解耦 + blueprint 结构直接可抄；document bank 是低成本上下文管理；**用 Claude-Code 做 harness 层自动优化**对无训练团队性价比极高，且验证了"便宜的中间指标可用于迭代"。
- **缺陷**：harness 增益仅 +0.67 RACE 且无显著性检验；对抗式 MDP 更多是包装；自评 reward 有自我偏好风险；token 成本未报告；成稿质量粗糙（有残句）。

---

## 方向三：信息流控制与多 agent 编排

### 6. Don't Stop Early: Scalable Enterprise Deep Research (EDR)
arXiv 2604.24978，Salesforce。✅ training-free（LangGraph 实现）。**消融证据全 10 篇中最扎实。**

- **问题**：企业报告三大失败模式——覆盖不均、上下文爆炸、过早停止。现有系统只优化规划检索，从不显式控制"何时算做完"。
- **方法**（三机制一一对应）：
  1. **Outline + Reflection**：检索前纯基于任务定义出大纲并反思查漏（防检索分布带偏方向）；
  2. **Plan DAG + 依赖门控**：每步只接收依赖步骤的输出而非全部历史；无依赖步骤并行；replanning 固定轮数后冻结；
  3. **Evidence-aware Termination**：每个 agent 执行前**预声明显式终止判据**（要收集到哪些具体信息才算完成），循环取证自评直到满足。
- **结果**：销售任务 HAA 71.94 远超 Gemini-DR 60.00 / OpenAI-DR 59.67；DeepResearch Bench Avg 53.40 超 Tavily/ThinkDepth。**消融**：去终止判据 HAA −8.4（工具调用 327→224，直接证实早停）；去 DAG 改顺序 HAA −5.7 且耗时 47→222 分钟；去 outline reflection −11.3。有趣发现：固定模板任务上 4.1 反超 5.1（强推理模型画蛇添足）。
- **可复用**：**执行前预声明终止判据是全部 10 篇中性价比最高的单点改进**（一段 prompt 换 8.4 分）；先大纲后检索零成本；DAG 门控同时解决速度与质量；"用工具调用次数作早停行为证据"的消融方法论。
- **缺陷**：内部评测集不可复现（仅 10 场景）；判据自定义自判断，可能"自定义低标准然后自我满足"；可读性不占优；未报 token 成本。

### 7. Self-Optimizing Multi-Agent Systems for Deep Research
arXiv 2604.02988，Zeta Alpha。✅ 免梯度（prompt 层优化）。

- **问题**：手工 prompt 脆弱，换模型/领域即崩，人工重调昂贵。
- **方法**：四角色流水线（Orchestrator 计划派发 / 并行 Reader 抽证据 / Aggregator 合 mini-report / Writer 成稿，引用 ID 贯穿）。把四个 system prompt 当可优化参数：用 29 条带专家 rubric 的训练 query，LLM meta-prompt 依据评分+轨迹迭代改写 prompt。对比 TextGrad（贪心爬山）vs **GEPA**（遗传+Pareto 前沿采样）。
- **结果**：极简一行 prompt 0.513 → GEPA+定制 meta-prompt **0.705，超过专家一年打磨的 prompt 0.667**；优化已强的专家 prompt 收益递减（+0.005~0.034）；OpenAI 通用优化器最差（0.583）。每轮预算 $50。
- **可复用**：GEPA 式 prompt 自动优化只需几十条 rubric query + LLM judge；**meta-prompt 必须任务定制**（0.685→0.705，附录给了 DR 任务模板）；Pareto 多样性优于贪心。
- **缺陷**：单领域小数据无显著性检验；LLM-judge 有偏（优化可能在"讨好 judge"）；只优化 prompt 不动架构；已有好 prompt 时性价比低。

### 8. SearchSwarm: Towards Delegation Intelligence in Agentic LLMs
arXiv 2606.09730，清华/北大/蚂蚁/人大。⚠️ 最终模型需 SFT，但 **harness 部分 training-free 且贡献 +10 分**。

- **问题**：长程任务上下文需求无界而窗口有限；被动摘要/截断是无差别丢弃。主动方案（主 agent 委派子 agent）需要"委派智能"，该能力自然语料中不存在——直接给基座挂委派工具，它**从不调用**。
- **方法**：主 agent ReAct + call_sub_agent(brief)；子 agent 在全新独立上下文执行（只见 brief），返回压缩报告。四条 harness 设计原则：① 鼓励委派（token 昂贵但认知浅的收集工作交给子 agent）；② **详尽 brief**（把子 agent 当"刚加入调查的新同事"：任务+理由+已确认+不确定+已排除方向）；③ 主 agent 保留核心判断（方向决策、冲突裁决，子结论不可未验证就信）；④ 引用锚定报告（子 agent 结论带内联 URL，主 agent 可 visit 验证）。之后用 harness 引导的轨迹做 SFT 内化。
- **结果**：SearchSwarm-30B BrowseComp 68.1（30B 级 SOTA，追平 671B DeepSeek V3.2 的 67.6、超 GPT-5.2-Thinking 65.8）。**关键消融（training-free 部分）**：DeepSeek V3.2 原框架 47.7 → 只加工具定义 50.0 → 完整 harness（四原则 prompt）57.7，即**纯推理时 +10 分，其中 prompt 原则贡献 +7.7**。反例：弱基座挂 harness 不训练 = 从不委派。
- **可复用**：附录 B 开源主/子 agent 全量 system prompt；详尽 brief 原则最便宜有效；引用锚定+visit 验证给出"不看子轨迹也不盲信"的机制；上下文预算分层（主 128K/子 64K）+ 临界回滚强制作答。
- **缺陷**：harness 增益依赖基座能力（必须用强模型当主 agent）；委派仅一层、子 agent 间无通信；主结果无法精确归因；成本未报告。

---

## 方向四：评测与可信性

### 9. Search-Time Contamination in Deep Research Agents (STC)
arXiv 2606.05241，NTU + 阿里通义。检测流水线免训练可直接抄（附录含完整 prompt 和 URL 匹配表）。

- **问题**：agent 推理时联网可能搜到 benchmark 原题甚至答案，分数虚高；现有检测只做仓库级 URL 匹配，太粗且"命中仓库≠答案泄漏"。
- **三级污染分类**：**BML**（元数据泄漏：URL 暴露 benchmark 托管站，正则检测）→ **QCL**（问题上下文泄漏：页面含原题措辞，归一化 LCS 检测）→ **EAL**（显式答案泄漏：原题+答案同页，LLM-judge 严格双条件，人工校验精确率 94.85–100%）。评估两层：问题级切分子集 + 轮次级时变 Cox 比例风险模型（污染事件当时变协变量算 HR）。
- **结果**：6 个医学 benchmark 全部有污染，MedMCQA 约 1/4 题可搜到答案；EAL 前后准确率 7.69%→89.74%，HR 2.20–8.92；**BML 单独不足以定罪（HR 多 <1，推翻前人仅凭仓库匹配的结论）**；QCL 催化后续 EAL（HR 2.50–6.74）。商业系统：Gemini-DR 泄漏率 60%，Valyu 在 MedQA 0% 但在 PubMedQA 65–78%（受限检索源也不安全，本质是语料重叠）。总花费 $858。
- **对实验设计的启示**：隔离知识沙箱评测；搜索轨迹全透明记录；按污染子集切分汇报；必须做 EAL 级检测。
- **可复用**：三级检测流水线当**运行时过滤器**（搜索结果入 context 前剔除可疑 URL，既防污染又可做消融开关）；Cox/KM 可量化任何"中间事件→成功"的关联；"1 个白盒深挖 + N 个黑盒抽检"的实验经济学。

### 10. LiveBrowseComp: Are Search Agents Searching, or Just Verifying What They Already Know?
arXiv 2605.28721，哈工大 + 小红书。诊断实验纯 API 可复现。

- **问题**：静态榜高分可能是"参数化知识先猜答案、搜索只做验证"（内在知识依赖 IKD），比数据污染更隐蔽，n-gram 去污检查查不出。
- **三个诊断实验**：① 闭卷 pass@4（拆掉工具测知识覆盖）；② 证据屏蔽搜索（剔除全部 gold 文档，只留无关+难负例）；③ 轨迹溯源（query 关键信息源自模型推理还是检索结果；检索到关键证据后 3 轮内是否被使用）。
- **结果**：静态榜闭卷平均 38.9 分（最高 62.0）——不搜也能拿近半分；证据屏蔽后全员 26.1→6.2（搜不到证据时搜索比不搜更差 → 搜索是验证通道而非发现机制）；>50% query 是模型自生假设驱动；**检索到关键证据的使用率不足 1/3（24.7–32.2%）**。LiveBrowseComp（335 道 90 天内时效题，五阶段流水线+三重评审）：闭卷全员 <2%；带搜索掉 25–40 分；排名洗牌（GLM 5.1 从 68.0 跌到 33.9，DeepSeek v3.2 反超）；人类求解率两榜一致（30% vs 31%）证明掉分纯粹是拿掉记忆捷径。
- **对实验设计的启示**：必须报闭卷基线；加证据屏蔽消融；时间锚+长尾过滤+答案稳定性检查；跨模型比较用统一 scaffold；人类难度校准。
- **可复用**：三个诊断实验只需 API；"model-originated query 率"和"证据使用率"是便宜且诊断力强的过程指标；**"证据使用率 <33%"和"失败后只会改写上一条 query"是现成的推理时架构改进切入点**（证据强制引用、失败后强制换检索策略），可用证据屏蔽实验做 before/after；自建 50 题私有 live 集的完整配方（6 个免费 API + 90 天窗 + 长尾打分阈值）。

---

## 综合分析

### 领域收敛出的共识设计（多篇独立收敛）
1. **显式中间表示 + 显式完成判据**：AgentDisCo 的 blueprint ≈ EDR 的大纲子问题+终止判据 ≈ ScaffoldAgent 的大纲树 ≈ VeriTrace 的认知图——都在把"研究状态"从 LLM 隐式上下文中拿出来结构化管理。
2. **验证比生成容易**：FineVerify（事后选择器）与 Argus（在环调度器）都押注此点；FineVerify 实证"生成弱 ≠ 验证弱"。
3. **委派 + 上下文隔离**：SearchSwarm 的 call_sub_agent 与 EDR 的 DAG 依赖门控都是"每个工作单元只见必要信息"。
4. **prompt 层自动优化替代人工调参**：Self-Optimizing MAS 的 GEPA 与 AgentDisCo 的 Claude-Code harness 殊途同归。

### Training-free 的可行性证据链（报告核心论点素材）
- SearchSwarm 消融：纯 harness 对强基座 +10 分（prompt 原则占 +7.7）
- EDR 消融：一段终止判据 prompt +8.4 HAA
- FineVerify：零训练 12 样本让 GPT-5-mini 超 GPT-5
- Self-Optimizing：GEPA 自动优化 prompt 超专家一年手工调参
- VeriTrace/AgentDisCo：同基座下架构改进稳定 +1.5~+4 pp，超商业 DR 产品
- 反面约束：SearchSwarm 证明弱基座不会自发委派——training-free 路线必须用足够强的基座模型

### 推荐组合路线（按预算从低到高）
1. **起步**：ScaffoldAgent 的 utility-UCB 骨架（26k token/题）+ EDR 的预声明终止判据 + 先大纲后检索
2. **验证层**：FineVerify 的分解-三值核查-规则聚合；改进方向是把 not_found/contradicted 缺口反馈给下一轮搜索（借 Argus 缺口派发思想，prompt 复现）
3. **委派层**：SearchSwarm 开源 harness prompt（详尽 brief + 引用锚定 + 主 agent 保留判断）
4. **自动调优**：GEPA 优化整套 harness 的主/子 prompt（几十条 rubric query + $50/轮）
5. **增强插件**：VeriTrace 偏差路由（VERIFY/PIVOT 策略选择）+ 机械证据溯源；AgentDisCo document bank

### 评测协议（三道防线）
1. **防外部泄漏**：STC 三级检测（BML 正则 → QCL 归一化 LCS → EAL LLM-judge），BML 正则同时当运行时 URL 过滤器
2. **防内部泄漏**：闭卷基线 + 证据屏蔽消融 + query 溯源统计（LiveBrowseComp 三诊断）
3. **过程指标**：证据使用率、model-originated query 率、工具调用次数（早停行为证据）、Search Coverage 类中间指标
- benchmark 选择：DeepResearch Bench（RACE+FACT，报告类）+ BrowseComp-Plus（受控索引，可做证据屏蔽）+ 可选自建 50 题 live 集

### 公开的可复用资产
- FineVerify 代码：github.com/XuZhao0/fineverify
- SearchSwarm 附录 B：主/子 agent 全量 system prompt
- Self-Optimizing 附录：DR 任务定制 meta-prompt 模板
- STC 附录：三级检测 prompt + URL 匹配表
- LiveBrowseComp 附录：6 个时间戳 API 源 + 长尾过滤阈值
- 基座项目：langchain-ai/open_deep_research（架构最干净）/ gpt-researcher（工程成熟）/ deer-flow（工业对照）

---

## 增补（2026-07-07 扫描）：agent 式 DR 的方向图谱与 6 月新论文

> 背景：实证阶段确认 agentic loop 为默认基座后，回扫 arXiv 6 月新工作
>（API 限流，改抓 arxiv.org/search 页面），归入六个方向。

### 方向图谱（含对我们工作的映射）

1. **上下文工程**：委派隔离（SearchSwarm）、外置记忆（Argus 证据图、DualGraph
   知识图/大纲图分离）、压缩策略（工程实践领先论文）。→ Hybrid 的下一层空间，
   "上下文策略 × 报告质量"对照实验是文献空白，我们有三 harness 真实 trace。
2. **编排拓扑**：并行+验证聚合（Argus）、角色分工（AgentDisCo/VeriTrace）、
   动态拓扑。→ 我们证明裸单 agent 已很强，多 agent 增量需严格对照。
3. **test-time scaling**：验证选择（FineVerify N选1）、终止判据=何时停止 scaling
   （EDR）。→ 我们的风险门控是成本侧贡献（自适应决定花多少）。
4. **训练 agent 模型**（排除但追踪）：MetaResearcher（对抗环境 RL）、QUEST（合成
   任务）、S1-DeepResearch（长程真实任务）、DEEPRUBRIC（证据树 rubric 监督——
   监督信号结构可 training-free 借用作验证器评分结构）、SlimSearcher（效率 reward）。
5. **评测与可信性**（持续加厚）：Time to REFLECT（先评裁判）、TELBench（span 级
   轨迹错误定位）、"Can LLM-as-a-Judge Reliably Verify Rubrics in Agentic
   Scenarios?"（2026-06-29，**直接支撑我们的裁判噪声发现**）、Multi-Turn
   process-level 评测、跨语言 BrowseComp-Plus、SciConBench（原子事实分解）。
6. **垂直域爆发**（6 月最密集信号）：DEEPMED Search（医疗，**introspective
   verification 内化验证，与我们 Hybrid 验证器同构，值得精读**）、Physical
   Sciences DR、ICBCBench（金融）、MASS（社科）、VideoSearcher（视频多模态）。
   通用架构收敛后竞争转向垂直适配+域评测；可信性要求抬高验证器地位。

另：harness 工程本身开始成为研究对象——SkillHone（持久决策历史上的技能进化）、
CLI-Universe（终端 agent 任务合成）、SwarmX（agentic 调度）。我们的 F 系外挂
实验有同行了。

### 对我们的三个直接行动项

- 精读 DEEPMED 的 introspective verification，与 Hybrid-v3 引用核验互证；
- 报告裁判噪声部分引用 LLM-as-Judge rubric 可靠性论文（06-29）作文献支撑；
- 垂直域迁移验证（如金融+ICBCBench）是方法论的自然落地出口。


## 增补(2026-07-21 循环扫描):核验器 FPR 论点
- **Hallmark**(arXiv 2607.18360,07-20):引用核验器 benchmark(2526 条,
  14 类幻觉,污染防护 held-out)。核心论点:**核验器可部署性的瓶颈是假阳性率
  (FPR)而非召回**——agentic 查证买到召回但推高 FPR;真实基率下 FPR 的数量级
  差(而非召回)决定"报警是真捕获还是噪音";多数 LLM 对训练截止后的论文
  过度报警。
- 对我们的映射:fact-v2 的"矛盾"判定就是我们的报警通道——mimo_smoke 曾修过
  一轮 conflict 去噪(pair 级 worst-of 高估 4-5×),方向与该文一致;若将来把
  F10.2 的核修/[未证实] 标注当告警系统推给用户,**FPR(把对的标成未证实)
  应升为一等指标**——目前 fact2 的 partial 池里可能混有核验器自身的假阴性。


## 增补(2026-07-27):Grok Build /deep-research(07-26 发布)
一手来源:cryptobriefing 发布报道 + docs.x.ai(grok-4.20-multi-agent 模型页、
Citations API 文档)。架构四件套:
1. **多 agent 并行+独立核验**:专用模型 grok-4.20-multi-agent(1M 上下文,
   $1.25/M 输入),多 agent 并行拆解问题,"aggregate verified claims,
   cross-reference evidence, independently validate"——聚合的是已核验论断;
2. **缺口披露为产品特性**:报告自带"a list of what it couldn't find";
3. **检索用 Exa**(与本 lab deep-research skill 同源);
4. **平台层引用绑定**(API 层非模型自觉):All Citations(检索接触的全部 URL
   无条件返回,含未引用的——完整 provenance)+ Inline Citations([[N]](url)
   +结构化位置元数据 annotations)。

**与本 lab F115 的四点独立收敛**:核验聚合↔后置核修;缺口清单↔"未获来源
子话题"披露;All Citations↔search_calls.jsonl;平台引用↔[Sn] 机械渲染
(路径 C 的 training-free 近似)。唯一分野=多 agent 并行(强基座可负担
orchestrator-worker;弱基座不自发委派,故我们走串行三阶段)。
**关键旁证**:xAI 文档明言 inline citations "model decides when and where"
不保证每句引——最强基座上生成时引用仍靠模型自觉,G-Cite 不可靠结论的
行业级印证。可操作:Grok API OpenAI 兼容,可接入评测框架作强基座对照臂。
