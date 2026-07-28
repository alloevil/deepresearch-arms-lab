"""RACE 风格裁判：四维打分（全面性/深度/指令遵循/可读性）+ pairwise 对比模式。

设计要点：
- 裁判模型与 arm 执行模型不同档（减轻自我偏好）
- 盲评：报告以匿名标签呈现，裁判看不到来自哪个系统
- 降方差：absolute 模式每份报告独立打分 n_samples 次取各维中位数；
  pairwise 模式同题两报告并排比较，A/B 换位各判一次取均值（抵消位置偏差）
- 可审计：结果携带 judge_meta（裁判模型/rubric hash/打分日期/采样数）——
  裁判 prompt 的微小变化会带来 ±0.3-0.6 分漂移，跨批次比较必须能核对同源
- 超长报告保头尾截断（结论在尾部，是 depth 得分点；此前尾部被静默丢弃）
"""
import hashlib
import json
import os
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import _eval_channel, chat_json_eval  # noqa: E402

# 裁判走评测通道（chat_json_eval），与执行器网关解耦——执行器网关不一定提供
# Claude，裁判必须能路由到供 opus 的网关（LAB_EVAL_BASE_URL），否则 400。
# LAB_JUDGE_MODEL 仅在评测通道不供默认裁判时覆盖；换裁判模型 = 换分数量纲。
JUDGE_MODEL = os.environ.get("LAB_JUDGE_MODEL", "claude-opus-4-8")
DIMS = ["comprehensiveness", "depth", "instruction_following", "readability"]

DIM_TEXT = """1. comprehensiveness 全面性：任务要求的各个方面是否都被覆盖？有无明显遗漏的子问题？
2. depth 深度：是否超越表面罗列，给出机制解释、数据支撑、多方对比和批判性评估？
3. instruction_following 指令遵循：任务中的具体要求（如"至少各一家""对比""评估可能性"）是否逐一满足？
4. readability 可读性：结构是否清晰、行文是否连贯、结论是否明确？"""

DISCIPLINE = """- 6 分代表"合格但平庸"，8 分以上必须有明确理由
- 报告长度本身不加分；冗长注水应在 readability 扣分
- 无信源支撑的断言应在 depth 扣分
- 注意：报告的检索时间就是 {today} 前后，出现早于今天的日期与数据都是正常的，
  不要因为"日期太新"或"数据是近期的"而怀疑其真实性、加以扣分"""

RUBRIC = """你是一位严格的研究报告评审专家。今天是 {today}。请对下面这份研究报告打分。

【研究任务】
{question}

【被评报告】
{report}

【评分维度】（每维 0-10 分，可用小数）
""" + DIM_TEXT + """

【打分纪律】
""" + DISCIPLINE + """
- 只输出 JSON：{{"comprehensiveness": x, "depth": x, "instruction_following": x, "readability": x, "rationale": "50字以内总评"}}"""

# JudgeSense（2604.23478）式 rubric 敏感性诊断用：与 RUBRIC 语义等价的改写版。
# 同维度、同纪律、同输出格式，仅措辞不同——分数差即纯 rubric 措辞漂移。
RUBRIC_ALT = """你是一名要求很高的研究报告审稿人。当前日期：{today}。请评审下列报告并给出分数。

【任务描述】
{question}

【待审报告】
{report}

【审稿维度】（各维 0-10，允许小数）
""" + DIM_TEXT + """

【审稿要求】
""" + DISCIPLINE + """
- 只输出 JSON：{{"comprehensiveness": x, "depth": x, "instruction_following": x, "readability": x, "rationale": "50字以内总评"}}"""

PAIR_RUBRIC = """你是一位严格的研究报告评审专家。今天是 {today}。下面是针对同一研究任务的两份匿名报告，请逐维比较并分别打分。

【研究任务】
{question}

【报告 A】
{report_a}

【报告 B】
{report_b}

【评分维度】（每维 0-10 分，可用小数；两份报告分别打分，同维直接可比）
""" + DIM_TEXT + """

【打分纪律】
""" + DISCIPLINE + """
- 先逐维找出两份报告的具体差异再打分，不要给出敷衍的同分
- 只输出 JSON：{{"a": {{"comprehensiveness": x, "depth": x, "instruction_following": x, "readability": x}}, "b": {{同结构}}, "rationale": "80字以内说明关键差异"}}"""

CITATION_CHECK = """下面是一份研究报告中抽取的 {n} 条"论断-引用URL"对，以及每个 URL 的实际网页内容摘录。
请逐条判断该网页内容是否支撑对应论断，输出 JSON 数组，每项 {{"idx": i, "verdict": "supported|not_found|contradicted"}}。

{pairs}"""


