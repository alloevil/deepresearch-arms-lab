"""Arm F10.2:B + 后置引用核修(post-hoc verify & repair)。

设计翻转依据(F10/F10.1 三题实证,2026-07-20):
- F10(撤引用职责+补挂):精度 0.72 但覆盖塌缩,judge −1.4;
- F10.1(+检索纪律):覆盖回升但核对吞吐不变 → partial 激增,精度掉回 0.53;
- 共同教训:**替换** B 的引用职责总在跷跷板上;而 B 的 judge 8.96 无人能敌,
  其 fact 弱点(21 超写+13 矛盾)恰是"可修复池"。
F10.2 = 原封不动的 B(draft 阶段带引用写作)+ 核修编辑(不新增引用职责,
只核对修复既有引用:错位改指向/强度不符弱化/不可核标[未证实])。
这是 Anthropic CitationAgent 的原始形态——叠加在强 harness 之上而非替代。
对照关系:F102 vs B = 单变量(+后置核修一道工序)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from arms.arm_b_claude_code import PROMPT as B_PROMPT  # noqa: E402 — draft=B 逐字同构
from arms.arm_f10_postcite import (  # noqa: E402 — 复用基础设施
    SEARCH_CLI, _claude, _url_pool)

PROMPT_VERIFY = """今天是 {date}。你是一名引用核对编辑。研究员已完成带引用的研究报告 {draft}（用 Read 工具读取）。你的任务是核对并修复报告中的引用，输出定稿。

【候选来源池】（研究员实际检索/阅读过的页面,供交叉核对与替换来源用）
{url_pool}

【可用工具】
- python3 {cli} read "URL" —— 读取网页正文（核对用）
- Read/Write —— 读初稿、写定稿

【工作方法】
1. 通读报告,找出全部【关键事实论断】（数字/日期/金额/排名/点名主体/直接引语）
   及其标注的来源。
2. 逐条用 read 打开被引用的页面核对：
   - 页面支持论断 → 保留不动；
   - 论断措辞强度超过页面（页面"计划/预计",论断"已经/将"）→ 弱化措辞；
   - 页面不支持该论断 → 在候选池找正确来源替换；找不到则去掉该引用并在
     句末标注 [未证实]，或删去无据的具体数字/日期；
   - 引用 URL 打不开 → 尝试候选池同主题来源替换；无替换则标 [未证实]。
3. 没有标注来源的关键论断：若候选池能核实,补挂来源;不能则弱化或标 [未证实]。
4. 除引用修复与措辞弱化外，不得改动报告结构、内容组织与结论；参考来源节
   同步更新（只列正文实际引用的来源）。
5. 【引用格式】定稿采用统一形态：正文中被支持的论断句末标 [n]（同一来源
   复用同一编号），文末"## 参考来源"节按 "[n] 标题 — URL" 一行一条列出。
   不要把引用只放在文末而正文无标记。

把定稿完整写入 {out}（只写报告本身）。"""


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    import os
    out_file = workdir / "report.md"
    draft_file = workdir / "draft.md"
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))

    if os.environ.get("LAB_CLOSED_BOOK"):
        from arms.arm_b_claude_code import run as run_b
        return run_b(question, logger, workdir)  # 闭卷=纯 B

    # 阶段 1:逐字 B(唯一差异:产物先落 draft.md)
    prompt = B_PROMPT.format(date=now_str(), question=question,
                             cli=SEARCH_CLI, out=draft_file)
    _claude(prompt, workdir, logger, "draft",
            f"Bash(python3 {SEARCH_CLI} *),Write,Read", timeout, 60)
    draft = draft_file.read_text() if draft_file.exists() else ""
    if len(draft) < 1000:
        raise RuntimeError(f"draft too short ({len(draft)} chars)")

    # 阶段 2:核修编辑(同执行器模型)。曝光维持默认 8K:扩容配对消融
    # (2026-07-21,n=8 题)显示 24K 平均收益≈零(严格率 0.30→0.33,矛盾反增),
    # q09 首对的大幅增益未复现;需要时经 LAB_READ_MAX 显式开启
    pool = _url_pool(workdir)
    logger.log("verify-pool", n=pool.count("\n") + 1)
    try:
        prompt = PROMPT_VERIFY.format(date=now_str(), draft=draft_file,
                                      url_pool=pool, cli=SEARCH_CLI,
                                      out=out_file)
        _claude(prompt, workdir, logger, "verify",
                f"Bash(python3 {SEARCH_CLI} *),Write,Read,Edit", timeout, 80)
        report = out_file.read_text() if out_file.exists() else ""
        # 合格判据:长度不塌缩(核修不该砍内容)
        if len(report) >= max(1000, int(len(draft) * 0.7)):
            logger.log("verify-ok", draft_chars=len(draft),
                       final_chars=len(report))
            return report
        logger.log("verify-fallback", reason="output collapsed",
                   final_chars=len(report))
    except Exception as e:  # noqa: BLE001
        logger.log("verify-fallback", reason=str(e)[:200])
    out_file.write_text(draft)   # 兜底:退回纯 B 产物(仍是合格报告)
    return draft


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF102_"))
    logger = TraceLogger("/tmp/armF102_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
