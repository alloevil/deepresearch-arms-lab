"""Arm B2：Claude Code + 子 agent 委派（对照 B 的单变量：放开 Task 工具）。

动机：SearchSwarm 称委派编排对强基座 +10 分（BrowseComp），但那是短答案深搜；
长报告场景下委派的增量从未被同后端同题对照过。B 一直 --disallowedTools Task，
B2 仅放开 Task 并在提示中告知可用，其余与 B 完全一致。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import MODEL_MAIN, TraceLogger, now_str  # noqa: E402

LAB = Path(__file__).resolve().parent.parent
SEARCH_CLI = LAB / "common" / "search_cli.py"

PROMPT = """今天是 {date}。你是一名研究员，请完成下面的深度研究任务，产出一份带来源引用的中文研究报告。

【研究任务】
{question}

【可用工具】联网只能用这两个命令（内置的网页搜索不可用）：
- python3 {cli} search "中文查询词" —— 搜索，返回 JSON 结果
- python3 {cli} read "URL" —— 读取网页正文
你可以使用 Task 工具把独立的子主题调查委派给子 agent 并行处理（子 agent 使用
同样的搜索命令）；委派时给出详尽 brief（任务、原因、已确认、待查、已排除）。

【要求】
1. 多角度充分检索后再写作，重要论断标注来源 URL；
2. 报告用 Markdown，含分节结构和"参考来源"一节；
3. 把最终报告完整写入文件 {out}（只写报告本身）。"""


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    prompt = PROMPT.format(date=now_str(), question=question,
                           cli=SEARCH_CLI, out=out_file)
    cmd = ["claude", "-p", prompt,
           "--model", MODEL_MAIN,
           "--allowedTools", f"Bash(python3 {SEARCH_CLI} *),Write,Read,Task",
           "--disallowedTools", "WebSearch,WebFetch",
           "--max-turns", "80"]
    env = dict(os.environ)
    if os.environ.get("LAB_CLAUDE_BASE_URL"):
        env["ANTHROPIC_BASE_URL"] = os.environ["LAB_CLAUDE_BASE_URL"]
        sf = workdir / "claude_settings.json"
        sf.write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": os.environ["LAB_CLAUDE_BASE_URL"],
            "ANTHROPIC_AUTH_TOKEN": os.environ["ANTHROPIC_AUTH_TOKEN"],
        }}))
        cmd += ["--settings", str(sf)]
    logger.log("claude-code-start", cmd=" ".join(cmd[:4]), delegation=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=2400,
                          cwd=workdir, env=env)
    logger.log("claude-code-end", returncode=proc.returncode,
               stdout_tail=proc.stdout[-500:], stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")
    report = out_file.read_text() if out_file.exists() else proc.stdout
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars): {report[:200]}")
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armB2_"))
    logger = TraceLogger("/tmp/armB2_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
