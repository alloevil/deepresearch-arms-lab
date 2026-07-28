# provenance 落盘单测：补 meta.json.model=None 黑洞 + --compare 跨模型守卫
# 背景：agent 系执行器在子进程内、不进 trace，此前无法从产物自证跑的什么模型/网关
# （曾靠读 claude_settings.json + 探测网关才确认"最近批次实为 sonnet 而非 MiMo"）。
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:9")
os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy")

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB))

from eval import run  # noqa: E402


def test_provenance_has_model_and_gateway():
    p = run._provenance("B3")
    assert p["model_main"] and p["model_fast"] and p["gateway"]


def test_agent_arm_uses_claude_gateway(monkeypatch):
    # agent 系执行器网关看 LAB_CLAUDE_BASE_URL（arm 用它覆盖子进程 base_url）
    monkeypatch.setenv("LAB_CLAUDE_BASE_URL", "http://agent-gw.example")
    assert run._provenance("F91")["gateway"] == "http://agent-gw.example"
    # workflow 系走 core.chat 用 GATEWAY，不受 LAB_CLAUDE_BASE_URL 影响
    assert run._provenance("A")["gateway"] == run.GATEWAY


def test_agent_arm_falls_back_to_core_gateway(monkeypatch):
    monkeypatch.delenv("LAB_CLAUDE_BASE_URL", raising=False)
    assert run._provenance("B")["gateway"] == run.GATEWAY


def _write_meta(d: Path, arm: str, model_main, gateway):
    d.mkdir(parents=True)
    meta = {"qid": d.name.split("_")[0], "arm": arm, "status": "ok",
            "started_at": "2026-07-17T00:00:00"}
    if model_main is not None:
        meta["model_main"], meta["gateway"] = model_main, gateway
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "report.md").write_text("x")


def test_exec_models_reads_meta(tmp_path):
    _write_meta(tmp_path / "q01_B3", "B3", "claude-sonnet-5", "http://gw")
    assert run._exec_models(tmp_path, "B3") == {"claude-sonnet-5@http://gw"}


def test_exec_models_unknown_for_legacy_meta(tmp_path):
    _write_meta(tmp_path / "q01_B3", "B3", None, None)  # 旧版 meta 无 model 字段
    assert run._exec_models(tmp_path, "B3") == {"unknown"}


def test_compare_warns_on_model_mismatch(tmp_path, capsys):
    # 两 arm 不同执行器 → compare 必须显式告警"分差不可归因于机制"
    _write_meta(tmp_path / "q01_B3", "B3", "claude-sonnet-5", "http://sonnet-gw")
    _write_meta(tmp_path / "q01_F91", "F91", "xiaomi/mimo-v2.5-pro", "http://mimo-gw")
    for d, arm, ov in ((tmp_path / "q01_B3", "B3", 9.0),
                       (tmp_path / "q01_F91", "F91", 8.5)):
        (d / "scores.json").write_text(json.dumps({"overall": ov}))
    run.compare(str(tmp_path), "B3", "F91")
    out = capsys.readouterr().out
    assert "模型警告" in out


def test_compare_no_model_warning_when_same(tmp_path, capsys):
    _write_meta(tmp_path / "q01_B3", "B3", "claude-sonnet-5", "http://gw")
    _write_meta(tmp_path / "q01_F91", "F91", "claude-sonnet-5", "http://gw")
    for d, ov in ((tmp_path / "q01_B3", 9.0), (tmp_path / "q01_F91", 8.5)):
        (d / "scores.json").write_text(json.dumps({"overall": ov}))
    run.compare(str(tmp_path), "B3", "F91")
    out = capsys.readouterr().out
    assert "模型警告" not in out
