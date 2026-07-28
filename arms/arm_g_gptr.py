"""Arm G:GPT-Researcher 成熟系统对照(系统级,非单变量)。

选型依据(2026-07-20 调研):CMU DeepResearchGym 第三方实测其引用忠实精度
89.11 全场第一(vs Perplexity 55.65);自测 DRB 管线验证引用 35.2/篇。
回答的问题:成熟工程管线 + MiMo 能到什么水位——若显著超 B/F10,差距在工程
成熟度;若不超,MiMo 基座是天花板。

公平性说明(记进结论):
- 模型:FAST/SMART/STRATEGIC 全 = MiMo(OpenAI 兼容端点),与 B/F10 同;
- 检索:tavily(其原生 retriever;我们降级链亦含 tavily,同源不同管线);
- embedding:本地 all-MiniLM-L6-v2(它独有依赖,我们管线没有)——系统差异,
  不可消除,故 G vs B 是"系统对比"而非单变量消融。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger  # noqa: E402

LAB = Path(__file__).resolve().parent.parent
VENV_SITE = LAB / ".venv_gptr/lib/python3.12/site-packages"


def _configure_env(workdir: Path) -> None:
    """gpt-researcher 全靠环境变量配置;文档研究产物落 workdir。"""
    os.environ["OPENAI_BASE_URL"] = os.environ.get(
        "LAB_OPENAI_BASE_URL", "https://api.openai.com/v1")
    os.environ["OPENAI_API_KEY"] = os.environ.get("LAB_OPENAI_API_KEY") or \
        os.environ["ANTHROPIC_AUTH_TOKEN"]
    m = "openai:" + os.environ.get("LAB_MODEL_MAIN", "xiaomi/mimo-v2.5-pro")
    os.environ["FAST_LLM"] = m
    os.environ["SMART_LLM"] = m
    os.environ["STRATEGIC_LLM"] = m
    # 多语言 embedding:英文-only MiniLM 对中文内容相似度全低于 0.42 阈值,
    # 上下文压缩会把检索结果全滤空(冒烟实证)→ 换 multilingual + 放宽阈值
    os.environ["EMBEDDING"] = ("huggingface:sentence-transformers/"
                               "paraphrase-multilingual-MiniLM-L12-v2")
    os.environ["SIMILARITY_THRESHOLD"] = "0.3"
    # custom retriever → lab_retriever_bridge(与 B/F10 完全同一搜索后端+抓取链;
    # serper/tavily/firecrawl 独立 key 均已配额耗尽,bridge 自带 bing 兜底)
    os.environ["RETRIEVER"] = "custom"
    os.environ["RETRIEVER_ENDPOINT"] = os.environ.get(
        "LAB_RETRIEVER_ENDPOINT", "http://127.0.0.1:8377")
    os.environ["REPORT_SOURCE"] = "web"
    os.environ["DOC_PATH"] = str(workdir)


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    if os.environ.get("LAB_CLOSED_BOOK"):
        raise RuntimeError("arm G 不支持闭卷(gpt-researcher 无闭卷模式)")
    if str(VENV_SITE) not in sys.path:
        sys.path.insert(0, str(VENV_SITE))
    _configure_env(workdir)
    from gpt_researcher import GPTResearcher  # 延迟导入:venv site 注入后才可用

    async def _research() -> str:
        researcher = GPTResearcher(query=question, report_type="research_report",
                                   report_format="markdown")
        ctx = await researcher.conduct_research()
        logger.log("gptr-research-done", n_context=len(ctx or []),
                   n_sources=len(researcher.visited_urls))
        report = await researcher.write_report()
        # 审计留痕:访问过的 URL 与成本,与 search_calls.jsonl 角色对应
        (workdir / "gptr_visited.json").write_text(json.dumps(
            sorted(researcher.visited_urls), ensure_ascii=False, indent=1))
        logger.log("gptr-report-done", chars=len(report),
                   costs=getattr(researcher, "research_costs", None))
        return report

    report = asyncio.run(_research())
    if len(report) < 1000:
        raise RuntimeError(f"gptr report too short ({len(report)} chars)")
    (workdir / "report.md").write_text(report)
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armG_"))
    logger = TraceLogger("/tmp/armG_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
