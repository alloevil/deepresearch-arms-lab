"""Arm E：Codex CLI 通用 harness（第三个通用 agent CLI 对照）。

公平性控制（与 Arm B/D 对齐）：
- 独立 CODEX_HOME，屏蔽用户全局配置（gpt-5.5、MCP servers 等）
- 模型 claude-sonnet-5，走与 A/C 相同的网关（wire_api=chat 即 OpenAI 兼容接口）
- 无内置 web 工具；沙箱 workspace-write 但放行网络，使 search_cli 可达
- 研究指令与 Arm B/D 完全一致
"""
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

CONFIG_TOML = """model = "{model}"
model_provider = "lab"
web_search = "disabled"

[model_providers.lab]
name = "lab-gateway"
base_url = "{base_url}"
env_key = "ANTHROPIC_AUTH_TOKEN"
wire_api = "responses"

[sandbox_workspace_write]
network_access = true
"""


def make_home(workdir: Path) -> Path:
    home = workdir / "codex_home"
    home.mkdir(exist_ok=True)
    base_url = os.environ["ANTHROPIC_BASE_URL"].rstrip("/") + "/v1"
    (home / "config.toml").write_text(
        CONFIG_TOML.format(base_url=base_url, model=MODEL_MAIN))
    return home


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    home = make_home(workdir)
    prompt = PROMPT.format(date=now_str(), question=question,
                           cli=SEARCH_CLI, out=out_file)
    last_msg = workdir / "last_message.txt"
    cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral",
           # bwrap 沙箱会导致部分命令请求提权,而 exec 模式 approval=Never 直接拒绝
           # (round2 4/10 失败),故关沙箱,工具约束与 arm D 同为软约束(报告需注明)
           "-C", str(workdir), "-s", "danger-full-access",
           "-o", str(last_msg), prompt]
    env = {**os.environ, "CODEX_HOME": str(home)}
    logger.log("codex-start", cmd=" ".join(cmd[:4]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                          cwd=workdir, env=env)
    logger.log("codex-end", returncode=proc.returncode,
               stdout_tail=proc.stdout[-500:], stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"codex exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")
    report = out_file.read_text() if out_file.exists() else (
        last_msg.read_text() if last_msg.exists() else proc.stdout)
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars): {report[:200]}")
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armE_"))
    logger = TraceLogger("/tmp/armE_smoke.jsonl")
    report = run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。", logger, wd)
    print(report[:1500])
