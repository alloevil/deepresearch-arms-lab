"""Arm F9：证据绑定写作（evidence-grounded writing）。

诊断依据（fact 全量批 + fact-v2，2026-07-08）：not_found ~28% 是三 arm 共性
水位，根因是「数据打包句」与「跨源引用错位」，且 B3 消融证明行为由协议 prompt
决定、外部修订机制中性。故 F9 的修法在写作方式本身：

- 检索时把要用的证据**逐字摘录**存 evidence.jsonl（id + url + quote≤200字）；
- 写作时每个事实论断句末标 [En]，一句一证据；论断强度不得超过 quote 原文；
- 跨证据综合判断标 [综合 E2,E5] 或不标（视为分析）。

机械件（非修订回路，保持 B3 式"无外部退回"纯度）：
1. 渲染：成文后把 [En] 机械替换为（url），fact 核验器可直接解析；
2. 摘录审计：quote 是逐字的 → 验证从 LLM 判定降级为**代码子串匹配**
   （"LLM 做抽取、代码做判断"），结果记 quote_check.json，不退回修改。

对照关系：B3（协议 prompt） vs F9（协议 prompt 的引用条款换成证据绑定）。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger, now_str, read_page  # noqa: E402
from common.verify_cli import extract_rubric  # noqa: E402
from arms.arm_f8_scaffold import (  # noqa: E402 — 复用基础设施与非引用条款
    SEARCH_CLI, VERIFY_CLI, _rubric_text, _run_claude)

# 与 F8/B3 协议同构：1-4c/6 条逐字一致；差异仅在第 5/7 条（引用方式）——
# 保证 F9 vs B3 的对比是"引用条款"单变量
PROMPT = """今天是 {date}。你是一名研究员，请完成下面的深度研究任务，产出一份带来源引用的中文研究报告。

【研究任务】
{question}

【任务硬性要求】（系统已从任务中抽取，验收时按此核对，见 rubric.json）
{rubric_text}

【可用工具】
- python3 {cli} search "查询词" —— 搜索，返回 JSON 结果（内置网页搜索不可用）
- python3 {cli} read "URL" —— 读取网页正文
- python3 {vcli} check {out} --question question.txt --rubric rubric.json --extended --actions ——
  质量自检（截断/引用/信源多样性/硬性要求），返回 JSON 失败清单

【研究协议（必须遵守）】
1. 上面的「任务硬性要求」就是你的 checklist——把它复制进 checklist.md 并在
   研究过程中逐项勾选。
2. 拟报告大纲，为每节写出完成判据（需要哪些具体证据该节才算可写）。
3. 检索优先覆盖清单未满足项；某项检索不到时必须换语言（英文）、换角度再试至少一次。
4. 【信源纪律】每个主体章节的关键论断至少要有两个不同网站的来源交叉支撑，
   其中至少一个为权威来源（官方/国际机构/主流媒体/学术）；博客与自媒体只能作
   补充信源，不得超过全部引用的三分之一。
4b.【篇幅纪律】每个主体章节 700-1200 字；宁可信息密集，不要复述与注水。
4c.【rubric 生长】研究中若发现任务隐含的新验收要点（如新的关键主体/必要对比），
   把它追加到 rubric.json 的 "discovered" 数组（只增不改),后续核对将包含它们。
5. 【证据绑定写作——本任务核心纪律】
   a) 检索/阅读过程中，凡是之后要写进报告的事实，先把证据登记进 evidence.jsonl
      （一行一条 JSON）：{{"id": "E1", "url": "来源URL", "quote": "从网页正文逐字
      复制的原文片段（≤200字）"}}。quote 必须逐字复制页面原文，不得改写、概括
      或翻译（英文页面就存英文原文）。
   b) 写作时，每个事实论断的句末标注其证据 ID，如「……出货量达 5 GWh[E3]。」
      一句话只承载一条证据里的事实；来自不同证据的事实必须拆成不同句子、
      各标各的 ID。禁止多个事实共享一个句末 ID。
   c) 论断措辞强度不得超过 quote 原文：原文是"计划/目标/预计"，不得写成
      "将/已经/确定"；原文没有的数字与结论不得出现。
   d) 跨证据的综合判断（对比结论、趋势判断、评估）标注全部依据，如
      「……整体呈加速态势[综合 E2,E5]。」纯属你的分析推断可不标 ID。
   e) 深度四要素不变——每个主体章节须覆盖：具体数据点、多方对比、机制解释、
      批判性评估。拆句是把打包的事实分开各自配证据，**不是少写**；无证据
      登记的事实不得写入。
