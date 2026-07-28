"""Arm F11.3:采集侧预引用 + 原子句写作(一句一事实)。

partial 成因诊断(2026-07-23):F11 配对级严格率 0.58 被 worst-of 聚合系统性
压低——27 个 partial 平均打包 5.1 子句/对,对内子句实际支持 0.63,13/27 是
"仅 1 子句未达标"就整对判 partial;子句级 F11 早已 0.78-0.84。

F11.3 单变量修改(仅引用条款加原子句约束;预引用机制/渲染逐字不动):
- 一句话只陈述一个可独立核验的事实,避免把多个数据点/时间点堆进一个长句;
- 一个 [Sn] 标注管一个事实,不要一句尾巴挂多事实共享一个标号。
预期:配对粒度逼近子句粒度 → 配对严格率 0.58→逼近 0.78,可信性零风险
(不放松"没读过不得写")。对照:F113 vs F11 = 句子粒度单变量。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from arms.arm_f10_postcite import SEARCH_CLI, _claude  # noqa: E402
from arms.arm_f11_precite import _render, PROMPT_DRAFT as _F11_PROMPT  # noqa: E402

_ATOMIC = """2b.【原子句纪律】写作时一句话只陈述一个可独立核验的事实:
   a) 不要把多个数据点、时间点或指标堆进同一个长句(如"A达5GWh、B增长20%、
      C计划2027年量产"应拆成三句),每个事实单独成句并各自标 [Sn];
   b) 一个来源编号只对应它所在那一句的单一事实,避免一句尾部挂一串事实共享
      一个标号;
   c) 宁可句子多而短,不要句子长而信息密——这样每条论断都能被逐一核实。
"""
PROMPT_DRAFT = _F11_PROMPT.replace("3. 报告不需要", _ATOMIC + "3. 报告不需要")
assert PROMPT_DRAFT != _F11_PROMPT


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))

    if os.environ.get("LAB_CLOSED_BOOK"):
        from arms.arm_f11_precite import run as run_f11
        return run_f11(question, logger, workdir)

    prompt = PROMPT_DRAFT.format(date=now_str(), question=question,
                                 cli=SEARCH_CLI, out=out_file)
    _claude(prompt, workdir, logger, "draft",
            f"Bash(python3 {SEARCH_CLI} *),Write,Read", timeout, 60,
            extra_env={"LAB_PRECITE": "1"})
    report = out_file.read_text() if out_file.exists() else ""
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars)")

    mp_f = workdir / "precite_map.json"
    mp = json.loads(mp_f.read_text()) if mp_f.exists() else {}
    final = _render(report, mp, logger)
    out_file.write_text(final)
    return final


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF113_"))
    logger = TraceLogger("/tmp/armF113_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
