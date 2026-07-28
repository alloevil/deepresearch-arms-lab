# 主流 Deep Research 系统方案调研(2025-2026)

> 调研日期:2026-07-20。证据台账:`evidence-dr-mainstream.md`(35 条)。
> 定位:与 `deepresearch-survey-notes.md`(2026 学术论文精读)互补,本篇聚焦**工业系统与开源框架的工程设计**,三个维度:检索-写作编排 / 引用可信性机制 / 弱基座适配。直接动机:F9.1 证据台账 prompt 协议在 MiMo 弱基座上收益归零(mimo_smoke 批,2026-07-17)。

## 摘要

1. 主流系统分**训练派**(OpenAI、Kimi:能力用 RL 内化进模型)与**编排派**(Anthropic、Gemini、Perplexity、全部开源框架:harness 承担结构),但在引用问题上殊途同归——**没有任何一家依赖"模型在写作时自觉遵守引用协议"**:训练派用 format/rubric reward 内化 [9][10],编排派把引用做成管线结构(后置 CitationAgent [8]、采集侧 source-track [18]、检索层预绑定 provenance [14])。我们的 F9.1 生成时台账协议恰好是行业普遍回避的那条路。
2. 学术侧给出了系统对照:生成时引用(G-Cite)精度优先但牺牲覆盖与速度,事后归因(P-Cite)高覆盖+正确性有竞争力,高风险场景推荐 P-Cite 优先;且**两个范式下引用质量的主驱动都是检索,不是生成模型的引用能力** [1]。
3. 弱基座的失效有机理实证:小模型在复杂格式要求下发生 **scaffold collapse**(直接放弃结构协议),且存在非单调现象——**轻量协议包装比裸模型更差**;有效的是完整 plan→execute→verify→recover 流水线,其中恢复机制是主要贡献者 [2]。这与 mimo_smoke 观察(B3/F91 均不优于裸 B、F91 台账句级支撑率仅 0.55)形成互证。
4. 报告成文方式存在真实路线分歧:LangChain 亲测并行分节写作导致报告割裂、收敛为"研究并行、写作单次一口气"[16];STORM 与 GPT-Researcher×DeepAgents 坚持分节,但都有全局约束层兜底(大纲先行 / chief editor 审稿退回)[20][21]。**裸并行分节必然割裂,分节可行的前提是强协调产物。**
5. 引用的表面质量与事实可靠性脱节是行业级问题:前沿模型链接有效率 >94% 但事实准确率仅 39-77%,开源模型不足一半能 one-shot 产出带引用报告;检索越多引用越不准(工具调用 2→150,事实核查准确率平均 -42%)[3]。我们 mimo_smoke 的严格可核实率 0.17-0.25 不是异常值,是行业常态的弱基座端。

## 1. 闭源工业系统:两派架构,一个共识

**训练派。** OpenAI Deep Research 是在浏览任务上端到端 RL 训练的模型,不是外部编排;训练时用 CoT 模型按 ground truth 或 rubric 给回答打分 [10]。其行内引用由训练后的模型自身产出,指向来源精确位置(二手拆解)[11]。Kimi Researcher 的论据最直白:prompt-based workflow"绑定特定 LLM 版本、需随模型/环境变化频繁人工维护",所以放弃;能力几乎全部来自端到端 RL(HLE 8.6%→26.9%),工具调用格式合法性靠 **format reward** 在训练中保证,不靠 prompt 约束 [9]。Kimi 另有上下文管理机制(保留关键、丢弃无用文档)支撑单轨迹 50+ 迭代 [9]。

