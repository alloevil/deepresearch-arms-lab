"""Arm B：Claude Code 通用 harness（强基线对照）。

用 claude -p 无头模式跑研究任务。公平性控制：
- 通过 --allowedTools 只放行 Bash(search_cli.py ...)，禁用内置 WebSearch/WebFetch，
  使其与其他 arm 使用完全相同的搜索后端
- 模型 claude-sonnet-5，与 Arm A/C 主模型同档
- 研究指令只描述任务与格式要求，不泄露我们系统的机制设计（大纲判据等），
  让它按自己的通用编排方式工作——这正是"通用 harness"对照的意义
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

【可用工具】只能用这两个命令联网（内置的网页搜索不可用）：
- python3 {cli} search "中文查询词" —— 搜索，返回 JSON 结果
- python3 {cli} read "URL" —— 读取网页正文

【要求】
1. 多角度充分检索后再写作，重要论断标注来源 URL；
2. 报告用 Markdown，含分节结构和"参考来源"一节；
3. 把最终报告完整写入文件 {out}（只写报告本身）。"""

# 闭卷评测（LAB_CLOSED_BOOK）专用：不给检索工具也不提检索——
# 探针实测两个原因缺一不可：①agent 反编造行为学会因"检索不可用"拒写，
# 测不出参数化知识水位，必须明说这是闭卷评测；②闭卷下 agent 无事可检索，
# 会尝试白名单外命令（ls 等）被拒后放弃，干脆不放行 Bash
PROMPT_CLOSED = """今天是 {date}。这是一次闭卷评测：联网检索不可用。请仅凭你自身已有的知识完成下面的深度研究任务，产出一份中文研究报告。

【研究任务】
{question}

【要求】
1. 直接基于你已有的知识写作，不要尝试联网或调用任何命令行工具；
2. 不确定的数字、日期与最新进展要如实标注不确定性，不要编造具体的引用 URL；
   可以提及机构名与报告名；
3. 报告用 Markdown，含分节结构与明确结论；
4. 把最终报告完整写入文件 {out}（只写报告本身）。"""


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    closed = bool(os.environ.get("LAB_CLOSED_BOOK"))
    if closed:
        prompt = PROMPT_CLOSED.format(date=now_str(), question=question,
                                      out=out_file)
        allowed = "Write,Read"
    else:
        prompt = PROMPT.format(date=now_str(), question=question,
                               cli=SEARCH_CLI, out=out_file)
        allowed = f"Bash(python3 {SEARCH_CLI} *),Write,Read"
    cmd = ["claude", "-p", prompt,
           "--model", MODEL_MAIN,
           "--allowedTools", allowed,
           "--disallowedTools", "WebSearch,WebFetch,Task",
           "--max-turns", "60"]
    env = dict(os.environ)
    # ~/.claude/settings.json 的 env 块会覆盖进程环境变量，须用 --settings（优先级最高）改网关
    if os.environ.get("LAB_CLAUDE_BASE_URL"):
        env["ANTHROPIC_BASE_URL"] = os.environ["LAB_CLAUDE_BASE_URL"]
        sf = workdir / "claude_settings.json"
        sf.write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": os.environ["LAB_CLAUDE_BASE_URL"],
            "ANTHROPIC_AUTH_TOKEN": os.environ["ANTHROPIC_AUTH_TOKEN"],
        }}))
        cmd += ["--settings", str(sf)]
    logger.log("claude-code-start", cmd=" ".join(cmd[:4]))
    # 超时按执行器校准:sonnet 典型 ~700s,默认 1800 够用;MiMo 推理税 4-6×,
    # B3 常态 760-1105s,q08_B3 实测 1825s 顶穿被杀 → env_mimo.sh 放宽 3600
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          cwd=workdir, env=env)
    logger.log("claude-code-end", returncode=proc.returncode,
               stdout_tail=proc.stdout[-500:], stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")
    report = out_file.read_text() if out_file.exists() else proc.stdout
    # 认证失败等错误会以短文本形式出现在 stdout，不能当作报告
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars): {report[:200]}")
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armB_"))
    logger = TraceLogger("/tmp/armB_smoke.jsonl")
    report = run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。", logger, wd)
    print(report[:1500])
