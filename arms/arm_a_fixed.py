"""Arm A：写死工作流（下界对照）。

固定顺序，无任何动态决策：
  出大纲（4-6 节） → 每节固定 2 条搜索 query → 每节读 top-2 网页 → 逐节写作 → 拼接。
没有终止判据、没有反思、没有缺口回补——这正是它作为下界的意义。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import MODEL_MAIN, TraceLogger, chat, chat_json, now_str, read_page, search  # noqa: E402


def run(question: str, logger: TraceLogger) -> str:
    outline = chat_json(
        [{"role": "user", "content":
          f"今天是 {now_str()}。为下面的研究任务设计一个 4-6 节的报告大纲，"
          f"每节配 2 条中文搜索查询。只输出 JSON 数组："
          f'[{{"title": "节标题", "queries": ["q1", "q2"]}}]\n\n任务：{question}'}],
        logger=logger, tag="outline")

    sections = []
    for sec in outline:
        evidence = []
        for q in sec["queries"][:2]:
            for hit in search(q, logger=logger, n=5)[:2]:
                body = read_page(hit["url"], logger=logger, max_chars=4000)
                if body:
                    evidence.append(f"【{hit['title']}】({hit['url']})\n{body}")
        ev_text = "\n\n---\n\n".join(evidence) if evidence else "（未检索到有效资料）"
        text = chat(
            [{"role": "user", "content":
              f"今天是 {now_str()}。研究任务：{question}\n\n"
              f"请基于以下资料撰写报告的「{sec['title']}」一节（500-800字），"
              f"关键论断标注来源URL。资料之外的内容不要编造。"
              f"直接输出正文，不要重复节标题。\n\n{ev_text[:20000]}"}],
            model=MODEL_MAIN, logger=logger, tag=f"write:{sec['title']}",
            max_tokens=2000)
        sections.append(f"## {sec['title']}\n\n{text}")

    return f"# 研究报告\n\n" + "\n\n".join(sections)


if __name__ == "__main__":
    logger = TraceLogger("/tmp/armA_smoke.jsonl")
    report = run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。", logger)
    print(report[:1500])
    print("\n=== tokens:", logger.tokens)
