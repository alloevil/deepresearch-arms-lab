"""Arm F10：引用后置化（post-hoc citation，路径 B/P-Cite）。

设计依据（research-dr-mainstream-20260720.md,2026-07-20 调研）：
- mimo_smoke 实证:F9.1 生成时台账协议在 MiMo 上收益归零(judge 打平、严格
  可核实率 0.17 vs B 0.25、fact-ev 句级支撑率 0.55、耗时 2×);
- 行业无人走"模型写作时自觉遵守引用协议"路:Anthropic 用后置 CitationAgent
  (引用与研究/写作解耦);G-Cite vs P-Cite 系统评估(arXiv 2509.21557)推荐
  高风险场景 P-Cite 优先,且引用质量主驱动是检索而非生成模型能力;
- 弱基座机理(arXiv 2605.12129):轻量协议包装比裸模型更差(非单调),格式
  强制应由 harness 承担。

机制(两阶段,均在执行器通道跑 MODEL_MAIN——机制侧不得偷换评测通道强模型):
1. draft:B 同构 prompt,唯一差异 = 撤掉写作侧引用职责(不标 URL、无参考
   来源节),让弱基座回到它擅长的裸写作(mimo_smoke 里 B 臂 judge 最高);
2. cite:独立"引用编辑"agent,输入 draft + 本 run search_calls.jsonl 落盘的
   URL 候选池(read 过的页优先),用 read 重开页面核对后:关键事实论断句末
   插 [n]、文末生成"参考来源"节(与 F9 渲染同形态,fact-v2 解析器已支持);
   核实不了的论断降级措辞或标[未证实]。
兜底(调研 P1:程序保证+修复兜底,不靠 prompt 遵守率):cite 阶段异常或产物
不合格 → 回退 draft 作为 report,trace 记 cite-fallback(引用缺失会诚实体现在
fact 轴,不掩盖)。

对照关系:F10 vs B = 引用职责位置单变量(B:写作时自由标 URL;F10:写作零
引用职责 + 后置绑定)。F10 vs F91 = P-Cite vs G-Cite。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import MODEL_MAIN, TraceLogger, now_str  # noqa: E402
from arms.arm_b_claude_code import PROMPT_CLOSED  # noqa: E402 — 闭卷与 B 完全同构

LAB = Path(__file__).resolve().parent.parent
SEARCH_CLI = LAB / "common" / "search_cli.py"

# 与 arm_b.PROMPT 同构,仅引用条款不同(B 第 1 条要求"重要论断标注来源 URL"、
# 第 2 条要求"参考来源"一节;此处显式豁免——这就是本消融的单变量)
PROMPT_DRAFT = """今天是 {date}。你是一名研究员，请完成下面的深度研究任务，产出一份中文研究报告。

【研究任务】
{question}

【可用工具】只能用这两个命令联网（内置的网页搜索不可用）：
- python3 {cli} search "中文查询词" —— 搜索，返回 JSON 结果
- python3 {cli} read "URL" —— 读取网页正文

【要求】
1. 多角度充分检索后再写作，事实论断要有检索依据；
2. 报告不需要标注引用或来源 URL，也不需要"参考来源"一节——引用由后续
   编辑流程统一补挂，你专注于检索充分、内容准确、写作质量；
3. 报告用 Markdown，含分节结构和明确结论；
4. 把最终报告完整写入文件 {out}（只写报告本身）。"""

PROMPT_CITE = """今天是 {date}。你是一名引用编辑。研究员已完成报告初稿 {draft}（用 Read 工具读取），初稿基于下面这些网页写成。你的任务是给报告补挂引用后输出定稿。

【候选来源池】（研究员实际检索/阅读过的页面）
{url_pool}

【可用工具】
- python3 {cli} read "URL" —— 重新读取网页正文（核对用）
- Read/Write —— 读初稿、写定稿

【工作方法】
1. 通读初稿，找出全部【关键事实论断】：具体数字、日期、金额、排名、点名
   主体的事实性陈述、直接引语。背景叙述与分析推断不需要引用。
2. 对每个关键论断，从候选池中找最可能的来源页，用 read 打开核对该论断是否
   被页面内容支持。一次可以核对同一页面上的多个论断。
3. 被支持的论断：句末插入引用标记 [n]（同一 URL 复用同一编号）。
   页面内容与论断措辞强度不符的（页面说"计划/预计"而论断写"已经/将"）：
   把论断措辞改弱到与页面一致后再标注。
   候选池核实不了的论断：不得编造来源——改写弱化（去掉具体数字/日期）或
   在句末标注 [未证实]。
4. 除上述引用插入与措辞弱化外，不得改动报告的结构、内容与结论。
5. 文末新增"## 参考来源"一节，按编号列出：[n] 页面标题或简述 — URL
   （只列正文实际引用到的编号）。

