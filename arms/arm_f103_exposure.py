"""Arm F10.3:F10.2 + 核修阶段曝光加大(exposure-scaled verify)。

单变量依据(arXiv 2607.12257,4B 模型受控实验):引用忠实性由"单源曝光量"
决定(400→1500 字符使 faithfulness 0.45→0.58,且与来源质量无关),而覆盖由
检索决定。F10.2 十题的残留失败池 = partial 47 对(fact-v2 判"部分支持")——
假设:核修编辑 read 只见 8000 字符,论断的支持证据在截断外,核对流于表面。

F10.3 = F10.2 逐字同构,唯一差异:verify 阶段 LAB_READ_MAX=24000(3×)。
draft 阶段不动(8000,与 B/F102 同)——保持"检索侧"完全一致,只动"核对侧
曝光"这一个变量。成本:核修阶段每页 +16K 字符输入(2607.12257 报告的曝光
代价约 +235 输出 token/源,便宜)。
对照:F103 vs F102 = 核修曝光单变量。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from arms.arm_b_claude_code import PROMPT as B_PROMPT  # noqa: E402
from arms.arm_f10_postcite import SEARCH_CLI, _claude, _url_pool  # noqa: E402
from arms.arm_f102_postverify import PROMPT_VERIFY  # noqa: E402 — 逐字复用

VERIFY_READ_MAX = "24000"


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    draft_file = workdir / "draft.md"
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))

    if os.environ.get("LAB_CLOSED_BOOK"):
        from arms.arm_b_claude_code import run as run_b
        return run_b(question, logger, workdir)

    # 阶段 1:逐字 B(曝光 8000,与 F102 同)
    prompt = B_PROMPT.format(date=now_str(), question=question,
                             cli=SEARCH_CLI, out=draft_file)
    _claude(prompt, workdir, logger, "draft",
            f"Bash(python3 {SEARCH_CLI} *),Write,Read", timeout, 60)
    draft = draft_file.read_text() if draft_file.exists() else ""
    if len(draft) < 1000:
        raise RuntimeError(f"draft too short ({len(draft)} chars)")

    # 阶段 2:核修(唯一变量:read 曝光 8000→24000)
    pool = _url_pool(workdir)
    logger.log("verify-pool", n=pool.count("\n") + 1,
               read_max=VERIFY_READ_MAX)
    try:
        prompt = PROMPT_VERIFY.format(date=now_str(), draft=draft_file,
                                      url_pool=pool, cli=SEARCH_CLI,
                                      out=out_file)
        _claude(prompt, workdir, logger, "verify",
                f"Bash(python3 {SEARCH_CLI} *),Write,Read,Edit", timeout, 80,
                extra_env={"LAB_READ_MAX": VERIFY_READ_MAX})
        report = out_file.read_text() if out_file.exists() else ""
        if len(report) >= max(1000, int(len(draft) * 0.7)):
            logger.log("verify-ok", draft_chars=len(draft),
                       final_chars=len(report))
            return report
        logger.log("verify-fallback", reason="output collapsed",
                   final_chars=len(report))
    except Exception as e:  # noqa: BLE001
        logger.log("verify-fallback", reason=str(e)[:200])
    out_file.write_text(draft)
    return draft


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF103_"))
    logger = TraceLogger("/tmp/armF103_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
