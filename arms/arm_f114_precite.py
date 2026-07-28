"""Arm F11.4:研究-写作分离 + 采集侧预引用(F11 的架构级改进)。

诊断链(2026-07-23/24):
- F11:fact 最好(子句级 0.75,n=10)但 judge 6.75——裁判归因全是检索覆盖洞
  ("日韩空白""单源依赖"),不是写作质量;
- F111/F112/F113 三次写作侧扰动全部劣化 fact——共性:都在给同一个写作 pass
  加码(广度/双通道/粒度),超出 MiMo 单 pass 认知负荷;
- 行业已验证但未在 F11 上用过的解法:研究/写作分离(LangChain ODR 亲测:
  并行分节写作割裂 → 收敛为"研究归研究、写作单次成文")+ 预引用笔记
  (GPT-Researcher +89% 验证引用的机制:pre-cited synthesis)。

F11.4 机制(两阶段,均执行器 MiMo):
1. 研究阶段:只检索+精读,LAB_PRECITE 照常发 [Sn] 编号;检索广度纪律放在
   这里(每子话题≥2 不同网站、检索失败换英文重试)——广度要求不再与写作
   争夺认知预算(F111 的教训);产物 notes.md(每来源要点,关键数字逐字
   摘录——F9 quote 纪律的轻量版);不写报告。
2. 写作阶段:**无检索工具(只有 Read/Write/Edit)**——"没读过不得写"从
   prompt 约束升级为物理约束;输入=题目+notes.md,引用=从笔记抄 [Sn] 标号,
   写作认知负荷降到最低;渲染与 F11 逐字共用。
兜底:notes.md 缺失/过短或来源<3 → 回退纯 F11 单 pass(recovery 原则)。
对照:F114 vs F11 = 架构单变量(单 pass vs 研究写作分离)。
目标:judge 回 8 档(覆盖洞被专职研究阶段补上)且子句级 ≥0.75(标号从紧凑
笔记抄,错标风险低于满页原文——F111 错位回潮的反向修复)。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from arms.arm_f10_postcite import SEARCH_CLI, _claude  # noqa: E402
from arms.arm_f11_precite import _render  # noqa: E402 — 渲染逐字共用

PROMPT_RESEARCH = """今天是 {date}。你是一名研究员,现在只做研究任务的【资料采集】阶段——不写报告,只产出结构化研究笔记,供后续写作阶段使用。

【研究任务】
{question}

【可用工具】只能用这两个命令联网(内置网页搜索不可用):
- python3 {cli} search "中文查询词" —— 搜索,返回 JSON 结果
- python3 {cli} read "URL" —— 读取网页正文。每个成功读取的页面开头会给出
  该页的来源编号,如【本页来源编号 [S3]】。

【采集纪律】
1. 【广度优先】把任务拆成子话题逐一检索;每个子话题争取精读 2 个不同网站的
   页面;某个子话题/地区/主体检索不到时,必须换语言(英文)、换措辞再试至少
   一次,确实找不到才在笔记中记录"该子话题未获来源"。
2. 【单源上限】不要让任何一个来源支撑超过三分之一的笔记内容。
3. 【逐字摘录】关键数字、日期、金额、排名、直接引语必须从页面原文逐字抄进
   笔记,不得凭记忆改写。

【产出】把研究笔记完整写入 {notes}(只写笔记),格式:
## 子话题名
- [S3] 要点一句话(含逐字摘录的关键数字/日期)
- [S3] 另一个要点
- [S7] ...
## 未获来源的子话题
- xxx(已尝试中英文检索)

笔记要覆盖任务的全部子话题,信息密度优先。"""

PROMPT_WRITE = """今天是 {date}。你是一名研究报告撰写人。研究员已完成资料采集,笔记在 {notes}(用 Read 工具读取)。请基于笔记撰写最终研究报告。

【研究任务】
{question}

【写作规则】
1. 【只写笔记里有的】报告中的事实内容只能来自笔记;笔记标注"未获来源"的
   子话题,在报告中如实说明检索局限,不得用你自己的知识填补具体数字、日期
   或事实细节。
2. 【引用方式】事实论断句末标注笔记中该要点的来源编号,如「……出货量达
   5 GWh[S3]。」一句可标多个编号[S2][S5]。**不要写任何 URL,不要自编编号**。
3. 报告不需要"参考来源"一节——系统会根据编号自动生成;
4. 报告用 Markdown:分节结构清晰、每个主体章节内容充实(综合笔记中该子话题
   的全部要点,做对比与机制分析)、结论明确;分析与评估是你的职责,但分析
   所依据的事实都要标编号。
5. 把最终报告完整写入 {out}(只写报告本身)。"""


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    notes_file = workdir / "notes.md"
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))

    if os.environ.get("LAB_CLOSED_BOOK"):
        from arms.arm_f11_precite import run as run_f11
        return run_f11(question, logger, workdir)

    # 阶段 1:专职研究(广度纪律在此;max_turns 90——广度结构性多耗轮次)
    prompt = PROMPT_RESEARCH.format(date=now_str(), question=question,
                                    cli=SEARCH_CLI, notes=notes_file)
    _claude(prompt, workdir, logger, "research",
            f"Bash(python3 {SEARCH_CLI} *),Write,Read", timeout, 90,
            extra_env={"LAB_PRECITE": "1"})
    notes = notes_file.read_text() if notes_file.exists() else ""
    mp_f = workdir / "precite_map.json"
    mp = json.loads(mp_f.read_text()) if mp_f.exists() else {}
    logger.log("research-done", notes_chars=len(notes), sources=len(mp))

    if len(notes) < 800 or len(mp) < 3:
        # 兜底:研究阶段产出不合格 → 回退纯 F11 单 pass
        logger.log("research-fallback", reason="notes/sources insufficient")
        from arms.arm_f11_precite import run as run_f11
        return run_f11(question, logger, workdir)

    # 阶段 2:无网写作("没读过不得写"物理化——写作 agent 无检索工具)
    prompt = PROMPT_WRITE.format(date=now_str(), question=question,
                                 notes=notes_file, out=out_file)
    _claude(prompt, workdir, logger, "write", "Read,Write,Edit", timeout, 40)
    report = out_file.read_text() if out_file.exists() else ""
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars)")

    final = _render(report, mp, logger)
    out_file.write_text(final)
    return final


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF114_"))
    logger = TraceLogger("/tmp/armF114_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
