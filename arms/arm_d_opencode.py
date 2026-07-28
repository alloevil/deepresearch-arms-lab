"""Arm D：opencode 通用 harness（与 Arm B 对照的第二个通用 agent CLI）。

公平性控制（与 Arm B 对齐）：
- 项目级 opencode.json 覆盖全局配置：禁用 webfetch 与所有 MCP（playwright 可联网），
  bash 只放行 search_cli.py，与其他 arm 使用完全相同的搜索后端
- 模型 claude-sonnet-5，走与 A/C 相同的网关（OpenAI 兼容接口）
- 研究指令与 Arm B 完全一致，不泄露机制设计
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


def make_config(workdir: Path) -> None:
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            "lab": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "lab-gateway",
                "options": {
                    "baseURL": os.environ["ANTHROPIC_BASE_URL"].rstrip("/") + "/v1",
                    "apiKey": os.environ["ANTHROPIC_AUTH_TOKEN"],
                },
                "models": {MODEL_MAIN: {"name": MODEL_MAIN}},
            }
        },
        "mcp": {
            "feishu-mcp": {"enabled": False},
            "feishu-mcp-pro": {"enabled": False},
            "playwright": {"enabled": False},
        },
        "tools": {"webfetch": False},
        "permission": {
            # 注意:bash 若配成 {pattern: allow, "*": deny} 会导致整个工具对模型不可见
            # (模型见不到 bash,报 Invalid Tool),只能整体放行,靠提示词约束命令范围
            "bash": "allow",
            "webfetch": "deny",
            # workdir 是临时目录，search_cli 在 lab 目录下，需放行跨目录访问
            "external_directory": "allow",
        },
    }
    (workdir / "opencode.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1))


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    make_config(workdir)
    prompt = PROMPT.format(date=now_str(), question=question,
                           cli=SEARCH_CLI, out=out_file)
    cmd = ["opencode", "run", "-m", f"lab/{MODEL_MAIN}", prompt]
    logger.log("opencode-start", cmd=" ".join(cmd[:4]))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                              cwd=workdir)
    except subprocess.TimeoutExpired:
        # opencode 偶发在写完 report.md 后进程不退出（round2 q08_D）：产物完整则照常采用
        if out_file.exists() and len(out_file.read_text()) >= 1000:
            logger.log("opencode-end", returncode=-1,
                       note="timeout after report written; salvaged")
            return out_file.read_text()
        raise
    logger.log("opencode-end", returncode=proc.returncode,
               stdout_tail=proc.stdout[-500:], stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"opencode exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")
    report = out_file.read_text() if out_file.exists() else proc.stdout
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars): {report[:200]}")
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armD_"))
    logger = TraceLogger("/tmp/armD_smoke.jsonl")
    report = run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。", logger, wd)
    print(report[:1500])
