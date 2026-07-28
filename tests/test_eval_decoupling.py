# 评测通道解耦单测：裁判/fact 核验与执行器网关分离
# 背景（2026-07-17 实测）：执行器网关不一定提供 Claude → 裁判 opus 400；
# 核验器与执行器同模型 = 自评闭环。解耦后执行器走 ANTHROPIC_BASE_URL，
# 评测侧走 LAB_EVAL_BASE_URL（未设时回落执行器通道，历史行为不变）。
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:9")
os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy")

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB))

from common import core, verify_cli  # noqa: E402
from eval import judge  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _ok_payload(text="ok"):
    return {"choices": [{"message": {"content": text}}], "usage": {}}


def test_chat_honors_channel_override(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"], seen["auth"] = url, headers["Authorization"]
        return _Resp(_ok_payload())

    monkeypatch.setattr(core.httpx, "post", fake_post)
    core.chat([{"role": "user", "content": "hi"}],
              base_url="http://judge-gw", api_key="judge-key", retries=1)
    assert seen["url"] == "http://judge-gw/v1/chat/completions"
    assert seen["auth"] == "Bearer judge-key"


def test_chat_default_channel_unchanged(monkeypatch):
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["url"], seen["auth"] = url, headers["Authorization"]
        return _Resp(_ok_payload())

    monkeypatch.setattr(core.httpx, "post", fake_post)
    core.chat([{"role": "user", "content": "hi"}], retries=1)
    assert seen["url"] == f"{core.GATEWAY}/v1/chat/completions"
    assert seen["auth"] == f"Bearer {core.API_KEY}"


def test_eval_channel_env_override(monkeypatch):
    monkeypatch.setenv("LAB_EVAL_BASE_URL", "http://opus-gw/")
    monkeypatch.setenv("LAB_EVAL_AUTH_TOKEN", "opus-key")
    assert core._eval_channel() == ("http://opus-gw", "opus-key")


def test_eval_channel_falls_back_to_executor(monkeypatch):
    monkeypatch.delenv("LAB_EVAL_BASE_URL", raising=False)
    monkeypatch.delenv("LAB_EVAL_AUTH_TOKEN", raising=False)
    assert core._eval_channel() == (core.GATEWAY, core.API_KEY)


def test_chat_json_eval_injects_eval_channel(monkeypatch):
    monkeypatch.setenv("LAB_EVAL_BASE_URL", "http://opus-gw")
    monkeypatch.setenv("LAB_EVAL_AUTH_TOKEN", "opus-key")
    seen = {}

    def fake_chat(messages, **kw):
        seen.update(kw)
        return json.dumps({"ok": 1})

    monkeypatch.setattr(core, "chat", fake_chat)
    assert core.chat_json_eval([{"role": "user", "content": "x"}]) == {"ok": 1}
    assert seen["base_url"] == "http://opus-gw"
    assert seen["api_key"] == "opus-key"


def test_model_verify_env_override(monkeypatch):
    monkeypatch.setenv("LAB_MODEL_VERIFY", "claude-haiku-4-5")
    assert core.model_verify() == "claude-haiku-4-5"
    monkeypatch.delenv("LAB_MODEL_VERIFY", raising=False)
    assert core.model_verify() == core.MODEL_FAST


def test_judge_routes_through_eval_channel(monkeypatch):
    # 裁判必须走 chat_json_eval（评测通道），模型为 JUDGE_MODEL
    seen = {}

    def fake_eval(messages, **kw):
        seen.update(kw)
        return {"comprehensiveness": 8, "depth": 8,
                "instruction_following": 8, "readability": 8, "rationale": "r"}

    monkeypatch.setattr(judge, "chat_json_eval", fake_eval)
    s = judge.score_once("q", "report")
    assert s["overall"] == 8.0
    assert seen["model"] == judge.JUDGE_MODEL


def test_mechanism_side_stays_on_executor(monkeypatch):
    # 守卫：extract_rubric 是 F 系 arm 的运行时机制（被测系统的一部分），
    # 必须走执行器通道的 chat_json+MODEL_FAST——若被误接到评测通道，
    # 等于给被测系统偷换更强模型，污染单变量对照。
    seen = {}

    def fake_chat_json(messages, **kw):
        seen.update(kw)
        return {"entities": [], "counts": [], "actions": []}

    def fail_eval(*a, **kw):
        raise AssertionError("机制侧不得走评测通道")

    monkeypatch.setattr(verify_cli, "chat_json", fake_chat_json)
    monkeypatch.setattr(verify_cli, "chat_json_eval", fail_eval)
    verify_cli.extract_rubric("调研固态电池产业化进展")
    assert seen["model"] == verify_cli.MODEL_FAST
    assert "base_url" not in seen