**编排派。** Anthropic Research 用 orchestrator-worker 多 agent,lead agent 协调并行 subagent;**引用完全剥离出研究 agent**——研究循环结束后,专门的 CitationAgent 基于"文档+报告"做事后定位 [8]。成本侧:多 agent 系统 token 约为 chat 的 15 倍,只适合高价值任务;且"模型能力是 token 效率乘数",升级基座的收益大于加倍 token 预算 [8]。Gemini Deep Research 是托管 agent:研究计划先行且用户可在执行前审改(collaborative planning),Max 版用扩展 test-time compute 迭代 reason-search-refine [12][13];官方把引用核验责任部分外置给用户(建议复核 citations 字段)[12]。Perplexity 官方描述为迭代 search-read-reason、计划随认知更新、源材料评估完后统一成文 [15];社区架构拆解进一步声称其引用在生成前就绑定进 pipeline——检索/排序层给每个 chunk 预分配 provenance record(citation_id/url/title/date/snippet),模型只输出标号,并断言"弱模型+结构化引用钩子 > 强模型+泛泛 cite your sources 指令" [14](单源推测,见"存疑与局限")。

## 2. 开源框架:编排与引用管线的具体做法

- **LangChain open_deep_research**:三阶段 Scope→Research→Write;supervisor 判断能否拆独立子题、派上下文隔离的子 agent 并行研究,可迭代补查;**最终报告由单次 LLM 调用一次性成文**(输入=brief+全部研究发现)。引用产生于每个子 agent 收尾时的清洗压缩调用("写详细回答并 citing helpful sources")[16]。
- **HuggingFace smolagents open-deep-research**:性能提升主要来自 **CodeAgent**——同一系统换成 JSON tool-calling,GAIA 验证集 55.15%→33%(-22pp);Code 动作比 JSON 平均少 30% 步数;浏览器工具刻意极简(纯文本浏览器,取自微软 Magentic-One)[17]。
- **GPT-Researcher**:planner-executor,planner 出研究问题、执行 agent 并行采集;引用在**采集侧**生成(逐资源 summarize and source-track),成文只做过滤聚合 [18]。对结构化输出配四级兜底链:json_repair→限 token 重试→降级 SMART_LLM→默认 persona [19]。2026-07 接入 LangChain Deep Agents 后**验证有效引用 18.6→35.2/篇(+89%)**,官方归因是"拉全文+返回预引用综合(pre-cited synthesis)而非搜索摘要" [20];该版本同时是分节写作的反例实现:researcher 子 agent 各写一节带引用草稿落盘,chief editor 审阅-退回修订-统一组装-参考文献去重 [20]。
- **STORM**:预写作(视角发现+模拟对话提问+大纲)/写作两阶段,"大纲先行"范式的原型;成文显式分节,每节用节标题对参考库做语义检索取证(全部引用塞不进上下文)[21]。专家评估发现主要失效模式是"红鲱鱼"(牵强关联/塞无关内容)而非事实幻觉 [22]。
- **deer-flow**(字节):1.x 为 Coordinator→Planner→Research Team→Reporter,计划节点 human-in-the-loop(自然语言改计划后执行),Reporter 末端单节点聚合成文 [23];2.0 放弃硬编码研究图、重写为通用 super-agent harness,官方推荐中档模型运行(自家 Doubao-Seed-2.0-Code 及开源的 DeepSeek v3.2/Kimi 2.5)[24]——工业界认为通用 harness + 中档(含开源)模型已是可行组合。

## 3. 编排范式:三个真问题上的行业收敛

**计划先行几乎是共识,分歧在计划是否暴露给人。** STORM(大纲)、deer-flow(Planner+HITL)、Gemini(计划可审改)、GPT-Researcher(planner 出题)都是计划先行;Perplexity/LangChain 在计划之上加"随认知更新/supervisor 迭代补查"的缺口驱动循环 [12][15][16]。纯草稿先行(TTD-DR 式)在工业系统中未见独立采用——它活在学术线里。

