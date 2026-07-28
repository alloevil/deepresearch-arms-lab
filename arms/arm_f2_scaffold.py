"""Arm F2：F 的迭代版（信源多样性 + 修订分诊 + 会话续跑 + checklist 核查）。

相对 arm_f_scaffold 的改动（F 首轮 3 题失分分析 → 修法）：
1. 信源多样性：verify_cli 新增单一域名检查（q09_F 被裁判点名"过度依赖单一博客源"）
2. 修订分诊：失败类型分两类——检索类（缺实体/数量不足/信源单一）修订指令附具体
   建议搜索词；文本类（截断/重复/覆盖率）只要求改写。检索类允许第二轮修订。
3. 会话续跑：修订用 `claude -p --resume <session_id>` 延续 draft 会话——修订者
   拥有 draft 阶段全部检索上下文，而非从零读报告（F 的修订是新会话，上下文断裂）。
4. checklist 核查：终检时机械检查 workdir/checklist.md 是否存在（协议第 1 步的
   遵守情况），缺失则在修订指令中点名补建并核对。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import MODEL_MAIN, TraceLogger, now_str  # noqa: E402
from common.verify_cli import verify  # noqa: E402

LAB = Path(__file__).resolve().parent.parent
SEARCH_CLI = LAB / "common" / "search_cli.py"

PROMPT = """今天是 {date}。你是一名研究员，请完成下面的深度研究任务，产出一份带来源引用的中文研究报告。

【研究任务】
{question}

【可用工具】只能用这两个命令联网（内置的网页搜索不可用）：
- python3 {cli} search "查询词" —— 搜索，返回 JSON 结果
- python3 {cli} read "URL" —— 读取网页正文

【研究协议（必须遵守）】
1. 开始研究前，先从任务中抽取「硬性要求清单」写入 checklist.md：所有点名的实体、
   数量要求（如"各举两例"）、动作要求（对比/评估/分析）。
2. 拟报告大纲，为每节写出完成判据（需要哪些具体证据该节才算可写）。
3. 检索优先覆盖清单未满足项；某项检索不到时必须换语言（英文）、换角度再试至少一次。
4. 【信源纪律】每个主体章节的关键论断至少要有两个不同网站的来源交叉支撑；
   避免整节只引用同一个网站。
5. 【深度要求】每个主体章节必须包含全部四要素：
   a) 具体数据点（数字、日期、金额）；b) 多方对比（不同主体/口径/立场并列）；
   c) 机制解释（为什么会这样，因果链条）；d) 批判性评估（数据可信度、反例、不确定性）。
6. 写作前逐条核对 checklist.md，未覆盖项回头补搜；补搜两次仍无果才允许写"证据不足"。
7. 重要论断标注来源 URL；报告用 Markdown 分节，含"参考来源"一节。

把最终报告完整写入文件 {out}（只写报告本身）。"""

REVISE_PROMPT = """你之前完成的研究报告 {out} 未通过质量验证，问题如下：

{failures}
{search_hints}
请修订：
1. 先读取 {out} 了解现有内容（如你已有上下文可跳过）；
2. 检索类问题用搜索工具补充证据（可换英文、换角度）：
   - python3 {cli} search "查询词"
   - python3 {cli} read "URL"
3. 文本类问题（截断/重复/覆盖率）直接改写对应章节；
4. 把修订后的完整报告写回 {out}。"""

RETRIEVAL_PAT = re.compile(r"未在报告中出现|实质分析了|单一域名|checklist")


def _classify(failures: list[str]) -> tuple[list[str], list[str]]:
    retrieval = [f for f in failures if RETRIEVAL_PAT.search(f)]
    textual = [f for f in failures if f not in retrieval]
    return retrieval, textual


def _search_hints(retrieval_fails: list[str]) -> str:
    if not retrieval_fails:
        return ""
    hints = []
    for f in retrieval_fails:
        m = re.search(r"「(.+?)」", f)
        if m:
            ent = m.group(1)
            hints.append(f'- 针对「{ent}」可尝试：search "{ent} 2025 2026"、'
                         f'search "{ent}" 的英文译名')
    return ("\n【建议搜索词】\n" + "\n".join(hints) + "\n") if hints else ""


def _run_claude(prompt: str, workdir: Path, logger: TraceLogger, tag: str,
                resume: str | None = None) -> str | None:
    """跑一次 claude -p，返回 session_id（供后续 --resume）。"""
    cmd = ["claude", "-p", prompt, "--model", MODEL_MAIN,
           "--output-format", "json",
           "--allowedTools", f"Bash(python3 {SEARCH_CLI} *),Write,Read,Edit",
           "--disallowedTools", "WebSearch,WebFetch,Task",
           "--max-turns", "80"]
    if resume:
        cmd += ["--resume", resume]
    env = dict(os.environ)
    if os.environ.get("LAB_CLAUDE_BASE_URL"):
        env["ANTHROPIC_BASE_URL"] = os.environ["LAB_CLAUDE_BASE_URL"]
        sf = workdir / "claude_settings.json"
        sf.write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": os.environ["LAB_CLAUDE_BASE_URL"],
            "ANTHROPIC_AUTH_TOKEN": os.environ["ANTHROPIC_AUTH_TOKEN"],
        }}))
        cmd += ["--settings", str(sf)]
    logger.log(f"{tag}-start", resume=bool(resume))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                          cwd=workdir, env=env)
    session_id = None
    try:
        d = json.loads(proc.stdout)
        if isinstance(d, list):    # --output-format json 输出事件数组,init 事件含 session_id
            for ev in d:
                if isinstance(ev, dict) and ev.get("session_id"):
                    session_id = ev["session_id"]
                    break
        elif isinstance(d, dict):
            session_id = d.get("session_id")
    except json.JSONDecodeError:
        pass
    logger.log(f"{tag}-end", returncode=proc.returncode, session=session_id,
               stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")
    return session_id


def _verify_plus(out_file: Path, question: str, workdir: Path) -> dict:
    result = verify(str(out_file), question)
    if not (workdir / "checklist.md").exists():
        result["failures"].append(
            "研究协议要求的 checklist.md 未创建——请补建硬性要求清单并逐项核对报告")
        result["pass"] = False
    return result


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    session = _run_claude(PROMPT.format(date=now_str(), question=question,
                                        cli=SEARCH_CLI, out=out_file),
                          workdir, logger, "draft")
    if not out_file.exists() or len(out_file.read_text()) < 1000:
        raise RuntimeError("draft report missing or too short")

    for attempt in (1, 2):
        result = _verify_plus(out_file, question, workdir)
        logger.log(f"verify-{attempt}", **result)
        if result["pass"]:
            break
        retrieval, textual = _classify(result["failures"])
        if attempt == 2 and not retrieval:
            break   # 第二轮只为检索类问题保留
        failures = "\n".join(f"- {f}" for f in retrieval + textual)
        session = _run_claude(
            REVISE_PROMPT.format(out=out_file, failures=failures,
                                 search_hints=_search_hints(retrieval),
                                 cli=SEARCH_CLI),
            workdir, logger, f"revise-{attempt}", resume=session) or session

    report = out_file.read_text()
    if len(report) < 1000:
        raise RuntimeError(f"final report too short ({len(report)} chars)")
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF2_"))
    logger = TraceLogger("/tmp/armF2_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商，并评估其中一家的降本路径。",
              logger, wd)[:1200])
