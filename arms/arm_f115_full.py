"""Arm F11.5:全栈合成 = 预引用研究 → 无网写作 → 后置核修。

三件已单独验证的机制的叠加(2026-07-24):
- F114-split(研究/写作分离+预引用):judge 8.83 + 子句级 0.68,残留错误
  = 错位 6 / 矛盾 8 / 超写 8(3题108对);
- F10.2 核修工序(十对配对实测):专修错位改指向/超写弱化/矛盾修正,
  净代价仅 −0.15 judge(噪声内),verify 零 fallback。
F115 = F114 原样跑完后,对渲染后的报告加一道 F102 核修(候选池来自本 run
search_calls.jsonl,渲染报告已带"[n]+参考来源"形态,PROMPT_VERIFY 兼容)。
兜底:核修产物塌缩(<70%)→ 保留 F114 原报告。
目标:judge ~8.7+(核修代价内)且子句级 0.68→0.75 档(错位/矛盾被修掉)。
对照:F115 vs F114 = +核修工序单变量(与 F102 vs B 同型)。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from arms.arm_f10_postcite import SEARCH_CLI, _claude, _url_pool  # noqa: E402
from arms.arm_f102_postverify import PROMPT_VERIFY  # noqa: E402 — 逐字复用
from arms.arm_f114_precite import run as run_f114  # noqa: E402


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    if os.environ.get("LAB_CLOSED_BOOK"):
        return run_f114(question, logger, workdir)

    # 阶段 1+2:F114 原样(研究→无网写作→渲染),产出 report.md
    report = run_f114(question, logger, workdir)
    out_file = workdir / "report.md"
    draft_copy = workdir / "prerepair.md"      # 核修前版本留档(配对分析用)
    draft_copy.write_text(report)

    # 阶段 3:F102 式核修(同执行器模型;候选池=本 run 实际读过的页)
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))
    pool = _url_pool(workdir)
    logger.log("repair-pool", n=pool.count("\n") + 1)
    try:
        prompt = PROMPT_VERIFY.format(date=now_str(), draft=draft_copy,
                                      url_pool=pool, cli=SEARCH_CLI,
                                      out=out_file)
        _claude(prompt, workdir, logger, "repair",
                f"Bash(python3 {SEARCH_CLI} *),Write,Read,Edit", timeout, 80)
        repaired = out_file.read_text() if out_file.exists() else ""
        if len(repaired) >= max(1000, int(len(report) * 0.7)):
            logger.log("repair-ok", before=len(report), after=len(repaired))
            return repaired
        logger.log("repair-fallback", reason="output collapsed",
                   after=len(repaired))
    except Exception as e:  # noqa: BLE001
        logger.log("repair-fallback", reason=str(e)[:200])
    out_file.write_text(report)
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF115_"))
    logger = TraceLogger("/tmp/armF115_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