**分节 vs 单次成文是有条件的分歧。** LangChain 的失败教训原文:"并行分节写作快,但报告割裂,因为写节的 agent 之间协调不足;解决办法是多 agent 只做研究、写作在全部研究完成后进行" [16]。而 STORM/DeepAgents 的分节之所以可行,是因为有全局约束物:STORM 的大纲 + 每节按节标题检索,DeepAgents 的 chief editor 审稿-退回机制 [20][21]。归纳:**协调层的强度决定成文方式的自由度**;没有强协调层时,单次成文是安全默认。

**上下文隔离 + 采集侧压缩是通用解。** LangChain 子 agent 独立上下文窗口防 context clash [16];Anthropic 并行 subagent [8];Kimi 上下文管理器 [9];GPT-Researcher 逐资源摘要 [18]。共同点:原始网页内容永远不直接进入成文上下文,进入的是**带来源的压缩中间物**。

## 4. 引用可信性:四条实现路径与它们对模型能力的依赖

| 路径 | 代表 | 引用职责在哪 | 对生成模型协议遵守的依赖 |
|------|------|------------|----------------------|
| A. 生成时协议(G-Cite) | STORM、GPT-Researcher 采集侧、我们的 F9.1 | 生成模型(写作/压缩时) | **高**——这是唯一把职责压在模型自觉上的路径 |
| B. 事后归因(P-Cite) | ContextCite [4]、Anthropic CitationAgent [8] | 独立后置步骤 | 低——成文模型可以完全不管引用 |
| C. 平台层引用绑定 | Cohere citation 对象 [5]、Gemini grounding annotations [6]、Perplexity 预绑定(拆解)[14] | 检索/API 基础设施 | 极低——引用是结构化元数据(span 索引+source id),不在散文里 |
| D. 训练内化 | OpenAI [10]、Kimi format reward [9]、CaRR 引用感知奖励 [7] | 模型权重 | 无(已内化),但需训练资源 |

三条与我们直接相关的结论:

1. **G-Cite vs P-Cite 的系统评估**(四个归因数据集、零样本到 RAG 全谱):P-Cite 高覆盖+正确性有竞争力+中等延迟,G-Cite 精度优先但牺牲覆盖与速度;高风险场景**推荐检索为中心的 P-Cite 优先**,G-Cite 只留给严格论断核验类场景 [1]。
2. **引用质量的主驱动是检索,不是生成** [1]。GPT-Researcher 的 +89% 验证引用也来自"拉全文+预引用综合"而非 prompt 加严 [20]。所以把引用职责从弱生成模型上剥离,不仅可行,而且损失的是本来就不是瓶颈的那部分。
3. **表面引用质量与事实可靠性脱节是行业级**:14 模型 benchmark 里前沿模型链接有效率>94%、相关性>80%,但事实准确率仅 39-77%;不足一半开源模型能 one-shot 产出带引用报告;工具调用 2→150 时事实核查准确率平均掉 42% [3]。

## 5. 弱基座适配:行业怎么对待"协议遵守率崩"

- **scaffold collapse 有名字有实证**:2-3B 模型在复杂格式要求下直接放弃 JSON 结构(TSR=0.429),结论是"harness 的格式强制功能独立于内容生成能力"——格式必须由 harness 承担 [2]。
- **非单调现象**:轻量协议包装(minimal-shell)比裸模型(model-only)更差,出现在 3 个模型中的 2 个;有效的是完整 plan→execute→verify→recover 流水线,消融显示 planning 和 recovery 各贡献约 24.7% [2]。**中间强度的协议落在最差区间**——F9.1 的 [En] 登记协议对 MiMo 可能正是这种"minimal-shell"。
- **表达形式匹配模型分布**:同一系统 JSON tool-calling 比 CodeAgent 掉 22pp [17]——协议不是越结构化越好,是越贴近模型擅长的表达越好。
- **兜底链而非高压线**:GPT-Researcher 在每个结构化输出点配 json_repair→重试→降级→默认值 [19];Kimi 用 format reward 训练 [9];SearchSwarm(已有笔记)证明弱基座不自发委派、prompt 教不会。行业对弱模型的一致做法是**程序保证 + 修复兜底**,不是更严的 prompt。
- **头部系统的判断**:Kimi 官方以"prompt workflow 对基座版本敏感"为放弃理由 [9];Anthropic 说模型能力是 token 效率乘数 [8]——在弱基座上加重协议/预算,预期收益递减。

