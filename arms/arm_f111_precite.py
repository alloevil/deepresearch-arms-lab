"""Arm F11.1:采集侧预引用 + 检索广度纪律(F11 的覆盖短板修复)。

F11 三题诊断(2026-07-21):精度突破(严格率 0.52、错位/矛盾双零、协议
遵守 100%),但 judge 分裂(8.25/6.25/5.75)——裁判归因:q01 日韩检索失败
后信息空白、q09 依赖单一 36氪源。"只写读过的页"把检索广度不足直接暴露
为覆盖缺陷(B 用参数化知识掩盖之,代价是超写)。

F11.1 单变量修改(仅 draft prompt 增加检索广度条款;预引用机制逐字不动):
- B3 式信源纪律:每个主体章节关键论断至少 2 个不同网站来源交叉;
- 检索失败必须换语言(英文)、换角度再试至少一次,不许放弃该子话题;
- 单一来源引用占比不得超过全部引用的 1/3。
对照:F111 vs F11 = 检索广度单变量。目标:judge 拉回 ~8 而精度不掉。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from arms.arm_f10_postcite import SEARCH_CLI, _claude  # noqa: E402
from arms.arm_f11_precite import _render, PROMPT_DRAFT as _F11_PROMPT  # noqa: E402

# 在第 2 条(引用方式)后插入广度条款,其余逐字同 F11
_BREADTH = """2b.【检索广度纪律】
   a) 每个主体章节的关键论断至少要有两个不同网站的来源交叉支撑;单一来源
      的引用不得超过全部引用的三分之一;
   b) 某个子话题/地区/主体检索不到时,必须换语言(英文)、换措辞再试至少
      一次;确实检索不到才可在报告中说明该局限;
   c) 检索广度优先于写作速度——宁可多读几页,不要用单源撑起整节。
"""
PROMPT_DRAFT = _F11_PROMPT.replace("3. 报告不需要", _BREADTH + "3. 报告不需要")
assert PROMPT_DRAFT != _F11_PROMPT


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))

    if os.environ.get("LAB_CLOSED_BOOK"):
        from arms.arm_f11_precite import run as run_f11
        return run_f11(question, logger, workdir)  # 闭卷同 F11(=B 闭卷)

    prompt = PROMPT_DRAFT.format(date=now_str(), question=question,
                                 cli=SEARCH_CLI, out=out_file)
    # max_turns 90:广度纪律结构性增加工具轮次(F10.1 撞 60 的教训)
    _claude(prompt, workdir, logger, "draft",
            f"Bash(python3 {SEARCH_CLI} *),Write,Read", timeout, 90,
            extra_env={"LAB_PRECITE": "1"})
    report = out_file.read_text() if out_file.exists() else ""
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars)")

    import json
    mp_f = workdir / "precite_map.json"
    mp = json.loads(mp_f.read_text()) if mp_f.exists() else {}
    final = _render(report, mp, logger)
    out_file.write_text(final)
    return final


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF111_"))
    logger = TraceLogger("/tmp/armF111_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
