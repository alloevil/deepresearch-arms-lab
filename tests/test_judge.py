# 裁判加固的离线测试：头尾截断、重复打分中位数聚合、pairwise 换位映射。
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:9")
os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy")

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB))

from eval import judge  # noqa: E402


def test_clip_keeps_head_and_tail():
    report = "开头" * 15000 + "【结论锚点】" + "结尾" * 15000  # 6 万字符，超限
    clipped = judge._clip(report, limit=30000)
    assert len(clipped) < 31000
    assert clipped.startswith("开头")
    assert clipped.endswith("结尾")          # 尾部（结论所在）不再被丢弃
    assert "中段已截断" in clipped
    short = "短报告"
    assert judge._clip(short) is short       # 未超限不动


def test_judge_report_median_aggregation(monkeypatch):
    """三次采样中有一次离群 → 中位数聚合不被污染。"""
    samples = iter([
        {"comprehensiveness": 9.0, "depth": 8.5, "instruction_following": 9.0,
         "readability": 8.5, "rationale": "正常一"},
        {"comprehensiveness": 7.0, "depth": 6.5, "instruction_following": 7.0,
         "readability": 6.5, "rationale": "离群"},
        {"comprehensiveness": 9.0, "depth": 8.5, "instruction_following": 9.0,
         "readability": 8.5, "rationale": "正常二较长的说明文字"},
    ])
    monkeypatch.setattr(judge, "chat_json_eval", lambda *a, **kw: dict(next(samples)))
    r = judge.judge_report("任务", "报告", n_samples=3)
    assert r["depth"] == 8.5 and r["overall"] == 8.75   # 离群样本被中位数吸收
    assert len(r["samples"]) == 3
    meta = r["judge_meta"]
    assert meta["mode"] == "absolute" and meta["n_samples"] == 3
    assert meta["judge_model"] and meta["rubric_sha"] and meta["judge_date"]


def test_judge_pair_position_swap_mapping(monkeypatch):
    """裁判有位置偏差（A 位恒 +0.5）→ 换位取均值后 x/y 差值应只剩真实差。"""
    TRUE = {"x": 8.0, "y": 7.0}
    BIAS = 0.5

    def fake(messages, **kw):
        prompt = messages[0]["content"]
        a_report = prompt.split("【报告 A】")[1].split("【报告 B】")[0].strip()
        a_is_x = a_report == "报告X"
        a_true = TRUE["x" if a_is_x else "y"]
        b_true = TRUE["y" if a_is_x else "x"]
        dims = judge.DIMS
        return {"a": {d: a_true + BIAS for d in dims},
                "b": {d: b_true for d in dims},
                "rationale": "test"}
    monkeypatch.setattr(judge, "chat_json_eval", fake)
    r = judge.judge_pair("任务", "报告X", "报告Y")
    # 位置偏差被换位平均抵消：x=8.25, y=7.25，差值 = 真实差 1.0
    assert r["delta_overall"] == 1.0
    assert r["x"]["overall"] == 8.25 and r["y"]["overall"] == 7.25
    assert {rd["x_position"] for rd in r["rounds"]} == {"A", "B"}
    assert r["judge_meta"]["mode"] == "pairwise"