## 6. 对我们框架的借鉴与创新点

mimo_smoke 批的诊断结论(F91 judge 打平、严格可核实率 0.17 vs B 0.25、fact-ev 句级支撑率 0.55、耗时 2 倍)在本调研中得到完整的外部解释链:**F9.1 是 G-Cite 路径 + 弱基座,恰好同时踩中"行业回避的引用路径"和"scaffold collapse 高发区"。**

**借鉴项(按性价比排序):**

1. **P0:引用后置化(A→B 路径迁移)——新 arm 候选 F10**。研究/写作阶段完全撤掉 [En] 登记协议(让 MiMo 回到它擅长的裸写作,B 臂形态),写作后由独立 CitationAgent 步骤(可用评测通道的强模型,或 MiMo 自己+规则校验)把报告句子归因到 search_calls.jsonl 已留痕的证据池。依据:Anthropic CitationAgent [8] + P-Cite 推荐 [1] + 我们自己的数据(B 臂裸跑 judge 最高)。这保持了"机制是可信性来源"假设的可测试性,只是把机制从生成侧移到管线侧。
2. **P0:采集侧预引用(pre-cited synthesis)**。现在 search_calls.jsonl 只记 URL;改为精读后产出**带 citation_id 的压缩证据块**,写作上下文里只有预编号证据,模型引用=写标号(填空),不是自由发挥。依据:Perplexity 拆解 [14]、GPT-Researcher +89% 的归因 [20]、Cohere/Gemini 的结构化引用形态 [5][6]。这是对 MiMo"协议遵守率崩"的釜底抽薪:把要遵守的协议从"全程维护台账"降为"写个数字"。
3. **P1:verify→recover 兜底环**。F 系若保留任何结构化产物,给它配修复链(解析失败→规则修复→重试→降级),而不是靠 prompt 遵守率。依据:[2] 恢复机制贡献 ~24.7%、[19] 四级兜底。我们的 fact-v2 已发现多 URL 挤一格的解析问题——这本身就该在采集侧被 schema 校验拦住。
4. **P1:成文纪律维持单次**。LangChain 教训 [16] 与我们框架现状一致,不要动;若未来做分节,必须先有 chief-editor 级协调层 [20]。
5. **P2:红鲱鱼指标**。STORM 发现主要失效是牵强关联而非幻觉 [22]——我们 fact-v2 的"部分成立"大池子(B3 126 对、F91 139 对)可能正是红鲱鱼形态,值得在 judge 维度或 fact 分类里显式拆出"相关性"轴。

**创新点(调研到的空白):**

- **弱基座 × P-Cite 的消融没人做过**。[1] 的 P-Cite 评估用的是常规模型+归因数据集,[2] 的 harness 实验是 2-3B 玩具任务;"同一弱基座上 G-Cite 协议 vs 后置 CitationAgent vs 采集侧预引用"的三臂对照,在 DR 场景是文献空白——正好是我们框架擅长的单变量消融,且 mimo_smoke 已经有 G-Cite 臂的基线数据。
- **"协议强度-基座能力"交互曲线**。[2] 的非单调现象(裸→轻协议→完整流水线)只在 2-3B 上验证;MiMo 量级(推理型中档模型)上这条曲线长什么样,我们有 B(裸)/B3(轻)/F91(重)三个点了,补一个"重协议+兜底环"的点就能画出来。

## 存疑与局限

