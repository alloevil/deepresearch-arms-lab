# 能力增强的离线测试：
# 1) read_page 的 browser-use 渲染降级（httpx 拿不到正文时触发）
# 2) verify_cli 引用核验失败信息携带论断原文
# 3) F8 _search_hints 把不支撑论断转成验证式搜索建议
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:9")
os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy")

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB))

from common import core  # noqa: E402
from arms import arm_f8_scaffold as f8  # noqa: E402


def test_read_page_browser_fallback(monkeypatch):
    """httpx 抓取正文过短 → 触发浏览器渲染降级并采用其结果。"""
    class FakeResp:
        text = "<html><body><div id=app></div></body></html>"  # JS 壳,无正文
    monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResp())
    rendered = "渲染后的正文。" * 50
    monkeypatch.setattr(core, "_browser_render_text", lambda url: rendered)
    text = core.read_page("https://js-only.example/test-fallback-1")
    assert text.startswith("渲染后的正文")


def test_read_page_no_fallback_when_static_ok(monkeypatch):
    """静态抓取已有足量正文 → 不调用浏览器。"""
    class FakeResp:
        text = "<html><body><p>" + "静态正文。" * 100 + "</p></body></html>"
    monkeypatch.setattr(core.httpx, "get", lambda *a, **kw: FakeResp())
    called = []
    monkeypatch.setattr(core, "_browser_render_text",
                        lambda url: called.append(url) or "x")
    text = core.read_page("https://static.example/test-fallback-2")
    assert "静态正文" in text and not called


def test_browser_render_disabled_without_env(monkeypatch):
    """未配置 BU_CDP_URL 时降级函数直接返回空,不起子进程。"""
    monkeypatch.delenv("BU_CDP_URL", raising=False)
    assert core._browser_render_text("https://any.example/") == ""


def test_citation_failure_carries_claim(monkeypatch, tmp_path):
    """引用核验失败信息应携带论断原文,供缺口反馈生成搜索建议。"""
    from common import verify_cli
    monkeypatch.setattr(verify_cli, "read_page", lambda url, **kw: "无关内容。" * 100,
                        raising=False)
    import common.core as cc
    monkeypatch.setattr(cc, "read_page", lambda url, **kw: "无关内容。" * 100)
    monkeypatch.setattr(verify_cli, "chat_json_eval",
                        lambda *a, **kw: {"verdict": "not_found"})
    body = ("# 报告\n\n" + "钠电池2025年出货量达到10GWh，同比增长3倍，多家头部厂商已建成量产线，"
            "正在成为储能市场的新主力技术方向之一。https://a.example/x\n\n" +
            "磷酸铁锂电芯成本已降至0.3元每瓦时，具备垂直整合能力的厂商优势明显，"
            "行业集中度在过去两年持续提升。https://b.example/y\n\n")
    fails, stats = verify_cli.check_citation_support(body, sample=2)
    assert fails and "不支撑论断：「" in fails[0]
    assert "钠电池" in fails[0]
    assert all("claim" in v for v in stats["detail"])


def test_f8_hints_from_unsupported_claims():
    """F8 把不支撑论断转成验证式搜索建议；实体缺失走原有分支。"""
    fails = [
        "引用抽查 4 条中 2 条不支撑论断——不支撑论断：「钠电池2025年出货量达到10GWh」"
        "(https://a.example/x)；不支撑论断：「成本降至0.3元每瓦时」(https://b.example/y)"
        "——请针对这些论断补搜可支撑的信源，或核实后修改/删除论断",
        "任务点名的「数字欧元」未在报告中出现",
    ]
    hints = f8._search_hints(fails)
    assert "验证论断「钠电池2025年出货量达到10GWh" in hints
    assert "成本降至0.3元每瓦时" in hints
    assert 'search "数字欧元 2025 2026"' in hints  # 原有实体分支不受影响
