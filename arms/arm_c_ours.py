"""Arm C：我们的系统（选型架构）。

机制来源（对应调研报告选型）：
- 大纲树 + 每节「完成判据」：EDR 的 evidence-aware termination（消融 +8.4 的机制）
- 机械证据库：VeriTrace——搜索工人回传的原文片段+URL 不经改写直接入库，写作时按节取用
- 独立上下文搜索工人 + 详尽 brief：SearchSwarm 编排层四原则（brief 含任务/理由/已知/已排除）
- 缺口驱动循环：规划器每轮读状态选一个未满足判据的节，生成 brief 派发；
  节的判据全部满足则标记完成；连续 2 轮无新证据的节强制关闭（防空转）
- 全局预算上限 + 边际终止：总搜索轮数封顶，所有节完成或预算耗尽即进入写作

刻意不做（对应报告"刻意不做的事"）：认知图横向边、五策略路由、UCB（首版用轮询选缺口）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import (MODEL_FAST, MODEL_MAIN, TraceLogger, chat, chat_json,  # noqa: E402
                         now_str, read_page, search)

MAX_ROUNDS = 14          # 全局搜索轮预算
MAX_STALL = 2            # 一个节连续 N 轮无新证据则强制关闭


# ---------------- 研究状态（纯数据，模型外维护） ----------------

class ResearchState:
    def __init__(self, question: str):
        self.question = question
        self.sections: list[dict] = []   # {title, criteria:[{text,met}], done, stall}
        self.evidence: list[dict] = []   # {id, section, claim, quote, url, title}
        self.searched_queries: set[str] = set()

    def open_sections(self):
        return [s for s in self.sections if not s["done"]]

    def section_evidence(self, title):
        return [e for e in self.evidence if e["section"] == title]

    def brief_view(self, sec) -> str:
        """给规划器/工人的紧凑状态视图——只含该节相关的状态，不含全历史。"""
        ev = self.section_evidence(sec["title"])
        met = [c["text"] for c in sec["criteria"] if c["met"]]
        unmet = [c["text"] for c in sec["criteria"] if not c["met"]]
        return json.dumps({
            "任务": self.question, "章节": sec["title"],
            "已满足的判据": met, "未满足的判据": unmet,
            "已有证据摘要": [e["claim"][:80] for e in ev][-8:],
            "已搜过的查询(勿重复)": sorted(self.searched_queries)[-15:],
        }, ensure_ascii=False)


# ---------------- 组件 1：规划器（出大纲+完成判据） ----------------

def plan(state: ResearchState, logger: TraceLogger):
    outline = chat_json(
        [{"role": "user", "content":
          f"今天是 {now_str()}。为下面的研究任务设计 4-6 节的报告大纲。"
          f"关键要求：为每一节写出 2-4 条「完成判据」——收集到哪些具体信息该节才算研究完成。"
          f"判据必须具体可核查（如“至少三家厂商的量产时间表”而非“了解行业情况”）。\n"
          f'只输出 JSON：[{{"title":"节标题","criteria":["判据1","判据2"]}}]\n\n任务：{state.question}'}],
        logger=logger, tag="plan")
    for sec in outline:
        state.sections.append({
            "title": sec["title"],
            "criteria": [{"text": c, "met": False} for c in sec["criteria"]],
            "done": False, "stall": 0})


# ---------------- 组件 2：搜索工人（独立上下文，详尽 brief 进，证据出） ----------------

def search_worker(brief: str, logger: TraceLogger) -> list[dict]:
    """一次性上下文：收 brief → 自主搜索+阅读 → 回传结构化证据。过程不回流主状态。"""
    queries = chat_json(
        [{"role": "user", "content":
          f"你是研究助理，刚接手下面的调查任务 brief。请设计 3 条互补的中文搜索查询"
          f"（角度不同、避开 brief 中已搜过的），只输出 JSON 数组[\"q1\",\"q2\",\"q3\"]。\n\n{brief}"}],
        model=MODEL_FAST, logger=logger, tag="worker:queries")

    pages = []
    for q in queries[:3]:
        for hit in search(q, logger=logger, n=6)[:2]:
            body = read_page(hit["url"], logger=logger, max_chars=5000)
            if len(body) > 300:
                pages.append({"title": hit["title"], "url": hit["url"], "body": body})
        if len(pages) >= 5:
            break

    if not pages:
        return []
    corpus = "\n\n===\n\n".join(
        f"[{i}] {p['title']} ({p['url']})\n{p['body']}" for i, p in enumerate(pages))
    extracted = chat_json(
        [{"role": "user", "content":
          f"任务 brief：\n{brief}\n\n下面是检索到的网页。请抽取与 brief 中「未满足的判据」相关的证据，"
          f"每条包含：claim（一句话论断）、quote（支撑它的原文片段，逐字摘录不改写，≤120字）、src（网页编号）。"
          f"只抽取网页中确实存在的内容，最多 10 条，优先信息密度高的。只输出 JSON："
          f'[{{"claim":"...","quote":"...","src":0}}]\n\n{corpus[:24000]}'}],
        logger=logger, tag="worker:extract", max_tokens=4500)
    out = []
    for e in extracted:
        try:
            p = pages[int(e["src"])]
            out.append({"claim": e["claim"], "quote": e["quote"],
                        "url": p["url"], "title": p["title"]})
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    # 机械入库前记录本工人用过的 query，回传给主状态去重
    return [{"queries": queries}] + out


# ---------------- 组件 3+4：缺口循环 + 终止控制 ----------------

def research_loop(state: ResearchState, logger: TraceLogger):
    rounds = 0
    while rounds < MAX_ROUNDS and state.open_sections():
        # 轮询选缺口最多的未完成节（首版不做 UCB）
        sec = max(state.open_sections(),
                  key=lambda s: sum(1 for c in s["criteria"] if not c["met"]))
        brief = state.brief_view(sec)
        results = search_worker(brief, logger)
        rounds += 1

        new_ev = 0
        for item in results:
            if "queries" in item:
                state.searched_queries.update(item["queries"])
                continue
            item["section"] = sec["title"]
            item["id"] = f"E{len(state.evidence)+1}"
            state.evidence.append(item)
            new_ev += 1
        logger.log("round", section=sec["title"], new_evidence=new_ev, round=rounds)

        # 对照判据自评（EDR 机制）：用快模型判断哪些判据已被现有证据满足
        ev = state.section_evidence(sec["title"])
        if ev:
            verdicts = chat_json(
                [{"role": "user", "content":
                  f"章节判据与已收集证据如下。逐条判断每个判据是否已被证据满足。\n"
                  f"判据：{json.dumps([c['text'] for c in sec['criteria']], ensure_ascii=False)}\n"
                  f"证据：{json.dumps([e['claim'] for e in ev], ensure_ascii=False)}\n"
                  f'只输出 JSON（与判据等长）：[{{"met": true}}, ...]'}],
                model=MODEL_FAST, logger=logger, tag="criteria-check")
            for c, v in zip(sec["criteria"], verdicts):
                c["met"] = bool(v.get("met"))

        sec["stall"] = sec["stall"] + 1 if new_ev == 0 else 0
        if all(c["met"] for c in sec["criteria"]) or sec["stall"] >= MAX_STALL:
            sec["done"] = True
            logger.log("section-close", section=sec["title"],
                       all_met=all(c["met"] for c in sec["criteria"]))


# ---------------- 组件 5：写作器（每节只见本节证据） ----------------

def write_report(state: ResearchState, logger: TraceLogger) -> str:
    parts = []
    for sec in state.sections:
        ev = state.section_evidence(sec["title"])
        ev_text = "\n".join(
            f"[{e['id']}] {e['claim']}\n  原文:「{e['quote']}」 来源: {e['url']}" for e in ev)
        text = chat(
            [{"role": "user", "content":
              f"今天是 {now_str()}。研究任务：{state.question}\n\n"
              f"撰写报告的「{sec['title']}」一节（600-900字）。规则：\n"
              f"1. 只使用下面编号证据中的信息，行文中用 [E编号] 标注依据；\n"
              f"2. 证据不足的方面明确写“现有资料未覆盖”，不要编造；\n"
              f"3. 有多方数据时对比呈现。\n"
              f"直接输出正文，不要输出节标题。\n\n证据：\n{ev_text[:20000]}"}],
            model=MODEL_MAIN, logger=logger, tag=f"write:{sec['title']}", max_tokens=2200)
        parts.append(f"## {sec['title']}\n\n{text}")

    refs = "\n".join(f"- [{e['id']}] {e['title']} — {e['url']}" for e in state.evidence)
    return "# 研究报告\n\n" + "\n\n".join(parts) + f"\n\n## 参考来源\n\n{refs}"


def run(question: str, logger: TraceLogger) -> str:
    state = ResearchState(question)
    plan(state, logger)
    research_loop(state, logger)
    return write_report(state, logger)


if __name__ == "__main__":
    logger = TraceLogger("/tmp/armC_smoke.jsonl")
    report = run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。", logger)
    print(report[:2000])
    print("\n=== tokens:", logger.tokens)