- **Perplexity 引用预绑定机制**([14],台账#21/#22)是社区拆解,非官方证实;机制合理且与 Cohere/Gemini 公开 API 形态一致,但"是否为 Perplexity 真实实现"属推测。
- **scaffold collapse/非单调现象**([2])实验只覆盖 2-3B 模型和 24 个受控任务,外推到 MiMo(中档推理模型)+开放式 DR 任务是类比不是证明——这正是上面创新点 2 要补的实验。
- **G-Cite vs P-Cite 评估**([1])在归因数据集上做,不是端到端 DR 场景;其"P-Cite 优先"建议移植到 DR 需打折。
- OpenAI/Gemini 内部机制细节闭源,行内引用如何产生([11])为二手拆解。
- 单源数字:+89% 验证引用 [20]、-22pp JSON vs Code [17] 均无第三方复现。

## 参考来源

[1] Generation-Time vs. Post-hoc Citation: A Holistic Evaluation of LLM Attribution — https://arxiv.org/html/2509.21557
[2] It's Not the Size: Harness Design Determines Operational Stability in Small Language Models — https://arxiv.org/pdf/2605.12129
[3] Cited but Not Verified: Parsing and Evaluating Source Attribution in LLM Deep Research Agents — https://doi.org/10.48550/arxiv.2605.06635
[4] ContextCite (MIT, NeurIPS 2024) — https://github.com/MadryLab/context-cite
[5] Cohere RAG Citations — https://docs.cohere.com/docs/rag-citations
[6] Gemini Grounding with Google Search — https://ai.google.dev/gemini-api/docs/interactions/google-search
[7] Chaining the Evidence: Citation-Aware Rubric Rewards (CaRR) — https://arxiv.org/abs/2601.06021
[8] How we built our multi-agent research system (Anthropic) — https://www.anthropic.com/engineering/multi-agent-research-system
[9] Kimi-Researcher: End-to-End RL Training for Emerging Agentic Capabilities — https://moonshotai.github.io/Kimi-Researcher/
[10] OpenAI Deep Research System Card — https://cdn.openai.com/deep-research-system-card.pdf
[11] How OpenAI's Deep Research Works (PromptLayer,二手) — https://blog.promptlayer.com/how-deep-research-works/
[12] Gemini Deep Research Agent docs — https://ai.google.dev/gemini-api/docs/deep-research
[13] Introducing Deep Research and Deep Research Max (Google) — https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/
[14] Perplexity deep research pipeline teardown(社区拆解,二手) — https://gist.github.com/Co-Messi/bfcfb39eede5c6bc2fadd2c04139a136
[15] Introducing Perplexity Deep Research — https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research
[16] Open Deep Research (LangChain) — https://www.langchain.com/blog/open-deep-research
[17] Open-source DeepResearch – Freeing our search agents (HuggingFace) — https://huggingface.co/blog/open-deep-research
[18] GPT-Researcher — https://github.com/assafelovic/gpt-researcher
[19] GPT-Researcher Query Planning (DeepWiki,二手) — https://deepwiki.com/assafelovic/gpt-researcher/9.1-query-planning-and-decomposition
[20] GPT-Researcher × Deep Agents README — https://github.com/assafelovic/gpt-researcher/blob/main/deep_agents/README.md
[21] STORM: Assisting in Writing Wikipedia-like Articles From Scratch — https://arxiv.org/abs/2402.14207
[22] Stanford STORM Research Project — https://storm-project.stanford.edu/research/storm/
[23] deer-flow 1.x README — https://github.com/bytedance/deer-flow/tree/main-1.x
[24] deer-flow (2.0) README — https://github.com/bytedance/deer-flow

---
引用回查:24 个来源中 23 个通过,1 个修正([24]"开源模型"表述过度引申,已改为"中档模型(自家 Doubao-Seed 及开源 DeepSeek/Kimi)")。承重来源 [1][2][3][8][9][14][16][17][20] 及全部关键数字均经重新拉取原页确认。
