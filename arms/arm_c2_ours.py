"""Arm C2：Arm C 的修复版（机制不变，修五个已定位的实现缺陷）。

相对 arm_c_ours 的改动（Round 1 失分分析 → 修法）：
1. 选节策略：贪心"未满足判据最多"会反复选中同一大节（q09 首节吃掉 7/14 轮）
   → 单节轮数上限 SECTION_CAP，达到上限的节不再参与选择
2. 补搜机制：判据未满足就关闭的节（q05 厄瓜多尔/丹麦没搜到即放弃）
   → 关闭前从全局补搜池扣预算做定向补搜，明确要求换语言/换角度
3. 写作截断：max_tokens 2200 顶格即静默截断（q05 已上线节、q09 两节）
   → 预算提到 4000 + 句末标点启发式检测 + 一次续写
4. 证据去重：同 URL 证据重复入库（q09 参考文献 123 条去重后仅 18 条）
   → 入库时按 (归一化URL, claim) 去重；参考文献按 URL 合并
5. 结论节错用证据门控：结论节分不到证据 → 写"无证据"（q09 结论 616 字自白）
   → 大纲不再含结论节；写作器最后基于全文草稿综合出结论（允许综合，禁止新事实）
"""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import (MODEL_FAST, MODEL_MAIN, TraceLogger, chat, chat_json,  # noqa: E402
                         now_str, read_page, search)

MAX_ROUNDS = 14          # 全局搜索轮预算（与 C 相同，保证可比）
RESCUE_ROUNDS = 3        # 其中预留的补搜池（含在 MAX_ROUNDS 内）
SECTION_CAP = 3          # 单节常规轮数上限
MAX_STALL = 2            # 一个节连续 N 轮无新证据则强制关闭
SENT_END = tuple("。！？.!?”』\"）)]】>》—*`")   # 句末启发式（含常见收尾符号）


def norm_url(url: str) -> str:
    """URL 归一化：去 query/fragment/尾斜杠，用于证据去重。"""
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))


# ---------------- 研究状态（纯数据，模型外维护） ----------------

class ResearchState:
    def __init__(self, question: str):
        self.question = question
        self.sections: list[dict] = []   # {title, criteria:[{text,met}], done, stall, rounds}
        self.evidence: list[dict] = []   # {id, section, claim, quote, url, title}
        self.searched_queries: set[str] = set()
        self._ev_keys: set[tuple] = set()

    def open_sections(self):
        return [s for s in self.sections if not s["done"]]

    def section_evidence(self, title):
        return [e for e in self.evidence if e["section"] == title]

    def add_evidence(self, item: dict) -> bool:
        """按 (归一化URL, claim) 去重入库。返回是否真正新增。"""
        key = (norm_url(item["url"]), item["claim"].strip())
        if key in self._ev_keys:
            return False
        self._ev_keys.add(key)
        item["id"] = f"E{len(self.evidence)+1}"
        self.evidence.append(item)
        return True

    def brief_view(self, sec, rescue: bool = False) -> str:
        ev = self.section_evidence(sec["title"])
        met = [c["text"] for c in sec["criteria"] if c["met"]]
        unmet = [c["text"] for c in sec["criteria"] if not c["met"]]
        view = {
            "任务": self.question, "章节": sec["title"],
            "已满足的判据": met, "未满足的判据": unmet,
            "已有证据摘要": [e["claim"][:80] for e in ev][-8:],
            "已搜过的查询(勿重复)": sorted(self.searched_queries)[-15:],
        }
        if rescue:
            view["补搜指令"] = ("常规检索未能满足上述判据。请换策略：1) 改用英文查询；"
                               "2) 换检索角度（实体别名、事件动词、上下游主体）；"
                               "3) 只针对未满足的判据，不要重复已覆盖内容。")
        return json.dumps(view, ensure_ascii=False)


# ---------------- 组件 1：规划器（出大纲+完成判据） ----------------

