"""Arm F11.2:采集侧预引用 + 双通道写作(检索事实/背景知识显式分道)。

F11 诊断(2026-07-21):精度突破(新尺严格率 0.58、错位矛盾趋零)但 judge
6.75——"没读过的页不得写入"同时禁止了 B 靠参数化知识补覆盖的能力(B judge
8.18 的重要来源,代价是超写 21+矛盾 28)。裁判对 F11 低分题的归因全是覆盖洞
("日韩信息空白""单源依赖"),不是写作质量。

F11.2 单变量修改(仅引用条款第 2 条扩展;预引用机制/渲染逐字不动):
- 双通道:检索事实照旧句末标 [Sn];**背景知识/推断允许写**,但必须置于
  显式标记之下(段落以「背景:」开头,或行内『(业界共识)』标注),
  不得携带具体数字/日期/引语——这些只能走 [Sn] 通道。
- 检索不到的重要子话题:用背景通道补齐叙述框架,并说明检索局限。
预期:覆盖洞消失(judge→8档)而 [Sn] 通道纯度不变(fact 持平)。
对照:F112 vs F11 = 背景通道单变量。
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str  # noqa: E402
from arms.arm_f10_postcite import SEARCH_CLI, _claude  # noqa: E402
from arms.arm_f11_precite import _render, PROMPT_DRAFT as _F11_PROMPT  # noqa: E402

_DUAL = """2b.【背景知识通道】检索事实之外,允许用你自己的背景知识补充叙述框架、
   机制解释与常识性铺垫,但必须显式分道:
   a) 成段的背景内容,段落以「背景:」开头;行内简短的共识性判断,句末标注
      『(业界共识)』;
   b) 背景通道**不得携带具体数字、日期、金额、排名、直接引语**——这些只能
      出现在带 [Sn] 标注的句子里;
   c) 某个重要子话题检索不到时,不要留白:用背景通道补齐框架性叙述,并说明
      "该部分未能获得可引用来源"。
"""
PROMPT_DRAFT = _F11_PROMPT.replace("3. 报告不需要", _DUAL + "3. 报告不需要")
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
    # 双通道行为审计:背景标记与 [n] 引用的比例进 trace
    logger.log("dual-channel", bg_paras=final.count("背景:"),
               bg_inline=final.count("(业界共识)"))
    out_file.write_text(final)
    return final


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF112_"))
    logger = TraceLogger("/tmp/armF112_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
