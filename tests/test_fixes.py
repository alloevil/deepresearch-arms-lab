# 三个正确性修复的分支测试：
# 1) F6/F7 修订循环——第三轮纯文本修订真实可达（此前是 break 之后的死代码）
# 2) run.py 续跑判据——meta.status 而非 report.md 存在性
# 3) verify_cli——infra error 不计入质量 failures（不触发 pass=False）
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:9")
os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy")

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB))

from common.core import TraceLogger  # noqa: E402
from common import verify_cli  # noqa: E402
from arms import arm_f6_scaffold as f6  # noqa: E402

ENTITY_FAIL = "任务点名的「数字欧元」未在报告中出现"
TRUNC_FAIL = "「现状」节末尾疑似截断: …而且"


def _fake_env(monkeypatch, tmp_path, deep_results):
    """给 arm_f6.run 打桩：rubric 抽取、claude 子进程、验证器全部离线化。
    deep_results: 依次返回的深检结果序列（耗尽后重复最后一个）。"""
    calls = {"revise": []}  # [(tag, prompt)]
    out_file = tmp_path / "report.md"

    monkeypatch.setattr(f6, "extract_rubric",
                        lambda q: {"entities": [], "counts": [], "actions": []})

    def fake_claude(prompt, workdir, logger, tag, resume=None):
        if tag == "draft":
            out_file.write_text("# 报告\n" + "内容。" * 600)
        else:
            calls["revise"].append((tag, prompt))
        return "sess-1"
    monkeypatch.setattr(f6, "_run_claude", fake_claude)
    monkeypatch.setattr(f6, "_ev_used_ratio", lambda *a: 1.0)

    state = {"i": 0}

    def fake_verify(out, question, workdir, deep=False, rubric=None):
        if not deep:  # 快检：强制进入深检循环
            return {"pass": False, "failures": [ENTITY_FAIL], "errors": [],
                    "stats": {"risk": 0.9, "risk_reasons": ["test"]}}
        r = deep_results[min(state["i"], len(deep_results) - 1)]
        state["i"] += 1
        return json.loads(json.dumps(r))  # 防止调用方原地修改共享 dict
    monkeypatch.setattr(f6, "_verify_plus", fake_verify)
    return calls


def _fail(failures):
    return {"pass": False, "failures": list(failures), "errors": [],
            "stats": {"risk": 0.9, "risk_reasons": []}}


def _passed():
    return {"pass": True, "failures": [], "errors": [],
            "stats": {"risk": 0.0, "risk_reasons": []}}


def test_third_textual_revision_is_reachable(monkeypatch, tmp_path):
    """一直不过 → 三轮修订都发生，且第三轮只带文本类失败、无搜索建议。"""
    calls = _fake_env(monkeypatch, tmp_path,
                      deep_results=[_fail([ENTITY_FAIL, TRUNC_FAIL])] * 4)
    logger = TraceLogger(tmp_path / "trace.jsonl")
    f6.run("测试任务", logger, tmp_path)

    tags = [t for t, _ in calls["revise"]]
    assert tags == ["revise-1", "revise-2", "revise-3"]
    p1, p3 = calls["revise"][0][1], calls["revise"][2][1]
    # 前两轮全量（检索类+文本类，含搜索建议）
    assert ENTITY_FAIL in p1 and TRUNC_FAIL in p1 and "建议搜索词" in p1
    # 第三轮仅文本类，且不再注入搜索建议
    assert ENTITY_FAIL not in p3 and TRUNC_FAIL in p3 and "建议搜索词" not in p3
    # 最终仍失败 → 诚实交卷标记落 trace
    trace = (tmp_path / "trace.jsonl").read_text()
    assert "shipped-with-failures" in trace
    assert trace.count("verify-deep") == 4


def test_pass_midway_stops_revisions(monkeypatch, tmp_path):
    """第二次深检通过 → 只修订一轮，无 shipped-with-failures。"""
    calls = _fake_env(monkeypatch, tmp_path,
                      deep_results=[_fail([TRUNC_FAIL]), _passed()])
    logger = TraceLogger(tmp_path / "trace.jsonl")
    f6.run("测试任务", logger, tmp_path)
    assert [t for t, _ in calls["revise"]] == ["revise-1"]
    assert "shipped-with-failures" not in (tmp_path / "trace.jsonl").read_text()


def test_third_round_all_retrieval_failures_skips_revision(monkeypatch, tmp_path):
    """第三轮只剩检索类失败 → 无文本类可修，跳过修订直接交卷（带标记）。"""
    calls = _fake_env(monkeypatch, tmp_path,
                      deep_results=[_fail([ENTITY_FAIL])] * 4)
    logger = TraceLogger(tmp_path / "trace.jsonl")
    f6.run("测试任务", logger, tmp_path)
    assert [t for t, _ in calls["revise"]] == ["revise-1", "revise-2"]
    assert "shipped-with-failures" in (tmp_path / "trace.jsonl").read_text()


def test_infra_error_not_counted_as_failure(monkeypatch):
    """快模型不可用 → errors 通道记录，fails 为空（不触发修订循环）。"""
    def boom(*a, **kw):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(verify_cli, "chat_json", boom)
    fails, errors = verify_cli.check_requirements(
        "任务", "报告正文，提到了数字欧元。",
        rubric={"entities": ["数字欧元"], "counts": [{"what": "案例", "min": 2}],
                "actions": ["对比"]},
        check_actions=True)
    assert fails == []           # 实体在文中，数量/动作检查是 infra 故障
    assert len(errors) == 2      # counts + actions 各一条
    assert all("LLM不可用" in e for e in errors)


def test_verify_pass_despite_infra_error(monkeypatch, tmp_path):
    """verify 整体：infra error 存在时 pass 仍可为 True，errors 键透出。"""
    def boom(*a, **kw):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(verify_cli, "chat_json", boom)
    body = ("# 报告\n\n## 分析\n\n" +
            "数字欧元进展显著，" * 20 + "详见来源 https://example.org/a 。\n\n"
            "## 参考来源\n\n- https://example.org/a\n")
    rp = tmp_path / "r.md"
    rp.write_text(body)
    result = verify_cli.verify(
        str(rp), "任务",
        rubric={"entities": [], "counts": [{"what": "案例", "min": 2}],
                "actions": []})
    assert result["errors"] and "LLM不可用" in result["errors"][0]
    assert not any("LLM不可用" in f for f in result["failures"])


def test_resume_status_semantics(tmp_path):
    """_prev_status：ok 才算完成；error/缺失/损坏都应触发重跑。"""
    sys.path.insert(0, str(LAB / "eval"))
    from eval.run import _prev_status
    d = tmp_path / "q01_F6"
    d.mkdir()
    assert _prev_status(d) is None                       # meta 缺失
    (d / "meta.json").write_text("{broken")
    assert _prev_status(d) is None                       # meta 损坏
    (d / "meta.json").write_text(json.dumps({"status": "error"}))
    assert _prev_status(d) == "error"
    (d / "meta.json").write_text(json.dumps({"status": "ok"}))
    assert _prev_status(d) == "ok"