def plan(state: ResearchState, logger: TraceLogger):
    outline = chat_json(
        [{"role": "user", "content":
          f"今天是 {now_str()}。为下面的研究任务设计 4-6 节的报告大纲。"
          f"关键要求：\n"
          f"1. 为每一节写出 2-4 条「完成判据」——收集到哪些具体信息该节才算研究完成，"
          f"判据必须具体可核查（如“至少三家厂商的量产时间表”而非“了解行业情况”）；\n"
          f"2. 任务中点名的具体实体、数量要求（如“各举两例”）必须逐一落进对应节的判据；\n"
          f"3. 不要设计“结论/总结/建议”节，结论由系统在写作阶段基于全文自动生成。\n"
          f'只输出 JSON：[{{"title":"节标题","criteria":["判据1","判据2"]}}]\n\n任务：{state.question}'}],
        logger=logger, tag="plan")
    for sec in outline:
        state.sections.append({
            "title": sec["title"],
            "criteria": [{"text": c, "met": False} for c in sec["criteria"]],
            "done": False, "stall": 0, "rounds": 0})


# ---------------- 组件 2：搜索工人（与 C 相同，独立上下文） ----------------

def search_worker(brief: str, logger: TraceLogger) -> list[dict]:
    queries = chat_json(
        [{"role": "user", "content":
          f"你是研究助理，刚接手下面的调查任务 brief。请设计 3 条互补的搜索查询"
          f"（角度不同、避开 brief 中已搜过的；若 brief 含补搜指令则严格遵循），"
          f"只输出 JSON 数组[\"q1\",\"q2\",\"q3\"]。\n\n{brief}"}],
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
        return [{"queries": queries}]
    corpus = "\n\n===\n\n".join(
        f"[{i}] {p['title']} ({p['url']})\n{p['body']}" for i, p in enumerate(pages))
    extracted = chat_json(
        [{"role": "user", "content":
          f"任务 brief：\n{brief}\n\n下面是检索到的网页。请抽取与 brief 中「未满足的判据」相关的证据，"
          f"每条包含：claim（一句话论断）、quote（支撑它的原文片段，逐字摘录不改写，≤120字）、src（网页编号）。"
          f"只抽取网页中确实存在的内容，最多 10 条，优先信息密度高的。只输出 JSON："
          f'[{{"claim":"...","quote":"...","src":0}}]\n\n{corpus[:24000]}'}],
        logger=logger, tag="worker:extract", max_tokens=4500)
    out = [{"queries": queries}]
    for e in extracted:
        try:
            p = pages[int(e["src"])]
            out.append({"claim": e["claim"], "quote": e["quote"],
                        "url": p["url"], "title": p["title"]})
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    return out


# ---------------- 组件 3+4：缺口循环 + 预算统筹 + 补搜 ----------------

def _do_round(state, sec, logger, rescue=False) -> int:
    """执行一轮检索并更新判据，返回新增证据数。"""
    results = search_worker(state.brief_view(sec, rescue=rescue), logger)
    new_ev = 0
    for item in results:
        if "queries" in item:
            state.searched_queries.update(item["queries"])
            continue
        item["section"] = sec["title"]
        if state.add_evidence(item):
            new_ev += 1
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
    return new_ev


def research_loop(state: ResearchState, logger: TraceLogger):
    rounds = 0
    regular_budget = MAX_ROUNDS - RESCUE_ROUNDS

    while rounds < regular_budget:
        # 只在未达单节上限的节里选缺口最多的（修 q09 首节垄断）
        pool = [s for s in state.open_sections() if s["rounds"] < SECTION_CAP]
        if not pool:
            break
        sec = max(pool, key=lambda s: sum(1 for c in s["criteria"] if not c["met"]))
        new_ev = _do_round(state, sec, logger)
        rounds += 1
        sec["rounds"] += 1
        logger.log("round", section=sec["title"], new_evidence=new_ev, round=rounds)

        sec["stall"] = sec["stall"] + 1 if new_ev == 0 else 0
        if all(c["met"] for c in sec["criteria"]) or sec["stall"] >= MAX_STALL:
            sec["done"] = True
            logger.log("section-close", section=sec["title"],
                       all_met=all(c["met"] for c in sec["criteria"]))

    # 补搜阶段（修 q05 点名实体缺失）：未满足判据的节按缺口从大到小分配补搜池
    rescue_left = MAX_ROUNDS - rounds
    needy = sorted((s for s in state.sections
                    if not all(c["met"] for c in s["criteria"])),
                   key=lambda s: -sum(1 for c in s["criteria"] if not c["met"]))
    for sec in needy:
        if rescue_left <= 0:
            break
        new_ev = _do_round(state, sec, logger, rescue=True)
        rescue_left -= 1
        rounds += 1
        logger.log("rescue-round", section=sec["title"], new_evidence=new_ev,
                   all_met=all(c["met"] for c in sec["criteria"]))
    for sec in state.open_sections():
        sec["done"] = True
        logger.log("section-close", section=sec["title"],
                   all_met=all(c["met"] for c in sec["criteria"]))


# ---------------- 组件 5：写作器（截断检测 + 独立结论节） ----------------

def _write_with_continuation(prompt: str, logger: TraceLogger, tag: str) -> str:
    text = chat([{"role": "user", "content": prompt}],
                model=MODEL_MAIN, logger=logger, tag=tag, max_tokens=4000)
    text = (text or "").rstrip()
    if text and not text.endswith(SENT_END):
        cont = chat(
            [{"role": "user", "content": prompt},
             {"role": "assistant", "content": text},
             {"role": "user", "content": "你的输出在句子中间被截断了。请从断点处继续，"
                                          "只输出剩余部分，不要重复已写内容。"}],
            model=MODEL_MAIN, logger=logger, tag=f"{tag}:cont", max_tokens=2000)
        text = text + (cont or "")
        logger.log("write-continuation", tag=tag)
    return text


def write_report(state: ResearchState, logger: TraceLogger) -> str:
    parts = []
    for sec in state.sections:
        ev = state.section_evidence(sec["title"])
        ev_text = "\n".join(
            f"[{e['id']}] {e['claim']}\n  原文:「{e['quote']}」 来源: {e['url']}" for e in ev)
        prompt = (
            f"今天是 {now_str()}。研究任务：{state.question}\n\n"
            f"撰写报告的「{sec['title']}」一节（600-900字）。规则：\n"
            f"1. 只使用下面编号证据中的信息，行文中用 [E编号] 标注依据；\n"
            f"2. 证据不足的方面明确写“现有资料未覆盖”，不要编造；\n"
            f"3. 有多方数据时对比呈现。\n"
            f"直接输出正文，不要输出节标题。\n\n证据：\n{ev_text[:20000]}")
        text = _write_with_continuation(prompt, logger, f"write:{sec['title']}")
        parts.append(f"## {sec['title']}\n\n{text}")

    # 结论节：基于全文草稿综合，不做证据门控（修 q09 结论饿死）
    draft = "\n\n".join(parts)
    conclusion = _write_with_continuation(
        f"研究任务：{state.question}\n\n下面是报告正文草稿。请撰写「结论」一节（400-600字）：\n"
        f"1. 综合各节的发现，直接回应任务中要求的判断/评估；\n"
        f"2. 只能基于草稿中已有的内容做综合与推断，不得引入任何新事实；\n"
        f"3. 观点明确，不要复述各节内容。\n直接输出正文。\n\n草稿：\n{draft[:30000]}",
        logger, "write:结论")
    parts.append(f"## 结论\n\n{conclusion}")

    # 参考文献按 URL 合并（修 q09 引用重复）
    seen, refs = set(), []
    for e in state.evidence:
        u = norm_url(e["url"])
        if u not in seen:
            seen.add(u)
            refs.append(f"- [{e['id']}] {e['title']} — {e['url']}")
    return "# 研究报告\n\n" + "\n\n".join(parts) + "\n\n## 参考来源\n\n" + "\n".join(refs)


def run(question: str, logger: TraceLogger) -> str:
    state = ResearchState(question)
    plan(state, logger)
    research_loop(state, logger)
    return write_report(state, logger)


if __name__ == "__main__":
    logger = TraceLogger("/tmp/armC2_smoke.jsonl")
    report = run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。", logger)
    print(report[:2000])
    print("\n=== tokens:", logger.tokens)