def _clip(report: str, limit: int = 30000) -> str:
    """超长报告保头尾：结论/不确定性讨论通常在尾部，是 depth 的得分点。"""
    if len(report) <= limit:
        return report
    head = int(limit * 0.65)
    tail = limit - head
    return (report[:head] + "\n\n…（篇幅超限，中段已截断，以下为报告尾部）…\n\n"
            + report[-tail:])


def _judge_meta(mode: str, n_samples: int, models: list | None = None) -> dict:
    return {"judge_model": (models[0] if models and len(models) == 1
                            else models) if models else JUDGE_MODEL,
            "judge_gateway": _eval_channel()[0],
            "rubric_sha": hashlib.sha256(RUBRIC.encode()).hexdigest()[:12],
            "judge_date": date.today().isoformat(),
            "mode": mode, "n_samples": n_samples}


def _overall(scores: dict) -> float:
    return round(sum(float(scores[d]) for d in DIMS) / len(DIMS), 2)


def score_once(question: str, report: str, rubric: str = RUBRIC,
               model: str = JUDGE_MODEL) -> dict:
    """单次打分（rubric 可换为 RUBRIC_ALT 做措辞漂移诊断；model 可换第二裁判）。"""
    prompt = rubric.format(question=question, report=_clip(report),
                           today=date.today().isoformat())
    s = chat_json_eval([{"role": "user", "content": prompt}],
                       model=model, max_tokens=800)
    s["overall"] = _overall(s)
    return s


def judge_report(question: str, report: str, n_samples: int = 3,
                 judge_models: list | None = None) -> dict:
    """absolute 模式：独立打分 n_samples 次，各维取中位数（单次打分噪声 ±0.3-0.6）。

    judge_models 给多个模型时=双/多裁判鲁棒聚合（RoPoLL 2606.30931）：
    各维对全部(模型×采样)结果取中位数，抵抗离群裁判。默认单裁判 opus-4-8——
    开启多裁判会改变分数量纲，破坏与历史批次的可比性，仅在专门批次用。"""
    models = judge_models or [JUDGE_MODEL]
    samples = []
    for m in models:
        for _ in range(n_samples):
            samples.append(score_once(question, report, model=m))
    agg = {d: round(statistics.median(float(s[d]) for s in samples), 2)
           for d in DIMS}
    agg["overall"] = _overall(agg)
    # 打分离散度（Coin Flip Judge 2606.13685）：单裁判 run-to-run 方差本身是可测量。
    # std 逐维、spread 是 overall 的极差——低离散度才让均分差可信
    if len(samples) > 1:
        agg["std"] = {d: round(statistics.pstdev(float(s[d]) for s in samples), 2)
                      for d in DIMS}
        overalls = [s["overall"] for s in samples]
        agg["overall_spread"] = round(max(overalls) - min(overalls), 2)
    agg["rationale"] = max(samples, key=lambda s: len(str(s.get("rationale", ""))))\
        .get("rationale", "")
    agg["samples"] = [{k: s.get(k) for k in (*DIMS, "overall")} for s in samples]
    agg["judge_meta"] = _judge_meta("absolute", n_samples, models)
    return agg


def judge_pair(question: str, report_x: str, report_y: str) -> dict:
    """pairwise 模式：并排比较打分，换位各判一次取均值。

    返回 {"x": {各维+overall}, "y": {...}, "delta_overall": x-y, "rounds": [...]}。
    x/y 是调用方的报告顺序，与呈现给裁判的 A/B 位置解耦。
    """
    today = date.today().isoformat()
    rx, ry = _clip(report_x), _clip(report_y)
    rounds = []
    for a_is_x in (True, False):
        ra, rb = (rx, ry) if a_is_x else (ry, rx)
        v = chat_json_eval([{"role": "user", "content": PAIR_RUBRIC.format(
            question=question, report_a=ra, report_b=rb, today=today)}],
            model=JUDGE_MODEL, max_tokens=800)
        x_scores = v["a"] if a_is_x else v["b"]
        y_scores = v["b"] if a_is_x else v["a"]
        rounds.append({"x": {d: float(x_scores[d]) for d in DIMS},
                       "y": {d: float(y_scores[d]) for d in DIMS},
                       "x_position": "A" if a_is_x else "B",
                       "rationale": v.get("rationale", "")})
    out = {}
    for side in ("x", "y"):
        agg = {d: round(sum(r[side][d] for r in rounds) / len(rounds), 2)
               for d in DIMS}
        agg["overall"] = _overall(agg)
        out[side] = agg
    out["delta_overall"] = round(out["x"]["overall"] - out["y"]["overall"], 2)
    out["rounds"] = rounds
    out["judge_meta"] = _judge_meta("pairwise", len(rounds))
    return out


if __name__ == "__main__":
    q = "测试任务：概述光伏行业现状"
    r = "光伏行业发展很快。中国是最大生产国。"
    print(json.dumps(judge_report(q, r, n_samples=1), ensure_ascii=False, indent=2))