把定稿完整写入 {out}（只写报告本身）。"""


def _url_pool(workdir: Path, cap: int = 40) -> str:
    """从本 run 的 search_calls.jsonl 提取候选 URL:read 过的页优先(agent 实际
    读过,支持概率最高),其余用 search 结果补足。"""
    reads, searches = [], []
    f = workdir / "search_calls.jsonl"
    if f.exists():
        for line in f.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("kind") == "read" and e.get("url") and e.get("chars", 0) > 200:
                reads.append(e["url"])
            elif e.get("kind") == "search":
                searches.extend(e.get("urls") or [])
    pool = list(dict.fromkeys(reads))          # 去重保序
    for u in dict.fromkeys(searches):
        if len(pool) >= cap:
            break
        if u not in pool:
            pool.append(u)
    if not pool:
        return "(候选池为空)"
    mark = {u for u in reads}
    return "\n".join(f"- {u}" + ("  (已精读)" if u in mark else "")
                     for u in pool[:cap])


def _claude(prompt: str, workdir: Path, logger: TraceLogger, tag: str,
            allowed: str, timeout: int, max_turns: int,
            extra_env: dict | None = None) -> None:
    cmd = ["claude", "-p", prompt, "--model", MODEL_MAIN,
           "--allowedTools", allowed,
           "--disallowedTools", "WebSearch,WebFetch,Task",
           "--max-turns", str(max_turns)]
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    if os.environ.get("LAB_CLAUDE_BASE_URL"):
        env["ANTHROPIC_BASE_URL"] = os.environ["LAB_CLAUDE_BASE_URL"]
        sf = workdir / "claude_settings.json"
        sf.write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": os.environ["LAB_CLAUDE_BASE_URL"],
            "ANTHROPIC_AUTH_TOKEN": os.environ["ANTHROPIC_AUTH_TOKEN"],
        }}))
        cmd += ["--settings", str(sf)]
    logger.log(f"{tag}-start")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=workdir, env=env)
    logger.log(f"{tag}-end", returncode=proc.returncode,
               stdout_tail=proc.stdout[-300:], stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"claude({tag}) exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")


def run(question: str, logger: TraceLogger, workdir: Path,
        draft_prompt: str = PROMPT_DRAFT, draft_max_turns: int = 60) -> str:
    out_file = workdir / "report.md"
    draft_file = workdir / "draft.md"
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))

    # 闭卷:无检索即无候选池,引用后置化无意义 → 与 B 闭卷完全同构
    if os.environ.get("LAB_CLOSED_BOOK"):
        prompt = PROMPT_CLOSED.format(date=now_str(), question=question,
                                      out=out_file)
        _claude(prompt, workdir, logger, "draft", "Write,Read", timeout, 60)
        report = out_file.read_text() if out_file.exists() else ""
        if len(report) < 1000:
            raise RuntimeError(f"closed-book report too short ({len(report)})")
        return report

    # 阶段 1:零引用职责裸写作(B 形态)
    prompt = draft_prompt.format(date=now_str(), question=question,
                                 cli=SEARCH_CLI, out=draft_file)
    _claude(prompt, workdir, logger, "draft",
            f"Bash(python3 {SEARCH_CLI} *),Write,Read", timeout, draft_max_turns)
    draft = draft_file.read_text() if draft_file.exists() else ""
    if len(draft) < 1000:
        raise RuntimeError(f"draft too short ({len(draft)} chars)")

    # 阶段 2:后置引用绑定(CitationAgent,同执行器模型)
    pool = _url_pool(workdir)
    logger.log("cite-pool", n=pool.count("\n") + 1 if pool != "(候选池为空)" else 0)
    try:
        prompt = PROMPT_CITE.format(date=now_str(), draft=draft_file,
                                    url_pool=pool, cli=SEARCH_CLI, out=out_file)
        _claude(prompt, workdir, logger, "cite",
                f"Bash(python3 {SEARCH_CLI} *),Write,Read,Edit", timeout, 80)
        report = out_file.read_text() if out_file.exists() else ""
        # 定稿合格判据:长度不塌缩(≥draft 的 60%,防编辑砍内容)且确实插了引用
        if len(report) >= max(1000, int(len(draft) * 0.6)) and "[1]" in report:
            logger.log("cite-ok", draft_chars=len(draft), final_chars=len(report))
            return report
        logger.log("cite-fallback", reason="output unqualified",
                   final_chars=len(report), has_cite="[1]" in report)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        logger.log("cite-fallback", reason=str(e)[:200])
    # 兜底:回退裸稿(引用缺失诚实体现在 fact 轴,不掩盖不重试)
    out_file.write_text(draft)
    return draft


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF10_"))
    logger = TraceLogger("/tmp/armF10_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1500])
