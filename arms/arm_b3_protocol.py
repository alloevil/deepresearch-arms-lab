"""Arm B3：裸 Agent-ClaudeCode + F8 同款协议 prompt（prompt 消融对照）。

目的：把 Hybrid 系对裸 agent 的增量拆成"协议 prompt 的功劳"和"外部验收+
退回修改机制的功劳"。B3 与 F8 的 prompt 逐字相同（直接 import，含 rubric
清单、写作规范、自检指引——agent 仍可自跑 verify_cli 自检），唯一差别是
交卷后没有任何外部检查：不做风险门控、不做深检、不退回修改，draft 即成品。

对照关系：B（裸题目） vs B3（+协议 prompt） vs F8（+协议 prompt+外部机制）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from common.verify_cli import extract_rubric  # noqa: E402
from arms.arm_f8_scaffold import (  # noqa: E402 — 逐字复用,保证 prompt 一致
    PROMPT, SEARCH_CLI, VERIFY_CLI, _rubric_text, _run_claude)


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    rubric = extract_rubric(question)
    (workdir / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False))
    (workdir / "question.txt").write_text(question)
    logger.log("rubric", **{k: rubric.get(k) for k in ("entities", "counts", "actions")})

    _run_claude(PROMPT.format(date=now_str(), question=question,
                              cli=SEARCH_CLI, vcli=VERIFY_CLI,
                              out=out_file,
                              rubric_text=_rubric_text(rubric)),
                workdir, logger, "draft")
    if not out_file.exists() or len(out_file.read_text()) < 1000:
        raise RuntimeError("draft report missing or too short")
    logger.log("no-external-verify", note="B3: draft shipped as-is (prompt-only ablation)")
    return out_file.read_text()


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armB3_"))
    logger = TraceLogger("/tmp/armB3_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商，并评估其中一家的降本路径。",
              logger, wd)[:1200])
