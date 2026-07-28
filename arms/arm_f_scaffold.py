"""Arm F：agent 基座（Claude Code）+ workflow 机制外挂——两范式合流实验。

三层设计（对应 C 系迭代中验证有效的机制，移植为 agent 的外挂）：
1. 协议层（prompt）：硬性要求清单先行、节级完成判据、深度四要素、写前自检
2. 终检门（代码）：verify_cli 输出端核查（截断/引用/点名实体/数量要求）
3. 修订回路：验证失败项喂回 harness 做一轮修订（同工作目录，可读原报告）

与 arm B 的差异仅在协议 prompt 与终检门——B 是裸 harness 对照。
"""
import json
import os
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
4. 【深度要求】每个主体章节必须包含全部四要素：
   a) 具体数据点（数字、日期、金额）；b) 多方对比（不同主体/口径/立场并列）；
   c) 机制解释（为什么会这样，因果链条）；d) 批判性评估（数据可信度、反例、不确定性）。
5. 写作前逐条核对 checklist.md，未覆盖项回头补搜；补搜两次仍无果才允许写"证据不足"。
6. 重要论断标注来源 URL；报告用 Markdown 分节，含"参考来源"一节。

把最终报告完整写入文件 {out}（只写报告本身）。"""

REVISE_PROMPT = """你之前完成的研究报告 {out} 未通过质量验证，问题如下：

{failures}

请修订：
1. 先读取 {out} 了解现有内容；
2. 对缺失的实体/数量要求，用搜索工具补充检索（可换英文、换角度）：
   - python3 {cli} search "查询词"
   - python3 {cli} read "URL"
3. 截断的章节补写完整；修订处保持来源引用。
4. 把修订后的完整报告写回 {out}。"""


def _run_claude(prompt: str, workdir: Path, logger: TraceLogger, tag: str) -> None:
    cmd = ["claude", "-p", prompt,
           "--model", MODEL_MAIN,
           "--allowedTools", f"Bash(python3 {SEARCH_CLI} *),Write,Read,Edit",
           "--disallowedTools", "WebSearch,WebFetch,Task",
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
    logger.log(f"{tag}-start", cmd=" ".join(cmd[:4]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                          cwd=workdir, env=env)
    logger.log(f"{tag}-end", returncode=proc.returncode,
               stdout_tail=proc.stdout[-400:], stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    _run_claude(PROMPT.format(date=now_str(), question=question,
                              cli=SEARCH_CLI, out=out_file),
                workdir, logger, "draft")
    if not out_file.exists() or len(out_file.read_text()) < 1000:
        raise RuntimeError("draft report missing or too short")

    result = verify(str(out_file), question)
    logger.log("verify", **result)
    if not result["pass"]:
        failures = "\n".join(f"- {f}" for f in result["failures"])
        _run_claude(REVISE_PROMPT.format(out=out_file, failures=failures,
                                         cli=SEARCH_CLI),
                    workdir, logger, "revise")
        result2 = verify(str(out_file), question)
        logger.log("verify-after-revise", **result2)

    report = out_file.read_text()
    if len(report) < 1000:
        raise RuntimeError(f"final report too short ({len(report)} chars)")
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF_"))
    logger = TraceLogger("/tmp/armF_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商，并评估其中一家的降本路径。",
              logger, wd)[:1200])
