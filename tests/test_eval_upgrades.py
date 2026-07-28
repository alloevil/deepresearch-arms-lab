# 评测增强四件套的单测:
# 1) 闭卷模式——core.search/read_page 短路,不触网
# 2) fact 全量化——sample=0 核查全部论断-引用对,返回支持矩阵摘要字段
# 3) 污染审计——QCL query_echo 识别照抄题面,BML 命中统计
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:9")
os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy")

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB))

from common import core, verify_cli  # noqa: E402
from eval import contamination  # noqa: E402


def test_closed_book_shortcircuits_search_and_read(monkeypatch):
    monkeypatch.setenv("LAB_CLOSED_BOOK", "1")
    # 断言不触网:任何后端被调用就失败
    monkeypatch.setattr(core, "_search_serper",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("触网")))
    monkeypatch.setattr(core, "_search_bing",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("触网")))
    assert core.search("固态电池") == []
    assert core.read_page("https://example.com") == ""


def test_closed_book_off_by_default(monkeypatch):
    monkeypatch.delenv("LAB_CLOSED_BOOK", raising=False)
    monkeypatch.setattr(core, "_search_bing", lambda q, n: [
        {"title": "t", "url": "https://a.com/x", "snippet": "s"}])
    for k in ("SERPER_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert core.search("q")[0]["url"] == "https://a.com/x"


_BODY = "\n\n".join(
    f"厂商{i}在 2025 年宣布其固态电池产线进入中试阶段，规划产能达到 {i} GWh，"
    f"技术路线为硫化物电解质，量产时间表定在 2027 年。来源: https://ex.com/p{i}"
    for i in range(10))


def _stub_verify(monkeypatch, verdict="supported"):
    monkeypatch.setattr(core, "read_page", lambda url, **k: "页" * 300)
    monkeypatch.setattr(verify_cli, "chat_json_eval",
                        lambda *a, **k: {"verdict": verdict})


def test_fact_full_checks_all_pairs(monkeypatch):
    _stub_verify(monkeypatch)
    _, st = verify_cli.check_citation_support(_BODY, sample=0)
    assert st["total_pairs"] == 10
    assert st["sampled"] == 10  # 全量:核查数=解析数
    assert st["supported"] == 10 and st["over_cite"] == 0


def test_fact_sampling_and_support_matrix_fields(monkeypatch):
    _stub_verify(monkeypatch, verdict="not_found")
    _, st = verify_cli.check_citation_support(_BODY, sample=4)
    assert st["sampled"] == 4 and st["total_pairs"] == 10  # 抽样路径不变
    assert st["not_found"] == 4 and st["contradicted"] == 0
    assert st["over_cite"] == 4  # 引用未支撑其论断的对数


# 脚注式引用（B3 等 arm）：正文 [^n] 标记 + 文末 [^n]: 说明 URL 定义。
# 文末定义块连续无空行会被当超长段落丢弃——修复前 total_pairs=0
_FOOTNOTE_BODY = (
    "厂商A于 2025 年宣布固态电池中试线投产，规划产能 5 GWh，采用硫化物路线[^1]。\n\n"
    "厂商B的量产时间表定在 2027 年，能量密度目标 400Wh/kg，技术路线为氧化物[^2]。\n\n"
    "[^1]: 某行业媒体，《固态电池产业动态季报》，https://ex.com/a\n"
    "[^2]: 某券商，《固态电池白皮书》，https://ex.com/b")


def test_fact_parses_footnote_citations(monkeypatch):
    _stub_verify(monkeypatch)
    _, st = verify_cli.check_citation_support(_FOOTNOTE_BODY, sample=0)
    assert st["total_pairs"] == 2  # 两个正文论断各配到文末脚注 URL
    assert st["supported"] == 2
    # 脚注定义行本身不被误当论断（否则会多出 2 个"来源标题"对）


def test_fact_footnote_does_not_break_inline(monkeypatch):
    _stub_verify(monkeypatch)
    _, st = verify_cli.check_citation_support(_BODY, sample=0)  # 内联式仍全解析
    assert st["total_pairs"] == 10


# fact-v2 分层:打包句拆子论断后不再"一损俱损";邻近池识别引用错位
_V2_BODY = (
    "厂商甲 2025 年出货 5 GWh，同时厂商乙的产线于 2026 年投产，两者均采用"
    "硫化物路线，行业整体渗透率达到 4%。来源: https://ex.com/a\n\n"
    "厂商丙的能量密度达到 400Wh/kg，量产计划定于 2027 年正式启动执行。"
    "来源: https://ex.com/b https://ex.com/c")


def test_fact_v2_layered_verdicts(monkeypatch):
    monkeypatch.setattr(core, "read_page", lambda url, **k: "页" * 300)
    calls = {"n": 0}

    def fake_chat(msgs, **k):
        text = msgs[0]["content"]
        if "拆成独立的原子事实" in text:
            calls["n"] += 1
            return ["子1", "子2"] if "厂商甲" in text else ["子3"]
        # 第二对(子3):主页 ex.com/b/c 不支撑,邻近池(第一段 ex.com/a)支撑→错位
        if "子3" in text:
            hit = "supported" if "ex.com/a" in text else "not_found"
            return [{"idx": 0, "verdict": hit}]
        # 第一对子2 的邻近重判:仍不支撑(保持 partial)
        if "子2" in text and "子1" not in text:
            return [{"idx": 0, "verdict": "not_found"}]
        # 第一对主判:子1 支撑、子2 不支撑
        return [{"idx": 0, "verdict": "supported"},
                {"idx": 1, "verdict": "not_found"}]

    monkeypatch.setattr(verify_cli, "chat_json_eval", fake_chat)
    st = verify_cli.check_citation_support_v2(_V2_BODY)
    assert st["total_pairs"] == 2
    assert st["pairs"]["partial"] == 1  # 打包句部分真,不再整句判死
    assert st["pairs"]["supported_by_neighbor"] == 1  # 邻近池识别出引用错位
    assert st["pairs"]["not_found"] == 0
    assert st["subclaims"]["total"] == 3


def test_fact_v2_unreachable(monkeypatch):
    monkeypatch.setattr(core, "read_page", lambda url, **k: "")  # 全部抓取失败
    monkeypatch.setattr(verify_cli, "chat_json_eval", lambda *a, **k: ["子"])
    st = verify_cli.check_citation_support_v2(_V2_BODY)
    assert st["pairs"]["unreachable"] == 2


def test_fact_v2_conflict_layers(monkeypatch):
    """CONFLICT 分层(DRAGged 分类学):时效矛盾与实质矛盾分档,
    contradicted 汇总键向后兼容地包含全部矛盾档。"""
    monkeypatch.setattr(core, "read_page", lambda url, **k: "页" * 300)

    def fake_chat(msgs, **k):
        text = msgs[0]["content"]
        if "拆成独立的原子事实" in text:
            return ["子1", "子2"] if "厂商甲" in text else ["子3"]
        if "子3" in text:  # 第二对:实质矛盾
            return [{"idx": 0, "verdict": "conflict_substantive"}]
        return [{"idx": 0, "verdict": "supported"},  # 第一对:时效矛盾档
                {"idx": 1, "verdict": "conflict_temporal"}]

    monkeypatch.setattr(verify_cli, "chat_json_eval", fake_chat)
    st = verify_cli.check_citation_support_v2(_V2_BODY)
    assert st["pairs"]["conflict_temporal"] == 1
    assert st["pairs"]["conflict_substantive"] == 1
    assert st["pairs"]["contradicted"] == 2  # 兼容键 = 全部矛盾档之和


# F9 机械件:[En] 渲染与逐字摘录审计(纯代码,无 LLM)
def test_run_py_function_inventory():
    """防"编辑吞函数头"回归:今天 judge_drift/summary 的 def 行两次被插入
    编辑误吞,函数体缝合进上一个函数,py_compile 不报错、运行时才炸。"""
    import ast
    src = (LAB / "eval" / "run.py").read_text()
    fns = {n.name for n in ast.walk(ast.parse(src))
           if isinstance(n, ast.FunctionDef)}
    expected = {"run_arms", "judge_all", "pairwise_all", "compare",
                "fact_check", "fact_check_v2", "fact_check_evidence",
                "judge_drift", "summary"}
    assert expected <= fns, f"missing: {expected - fns}"


def test_claims_vs_evidence_local_check(monkeypatch):
    """句级本地核验:标记句配 quote 判定,未登记 ID → no_evidence,零抓页。"""
    ev = {"E1": {"url": "https://ex.com/a", "quote": "出货量约 5 GWh"},
          "E2": {"url": "https://ex.com/b", "quote": "计划 2027 年中试"}}
    raw = ("厂商甲 2025 年出货量达到 5 GWh，规模全行业第一[E1]。"
           "厂商乙已确定 2027 年大规模量产[E2]。"
           "行业整体前景相当广阔，未来五年值得持续重点关注[E9]。"
           "这句没有任何标记，不参与核验。")

    def fake_chat(msgs, **k):
        assert "论断-证据摘录" in msgs[0]["content"]
        return [{"idx": 0, "verdict": "supported"},
                {"idx": 1, "verdict": "not_found"}]  # "已确定量产" 超过 "计划中试"

    monkeypatch.setattr(verify_cli, "chat_json_eval", fake_chat)
    monkeypatch.setattr(core, "read_page",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不应抓页")))
    st = verify_cli.check_claims_vs_evidence(raw, ev)
    assert st["total_claims"] == 3
    assert st["claims"]["supported"] == 1
    assert st["claims"]["not_found"] == 1  # 强度超写被判出
    assert st["claims"]["no_evidence"] == 1  # E9 未登记


def test_f9_render_and_quote_check(monkeypatch, tmp_path):
    from arms import arm_f9_evidence as f9
    from common.core import TraceLogger
    ev_lines = [
        {"id": "E1", "url": "https://ex.com/a", "quote": "出货量达 5 GWh"},
        {"id": "E2", "url": "https://ex.com/b", "quote": "量产计划定于 2027 年"},
        {"id": "E3", "url": "https://ex.com/c", "quote": "页面上根本没有的话"},
    ]
    (tmp_path / "evidence.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in ev_lines))
    ev = f9._load_evidence(tmp_path)
    logger = TraceLogger(tmp_path / "t.jsonl")

    report = ("厂商甲出货量达 5 GWh[E1]。厂商乙量产计划定于 2027 年[E2]。"
              "行业整体呈加速态势[综合 E1,E2]。未知引用[E9]保留。")
    rendered = f9._render_citations(report, ev, logger)
    # 脚注式:正文用数字上标 [n],唯一来源集中到文末"参考来源"节,同源复用编号
    assert "厂商甲出货量达 5 GWh[1]。" in rendered
    assert "厂商乙量产计划定于 2027 年[2]。" in rendered
    assert "行业整体呈加速态势[1][2]。" in rendered  # 综合引用两源,复用 [1][2]
    assert "## 参考来源" in rendered
    assert "[1] https://ex.com/a" in rendered and "[2] https://ex.com/b" in rendered
    assert "[E9]" in rendered  # 未知 ID 原样保留
    assert "[E1]" not in rendered

    # 摘录审计:E1/E2 逐字命中(跨空白仍匹配),E3 编造 → not_verbatim
    monkeypatch.setattr(f9, "read_page",
                        lambda url, **k: "……出货量达 5\nGWh……量产计划定于 2027 年……" + "填" * 100)
    f9._quote_check(ev, tmp_path, logger)
    st = json.loads((tmp_path / "quote_check.json").read_text())["stats"]
    assert st["verbatim"] == 2 and st["not_verbatim"] == 1


def test_f9_quote_align_recovers_paraphrase(monkeypatch, tmp_path):
    """模糊对齐:agent 改写过的摘录能回填页面原文;编造的对不上。"""
    from arms import arm_f9_evidence as f9
    from common.core import TraceLogger
    page = ("前言" * 30 + "三星SDI已于2023年建成全球最早的全固态电池试点产线，"
            "能量密度指标达到900Wh/L，处于行业领先水平。" + "后记" * 30)
    ev = {
        # 改写版摘录(语序/用词变了,但同段):应 aligned 并回填原文
        "E1": {"url": "https://ex.com/a",
               "quote": "三星SDI在2023年建成了全球最早的全固态电池试点产线,能量密度达900Wh/L"},
        # 纯编造:应保持 not_verbatim
        "E2": {"url": "https://ex.com/a", "quote": "丰田宣布2024年实现百万辆级全固态装车"},
    }
    (tmp_path / "evidence.jsonl").write_text(
        "\n".join(json.dumps(e | {"id": k}, ensure_ascii=False) for k, e in ev.items()))
    monkeypatch.setattr(f9, "read_page", lambda url, **k: page)
    logger = TraceLogger(tmp_path / "t.jsonl")
    f9._quote_check(ev, tmp_path, logger)
    st = json.loads((tmp_path / "quote_check.json").read_text())["stats"]
    assert st["aligned"] == 1 and st["not_verbatim"] == 1
    assert "900Wh/L" in ev["E1"]["quote_aligned"]  # 回填的是页面原文
    # 台账已带对齐字段落盘
    lines = (tmp_path / "evidence.jsonl").read_text().splitlines()
    assert any("quote_aligned" in ln for ln in lines)


def test_contamination_query_echo_and_bml(tmp_path):
    q = "调研 2025 年以来固态电池的产业化进展：主要厂商的技术路线与量产时间表"
    run = tmp_path / "q01_X"
    run.mkdir()
    events = [
        {"kind": "search", "query": "调研 2025 年以来固态电池的产业化进展",  # 照抄题面
         "urls": ["https://a.com/1", "https://huggingface.co/datasets/x"]},  # BML 命中
        {"kind": "search", "query": "Toyota solid state battery 2027",  # 正常 query
         "urls": ["https://b.com/2"]},
        {"kind": "read", "url": "https://a.com/1"},
    ]
    (run / "search_calls.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events))
    row = contamination.audit_run(run, q)
    assert row["bml_hits"] == 1
    assert row["query_echo"] >= 0.9  # 照抄题面的 query 几乎整条是题面子串
    assert row["n_queries"] == 2

    row2 = contamination.audit_run(run, "完全无关的另一个主题问题九九九")
    assert row2["query_echo"] == 0.0  # 无关题面不产生虚假命中


def test_clip_claim_cuts_at_sentence_boundary():
    # 旧 text[:200] 会把长打包段剁出悬空残句进核验器 → 矛盾/not_found 假阳
    # (mimo_smoke q05_F91 chinadaily 案例的根因)
    text = ("截至 2025 年 12 月，累计交易额达 19.5 万亿元人民币。" * 12
            + "这一数字较 2023 年增长了三倍以上，覆盖全部试点城市。")
    clipped = verify_cli._clip_claim(text, limit=400)
    assert len(clipped) <= 400
    assert clipped.endswith("。")  # 句界收尾,无悬空残句
    assert "这一数字较" not in clipped  # 装不下的整句被丢弃而非剁半


def test_clip_claim_short_text_unchanged():
    t = "厂商甲 2025 年出货 5 GWh，同比增长三倍。"
    assert verify_cli._clip_claim(t) == t


def test_clip_claim_no_boundary_falls_back_hard_cut():
    t = "无任何句读的超长串" + "数" * 500
    assert len(verify_cli._clip_claim(t, limit=400)) == 400


def test_extract_pairs_claim_not_fragmented():
    body = ("厂商甲的固态电池于 2025 年实现装车。" * 11
            + "这一数字较 2023 年增长。来源: https://ex.com/a")
    pairs, _ = verify_cli._extract_citation_pairs(body)
    assert pairs and not pairs[0]["claim"].endswith("增")  # 不再 200 字硬剁


def test_fact_v2_persists_sub_detail(monkeypatch):
    # 对级 worst-of 聚合掩盖构成——sub_detail 必须能定位到具体冲突子句
    monkeypatch.setattr(core, "read_page", lambda url, **k: "页" * 300)

    def fake_chat(messages, **kw):
        c = messages[0]["content"]
        if "拆成独立的原子事实子论断" in c:
            return ["子1", "子2"]
        return [{"idx": 0, "verdict": "supported"},
                {"idx": 1, "verdict": "conflict_substantive"}]

    monkeypatch.setattr(verify_cli, "chat_json_eval", fake_chat)
    st = verify_cli.check_citation_support_v2(_V2_BODY)
    sd = st["detail"][0]["sub_detail"]
    assert [x["verdict"] for x in sd] == ["supported", "conflict_substantive"]
    assert sd[0]["text"] == "子1"
    assert st["subclaims"]["conflicted"] == 2  # 两对各 1 个冲突子句


def test_extract_pairs_ordered_list_references():
    # 第五种引用形态(MiMo 批 q01/q09_B):正文 [n] + 文末 Markdown 有序列表
    body = ("行业在 2025 年经历系统性出清，多家明星公司接连倒闭破产[1]。"
            "幸存者转向高端品类并压缩产能规模以求生存[2]。\n\n"
            "## 参考来源\n\n"
            "1. Ageye, \"Why Farms Fail\" — https://ex.com/fail\n"
            "2. Plenty, \"Restructuring\" — https://ex.com/plenty\n")
    pairs, para_urls = verify_cli._extract_citation_pairs(body)
    assert len(pairs) == 1
    assert pairs[0]["urls"] == ["https://ex.com/fail", "https://ex.com/plenty"]
    # 参考区块不算论断、其 URL 不进邻近池
    assert para_urls[-1] == []


def test_extract_pairs_single_numbered_line_still_inline():
    # 正文里孤立的"1. xxx URL"行不是参考区(<2 行),仍按内联对解析,无回归
    body = ("1. 厂商甲于 2025 年实现装车量产，出货规模达到行业第一梯队水平，"
            "并与三家整车厂签订长期供货协议，产能利用率维持在九成以上。"
            "https://ex.com/a\n\n正文继续。")
    pairs, _ = verify_cli._extract_citation_pairs(body)
    assert len(pairs) == 1 and pairs[0]["urls"] == ["https://ex.com/a"]