6. 【内省自检】把报告写入 {out} 后，必须运行上面的质量自检命令，若返回
   failures 非空，按失败项修改报告（缺证据的先补搜）后重新自检，直到通过
   或已尽力（最多自检 3 次）。
7. 报告用 Markdown 分节。正文中只用 [En]/[综合 En,Em] 标注，不要直接写 URL，
   也不需要"参考来源"一节——系统会把标注机械替换为链接。

最终报告写入 {out}（只写报告本身）。"""

# agent 实测会自创带字母后缀的 ID(E17c 等),正则须兼容
_CIT_RE = re.compile(
    r"\[\s*(?:综合[:：]?\s*)?(E\d+[a-z]?(?:\s*[,，]\s*E\d+[a-z]?)*)\s*\]")


def _load_evidence(workdir: Path) -> dict:
    ev = {}
    f = workdir / "evidence.jsonl"
    if not f.exists():
        return ev
    for line in f.read_text().splitlines():
        try:
            e = json.loads(line)
            if e.get("id") and e.get("url"):
                ev[str(e["id"]).strip()] = e
        except json.JSONDecodeError:
            continue
    return ev


def _render_citations(report: str, ev: dict, logger: TraceLogger) -> str:
    """脚注式渲染：正文 [En] → 数字上标 [n]，唯一来源集中到文末"参考来源"节。
    高引用密度题上内联长 URL 会堆砌损害可读性（扩展题 e08 裁判实证 readability
    −0.46）——脚注式正文只留短标记，同源 URL 复用同一编号,可核验性不变
    （解析器已支持"正文 [n] + 文末 [n] URL"数字编号形态）。未知 ID 原样保留。"""
    missing = []
    order = {}  # url -> 顺次编号,保证同源复用同一 [n]

    def _num(url):
        if url not in order:
            order[url] = len(order) + 1
        return order[url]

    def repl(m):
        ids = [s.strip() for s in re.split(r"[,，]", m.group(1))]
        urls = list(dict.fromkeys(ev[i]["url"] for i in ids if i in ev))
        missing.extend(i for i in ids if i not in ev)
        if not urls:
            return m.group(0)
        return "".join(f"[{_num(u)}]" for u in urls)

    body = _CIT_RE.sub(repl, report)
    if order:
        refs = "\n".join(f"[{n}] {u}" for u, n in
                         sorted(order.items(), key=lambda kv: kv[1]))
        body = body.rstrip() + "\n\n## 参考来源\n\n" + refs + "\n"
    logger.log("f9-render", n_markers=len(_CIT_RE.findall(report)),
               n_evidence=len(ev), n_sources=len(order),
               missing_ids=sorted(set(missing))[:10])
    return body


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _quote_align(quote_norm: str, page_norm: str,
                 min_ratio: float = 0.75) -> str | None:
    """模糊对齐：agent 改写过的摘录,从页面原文找最相似的等长段回填。
    先用最长公共子串定位锚点,再在锚点邻域滑窗取最大相似度(partial-ratio
    思路,避免固定窗口把无关前后文卷进来稀释相似度)。相似度不足返回 None。"""
    from difflib import SequenceMatcher
    if not quote_norm or not page_norm:
        return None
    sm = SequenceMatcher(None, page_norm, quote_norm, autojunk=False)
    m = sm.find_longest_match(0, len(page_norm), 0, len(quote_norm))
    if m.size < 8:  # 连 8 字符的公共片段都没有,不可能是同段改写
        return None
    L = len(quote_norm)
    region = page_norm[max(0, m.a - L):min(len(page_norm), m.a + m.size + L)]

    def _scan(lo, hi, step):
        best, best_w, best_i = 0.0, None, lo
        for i in range(lo, max(lo + 1, hi), step):
            for wl in (L, L + 20):  # 两种窗长:等长(改写)与略长(有增删)
                w = region[i:i + wl]
                r = SequenceMatcher(None, w, quote_norm, autojunk=False).ratio()
                if r > best:
                    best, best_w, best_i = r, w, i
        return best, best_w, best_i

    step = max(1, L // 8)
    best, best_w, best_i = _scan(0, len(region) - L + 1, step)
    if step > 1:  # 粗定位后邻域精扫,避免步长跳过最优起点
        b2, w2, _ = _scan(max(0, best_i - step), best_i + step, 1)
        if b2 > best:
            best, best_w = b2, w2
    return best_w if best >= min_ratio else None


def _quote_check(ev: dict, workdir: Path, logger: TraceLogger) -> None:
    """摘录审计（纯代码，无 LLM）：quote 归一化空白后是否为页面原文子串；
    不逐字的尝试模糊对齐回填页面原文（quote_aligned 字段,原 quote 保留可审计）。
    只记录不退回——防 agent 编造摘录的审计轨迹。verdict:
    verbatim(逐字) > aligned(改写但可对齐回原文) > not_verbatim(对不上,
    疑似跨页拼接或编造) > unreachable / empty。"""
    rows, dirty = [], False
    for eid, e in ev.items():
        quote = _norm_ws(str(e.get("quote", "")))
        if not quote:
            rows.append({"id": eid, "verdict": "empty"})
            continue
        page = read_page(e["url"], max_chars=60000)
        if not page or len(page) < 100:
            rows.append({"id": eid, "verdict": "unreachable"})
            continue
        page_norm = _norm_ws(page)
        if quote[:400] in page_norm:
            rows.append({"id": eid, "verdict": "verbatim"})
            continue
        aligned = _quote_align(quote[:400], page_norm)
        if aligned:
            e["quote_aligned"] = aligned[:300]
            dirty = True
            rows.append({"id": eid, "verdict": "aligned"})
        else:
            rows.append({"id": eid, "verdict": "not_verbatim"})
    if dirty:  # 对齐结果写回台账,后续句级核验(fact-ev)优先用页面原文
        (workdir / "evidence.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in ev.values()))
    stats = {k: sum(1 for r in rows if r["verdict"] == k)
             for k in ("verbatim", "aligned", "not_verbatim",
                       "unreachable", "empty")}
    (workdir / "quote_check.json").write_text(
        json.dumps({"stats": stats, "detail": rows}, ensure_ascii=False))
    logger.log("f9-quote-check", **stats)


def _run_evidence_arm(question: str, logger: TraceLogger, workdir: Path,
                      prompt_tpl: str) -> str:
    """F9 系共用执行体：协议跑 draft → 落 report_raw.md（[En] 版，供句级
    本地核验）→ 机械渲染 [En]→URL → quote 逐字审计（不阻断）。"""
    out_file = workdir / "report.md"
    rubric = extract_rubric(question)
    (workdir / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False))
    (workdir / "question.txt").write_text(question)
    logger.log("rubric", **{k: rubric.get(k) for k in ("entities", "counts", "actions")})

    _run_claude(prompt_tpl.format(date=now_str(), question=question,
                                  cli=SEARCH_CLI, vcli=VERIFY_CLI, out=out_file,
                                  rubric_text=_rubric_text(rubric)),
                workdir, logger, "draft")
    if not out_file.exists() or len(out_file.read_text()) < 1000:
        raise RuntimeError("draft report missing or too short")

    raw = out_file.read_text()
    (workdir / "report_raw.md").write_text(raw)
    ev = _load_evidence(workdir)
    report = _render_citations(raw, ev, logger)
    out_file.write_text(report)
    try:
        _quote_check(ev, workdir, logger)  # 审计不阻断
    except Exception as e:  # noqa: BLE001
        logger.log("f9-quote-check-error", error=str(e)[:200])
    logger.log("no-external-verify",
               note="F9-family: evidence-bound draft shipped as-is (no revision loop)")
    return report


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    return _run_evidence_arm(question, logger, workdir, PROMPT)


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF9_"))
    logger = TraceLogger("/tmp/armF9_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商，并评估其中一家的降本路径。",
              logger, wd)[:1200])
