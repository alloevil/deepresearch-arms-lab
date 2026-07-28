#!/usr/bin/env python3
"""产物验证器：对生成的研究报告做输出端核查（arm F 的终检门，可独立使用）。

设计原则："LLM 做抽取、代码做判断"（C3 验证有效的原则搬到输出端）：
- 截断检测 / 引用重复率 / 段落引用覆盖率：纯机械
- 任务硬性要求（点名实体、数量要求）：快模型从题目和报告中做抽取，代码比对

用法:
  verify_cli.py check <report.md> --question "<任务原文或文件路径>"
输出 JSON: {"pass": bool, "failures": [...], "stats": {...}}
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import MODEL_FAST, chat_json, chat_json_eval, model_verify  # noqa: E402

# LLM 通道分工（勿混用，否则污染被测系统或客观轴）：
# - 机制侧（extract_rubric / check_requirements，F 系 arm 运行时自检）：
#   chat_json + MODEL_FAST —— 属于被测系统的一部分，必须与执行器同通道。
# - 评测侧（check_citation_support[_v2] / check_claims_vs_evidence，--fact 系）：
#   chat_json_eval + model_verify() —— 客观轴须独立于执行器（MiMo 核验 MiMo
#   = 自评闭环），MiMo 批次设 LAB_EVAL_BASE_URL / LAB_MODEL_VERIFY。

SENT_END = tuple("。！？.!?”』\"）)]】>》—*`|")

# 信源权威性分级（启发式;判"低"比判"高"可靠,故只列低档）
LOW_TIER = re.compile(
    r"blog|medium\.com|substack|jianshu|csdn|baijiahao|weixin|mp\.weixin|"
    r"zhihu\.com/p/|sohu\.com/a/|163\.com/dy/|toutiao|xueqiu|bilibili|"
    r"youtube|reddit|quora|wordpress|foodlore", re.I)
HIGH_TIER = re.compile(
    r"\.gov(\.|/)|\.edu(\.|/)|\.int/|imf\.org|worldbank|oecd|un\.org|bis\.org|"
    r"ecb\.europa|europa\.eu|stats\.|census|reuters|bloomberg|ft\.com|wsj\.com|"
    r"economist|xinhuanet|people\.com\.cn|gov\.cn|cctv|caixin|yicai|"
    r"nature\.com|science\.org|ieee|acm\.org|arxiv", re.I)

# 深度四要素的机械信号词（宁宽勿严:漏报可接受,误报会驱动无谓修订）
DEPTH_MARKERS = {
    "数据点": re.compile(r"\d+(\.\d+)?\s*[%％亿万美元元GWhkWh年月日倍家个]|20\d\d年"),
    "多方对比": re.compile(r"相比|而.{0,6}则|高于|低于|反观|不同于|对比|对照|差异|"
                          r"相较|较之|各自|分别|vs\.?|另一方面|与此同时"),
    "机制解释": re.compile(r"因为|由于|导致|源于|根源|背后|使得|从而|归因|原因在于|"
                          r"驱动|机制|本质|受制于|取决于|依赖于|逻辑(是|在于)"),
    "批判评估": re.compile(r"存疑|局限|不确定|矛盾|口径|需谨慎|可信度|风险在于|反例|"
                          r"质疑|瓶颈|不足|难以|尚未|待验证|警惕|偏差|"
                          r"然而|但.{0,8}(仍|并未|尚|值得注意)"),
}


def _sections(body: str):
    for m in re.finditer(r"^## (.+?)$\n(.*?)(?=^## |\Z)", body, re.M | re.S):
        title, text = m.group(1).strip(), m.group(2).strip()
        if "参考" in title or "references" in title.lower():
            continue
        yield title, text


def check_source_quality(body: str) -> tuple[list[str], dict]:
    """信源权威性：低档信源(博客/自媒体)占比过高,或关键节完全依赖低档信源。"""
    fails = []
    urls = re.findall(r"https?://[^\s)）\]」]+", body)
    if not urls:
        return [], {}
    low = [u for u in urls if LOW_TIER.search(u)]
    high = [u for u in urls if HIGH_TIER.search(u)]
    ratio = len(low) / len(urls)
    if ratio > 0.4:
        doms = sorted({re.sub(r'https?://([^/]+).*', r'\1', u) for u in low})[:4]
        fails.append(f"低权威信源(博客/自媒体)占引用 {ratio:.0%}（如 {doms}），"
                     f"关键论断请补充官方/机构/主流媒体信源交叉验证")
    for title, text in _sections(body):
        sec_urls = re.findall(r"https?://[^\s)）\]」]+", text)
        if len(sec_urls) >= 3 and all(LOW_TIER.search(u) for u in sec_urls):
            fails.append(f"「{title}」节引用全部来自低权威信源，需至少一个权威来源")
    return fails, {"low_ratio": round(ratio, 2), "high_count": len(high)}


def check_depth_markers(body: str) -> tuple[list[str], dict]:
    """深度四要素的机械检测：主体节缺 ≥3 个要素信号才报（粗网,只抓明显单薄）。"""
    fails, per_sec = [], {}
    for title, text in _sections(body):
        if len(text) < 400 or "结论" in title:
            continue
        has_table = bool(re.search(r"^\|.+\|.+\|$", text, re.M))
        missing = []
        for name, pat in DEPTH_MARKERS.items():
            if name == "多方对比" and has_table:   # markdown 表格视为对比呈现
                continue
            if len(pat.findall(text)) < (3 if name == "数据点" else 1):
                missing.append(name)
        per_sec[title[:16]] = missing
        if len(missing) >= 3:
            fails.append(f"「{title}」节深度要素不足，缺：{missing}"
                         f"（需补充：数据点=具体数字，多方对比，机制解释，批判性评估）")
    return fails, per_sec


def check_verbosity(body: str) -> list[str]:
    """冗长检测：节超长或引用密度过低。"""
    fails = []
    for title, text in _sections(body):
        if len(text) > 3000:
            n_cite = len(re.findall(r"https?://|\[E?\d+\]|\[\^", text))
            density = n_cite / (len(text) / 1000)
            if density < 1.0:
                fails.append(f"「{title}」节 {len(text)} 字但引用密度低"
                             f"({density:.1f}/千字)，疑似冗长注水，请压缩为信息密集的表述")
    return fails


def check_truncation(body: str) -> list[str]:
    fails = []
    # 按二级标题切节，检查每节末尾是否句子中断
    for m in re.finditer(r"^## (.+?)$\n(.*?)(?=^## |\Z)", body, re.M | re.S):
        title, text = m.group(1).strip(), m.group(2).strip()
        if ("参考" in title or "references" in title.lower()) or len(text) < 80:
            continue
        # 剥掉尾部的分隔线、引用标记；URL 剥离不吃闭括号（否则会把
        # "([X](url))" 拆成 "([X](" 造成假阳性——闭括号本身就是合法句尾）
        tail = text
        for _ in range(4):
            new = re.sub(r"(\s*-{2,}\s*|\s*[\(（]?\[(来源|source)[:：][^\]]*\][\)）]?\s*|"
                         r"\s*\[E?\d+\]\s*|\s*\[\^[^\]]*\]\s*|"
                         r"\s*https?://[^\s)）\]]*)$",
                         "", tail, flags=re.I).rstrip()
            if new == tail:
                break
            tail = new
        if tail and not tail.endswith(SENT_END):
            fails.append(f"「{title}」节末尾疑似截断: …{tail[-40:]}")
    return fails


def check_source_diversity(body: str) -> tuple[list[str], dict]:
    """主体章节的信源集中度：一节引用 ≥3 处但域名 ≤1 个 → 单一信源风险。"""
    fails, per_sec = [], {}
    for m in re.finditer(r"^## (.+?)$\n(.*?)(?=^## |\Z)", body, re.M | re.S):
        title, text = m.group(1).strip(), m.group(2).strip()
        if ("参考" in title or "结论" in title or "references" in title.lower()) \
                or len(text) < 300:
            continue
        urls = re.findall(r"https?://([^/\s\])」]+)", text)
        domains = {u.lower().lstrip("www.") for u in urls}
        per_sec[title[:20]] = len(domains)
        if len(urls) >= 3 and len(domains) <= 1:
            fails.append(f"「{title}」节全部引用来自单一域名"
                         f"（{next(iter(domains), '?')}），需补充独立信源交叉验证")
    return fails, per_sec


def check_ref_dup(body: str) -> tuple[list[str], float]:
    urls = re.findall(r"https?://\S+", body)
    if not urls:
        return (["报告中没有任何 URL 引用"], 0.0)
    norm = [u.split("#")[0].split("?")[0].rstrip("/).,;」』】") for u in urls]
    ratio = len(set(norm)) / len(norm)
    fails = []
    if ratio < 0.4 and len(norm) > 15:
        fails.append(f"引用重复严重: {len(norm)} 处 URL 去重后仅 {len(set(norm))} 个")
    return fails, round(ratio, 2)


def check_citation_coverage(body: str) -> tuple[list[str], float]:
    paras = [p for p in body.split("\n\n") if len(p.strip()) > 150
             and not p.strip().startswith(("#", "-", "*", "|", ">"))]
    if not paras:
        return [], 1.0
    cited = sum(1 for p in paras
                if re.search(r"https?://|\[E?\d+\]|\[\^", p))
    ratio = cited / len(paras)
    fails = []
    if ratio < 0.5:
        fails.append(f"正文段落引用覆盖率过低: {cited}/{len(paras)} 段有引用")
    return fails, round(ratio, 2)


def extract_rubric(question: str) -> dict:
    """从题目抽取结构化硬性要求（一次抽取,协议与验证共用同一份标准）。"""
    return chat_json(
        [{"role": "user", "content":
          f"分析下面研究任务的硬性要求，只输出 JSON："
          f'{{"entities":["任务点名的具体实体（公司/国家/项目名等,没有则空）"],'
          f'"counts":[{{"what":"要求列举的对象类型","min":数量}}],'
          f'"actions":["任务要求的动作,如 对比/评估可能性/给出建议"],'
          f'"task_type":"enumerative|comparative|evaluative|exploratory",'
          f'"type_evidence":"≤20字判定依据"}}\n'
          f"数量要求示例：“各举两例”→ 对每类各一条 counts。\n"
          f"task_type 判定：要求评估可能性/前景/是否可行（最终交付判断）→ evaluative；"
          f"以对比/差异为主 → comparative；以“各举N例/列出”为主 → enumerative；"
          f"仅梳理现状进展 → exploratory。混合任务取最终交付物的类型。\n\n任务：{question}"}],
        model=MODEL_FAST)


# 类型专属验收的机械信号（v7）
_CONDITIONAL_PAT = re.compile(r"若.{1,24}[则将]|如果.{1,24}(那么|则|将)|一旦.{1,20}[则将就]")
_FENCE_SIT_PAT = re.compile(r"机遇与挑战并存|有待观察|仁者见仁|还需时间检验|前景喜忧参半|尚难定论")
_COUNTER_PAT = re.compile(r"反方|另一种观点|看空|质疑(者|声音)|反对观点|悲观(者|观点)|批评者|然而也有观点")


def check_type_requirements(body: str, task_type: str | None) -> list[str]:
    """任务类型专属验收（v7）：协议按类型提要求,这里按类型机械核对。"""
    if not task_type:
        return []
    fails = []
    if task_type == "evaluative":
        tail = ""
        for title, text in _sections(body):
            if re.search(r"结论|评估|判断|前景|展望", title):
                tail += text + "\n"
        tail = tail or body[-3000:]
        if not _CONDITIONAL_PAT.search(tail):
            fails.append("评估型任务要求条件化判断（“若X则Y”式结论），当前结论缺少"
                         "明确的条件-结果表述")
        if _FENCE_SIT_PAT.search(tail) and not _CONDITIONAL_PAT.search(tail):
            fails.append("评估结论存在骑墙表述（如“机遇与挑战并存”）且无明确判断，"
                         "请给出立场、置信依据与可观察的先行指标")
        if not _COUNTER_PAT.search(body):
            fails.append("评估型任务要求呈现并回应最强反方论点，报告中未见反方观点")
    elif task_type == "comparative":
        has_table = bool(re.search(r"^\|.+\|.+\|$", body, re.M))
        cmp_hits = len(DEPTH_MARKERS["多方对比"].findall(body))
        if not has_table and cmp_hits < 8:
            fails.append("对比型任务要求结构化对比（统一维度的对比表或密集的并列比较），"
                         "当前各主体缺乏同维度对话")
    return fails


def check_requirements(question: str, body: str, rubric: dict | None = None,
                       check_actions: bool = False, logger=None) -> tuple[list[str], list[str]]:
    """题目硬性要求核对：抽取靠快模型，比对靠代码。可传入预生成 rubric 保证
    与研究协议同源（否则每次独立抽取,可能与 agent 的 checklist 打架）。

    返回 (fails, errors)：fails 是报告的质量问题；errors 是检查基础设施故障
    （如快模型不可用）——不计入 pass 判定，否则 infra 抖动会触发无谓的修订循环。"""
    req = dict(rubric) if rubric is not None else extract_rubric(question)
    # discovered（agent 研究中追加的验收项）在此统一合并——保证 agent 自检
    # （CLI --rubric）与外部门禁走同一套标准（v6 修复:此前 CLI 路径忽略 discovered）
    for d in req.get("discovered") or []:
        if isinstance(d, str):
            req.setdefault("entities", []).append(d)
        elif isinstance(d, dict) and d.get("what"):
            req.setdefault("counts", []).append(d)
    fails, errors = [], []
    for ent in req.get("entities", []):
        if ent and ent not in body:
            fails.append(f"任务点名的「{ent}」未在报告中出现")
    for c in req.get("counts", []):
        what, need = c.get("what", ""), int(c.get("min") or 0)
        if not what or need <= 0:
            continue
        try:
            names = chat_json(
                [{"role": "user", "content":
                  f"从下面的研究报告中抽取所有被实质分析（有具体事实/数据，非仅提及）的"
                  f"「{what}」的名称，同一实体不同叫法只算一个。只输出 JSON 数组。\n\n"
                  f"报告：{body[:28000]}"}],
                model=MODEL_FAST)
            found = len({str(x).strip() for x in names if str(x).strip()})
            if found < need:
                fails.append(f"「{what}」要求至少 {need} 个，报告中实质分析了 {found} 个")
        except Exception as e:
            errors.append(f"「{what}」数量检查跳过（LLM不可用: {e}）")
    # actions 验收（v6 修复:此前抽取了却从不核对——指令遵循的最大漏洞）。
    # 快模型逐条判定,宁严勿松;失败信息带证据要求,供修订定位。
    if check_actions and req.get("actions"):
        try:
            verdicts = chat_json(
                [{"role": "user", "content":
                  f"研究任务要求完成以下动作。逐条判断下面的报告是否「实质完成」了"
                  f"该动作——必须有对应的分析内容（如'对比'需有并列比较,'评估可能性'"
                  f"需有明确判断与依据),仅提及不算。宁严勿松。\n"
                  f"动作：{json.dumps(req['actions'], ensure_ascii=False)}\n"
                  f'只输出 JSON（与动作等长）：[{{"done": true, "why": "≤20字"}}]\n\n'
                  f"报告：{body[:28000]}"}],
                model=MODEL_FAST)
            for a, v in zip(req["actions"], verdicts):
                if not v.get("done"):
                    fails.append(f"任务要求的动作「{a}」未实质完成"
                                 f"（{v.get('why', '')}），请补充对应分析")
        except Exception as e:
            errors.append(f"动作检查跳过（LLM不可用: {e}）")
    return fails, errors


def _claim_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(
        r"https?://\S+|[\[\(（][^\]\)）]*[\]\)）]", "", s)).strip(" ->#*")


def _clip_claim(text: str, limit: int = 400) -> str:
    """句界感知截断：按句累积不超 limit，绝不产生悬空残句。

    旧实现 text[:200] 会把长打包段剁出残句（如"这一数字较 2023 年增长[断]"），
    残句进核验器被判 not_found/冲突——mimo_smoke 批实测的矛盾假阳根因。
    找不到句界（≥40 字内无句末标点）时才退化为硬截断。"""
    if len(text) <= limit:
        return text
    kept = ""
    for m in re.finditer(r"[^。！？!?；;]*[。！？!?；;]", text):
        if len(kept) + len(m.group(0)) > limit:
            break
        kept += m.group(0)
    return kept if len(kept) >= 40 else text[:limit]


def _extract_citation_pairs(body: str) -> tuple[list[dict], list[list[str]]]:
    """解析报告中的"论断-引用"对（内联 / 来源行 / 脚注三种形态）。

    返回 (pairs, para_urls)：
      pairs = [{"claim", "urls", "pi"}]，pi 为论断所在段索引；
      para_urls[i] = 第 i 段可解析到的全部 URL（含脚注解引用），供邻近池诊断。
    """
    # 脚注式引用（正文 [^n] 标记 + 文末 [^n]: 说明 URL 定义）——B3 等 arm 用此格式，
    # 文末定义块连续无空行会被当超长段落整体丢弃，正文 [^n] 段又无内联 http URL 被跳过
    footnotes = {}
    for m in re.finditer(r"\[\^([^\]]+)\]:\s*(.+)", body):
        fn_urls = re.findall(r"https?://[^\s)）\]」]+", m.group(2))
        if fn_urls:
            footnotes[m.group(1)] = fn_urls[0].rstrip(".,;」』")
    # 数字编号式（正文 [11] + 文末 "[11] 标题 — URL" 列表）——B3 引用格式随批漂移
    # 出现的第四种形态（2026-07-09 批）
    for m in re.finditer(r"^\[(\d{1,3})\][:.]?\s*(.+)$", body, re.M):
        fn_urls = re.findall(r"https?://[^\s)）\]」]+", m.group(2))
        if fn_urls and m.group(1) not in footnotes:
            footnotes[m.group(1)] = fn_urls[0].rstrip(".,;」』")
    # 有序列表式（正文 [n] + 文末 "n. 标题 — URL" Markdown 列表）——第五种形态
    # （2026-07-17 MiMo 批,同批内 q01/q09_B 即漂到此式）。已占编号不覆盖,
    # 方括号/脚注定义优先。
    for m in re.finditer(r"^(\d{1,3})[.、)]\s*(.+)$", body, re.M):
        fn_urls = re.findall(r"https?://[^\s)）\]」]+", m.group(2))
        if fn_urls and m.group(1) not in footnotes:
            footnotes[m.group(1)] = fn_urls[0].rstrip(".,;」』")
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    pairs, para_urls = [], []
    for i, para in enumerate(paras):
        is_fn_def = bool(re.match(r"\s*\[(?:\^[^\]]+|\d{1,3})\][:.]?\s", para)) \
            or len(re.findall(r"^\d{1,3}[.、)]\s.*https?://", para, re.M)) >= 2
        urls = [u.rstrip(".,;」』")
                for u in re.findall(r"https?://[^\s)）\]」]+", para)]
        ref_ids = (re.findall(r"\[\^([^\]]+)\]", para)
                   + re.findall(r"\[(\d{1,3})\]", para)) \
            if footnotes and not is_fn_def else []
        fn_hit = [footnotes[r] for r in ref_ids if r in footnotes]
        para_urls.append([] if is_fn_def else urls + fn_hit)
        if not urls:
            # 脚注引用段落：无内联 URL 但含 [^n] 标记，URL 从文末定义取
            if fn_hit and not is_fn_def and not para.startswith(("#", "|", ">")):
                text = _claim_text(para)
                if 40 < len(text) < 800:
                    pairs.append({"claim": _clip_claim(text), "urls": fn_hit[:2],
                                  "pi": i})
            continue
        # 形态一：独立来源行（"> 来源：…"），论断取上一个正文段
        if re.match(r">?\s*(来源|source|参考)[：:]", para, re.I) and i > 0:
            claim_src = paras[i - 1]
        # 形态二：URL 嵌在正文段内（排除文末脚注定义行——那是来源标题不是论断）
        elif not para.startswith(("#", "|", ">")) and not is_fn_def:
            claim_src = para
        else:
            continue
        text = _claim_text(claim_src)
        if 40 < len(text) < 800:
            # 来源行常列多个 URL 共同支撑,取前 2 个,任一支撑即算支撑
            pairs.append({"claim": _clip_claim(text), "urls": urls[:2], "pi": i})
    return pairs, para_urls


def check_citation_support(body: str, sample: int = 4) -> tuple[list[str], dict]:
    """引用支撑性抽查（贵：抓网页 + LLM 判定，只在 deep 模式跑）。

    从"论断 + 同段 URL"对中抽样，抓取网页正文，用快模型判断是否支撑。
    """
    from common.core import read_page
    pair_dicts, _ = _extract_citation_pairs(body)
    pairs = [(p["claim"], p["urls"]) for p in pair_dicts]
    if not pairs:
        return [], {"sampled": 0, "total_pairs": 0}
    if sample <= 0:  # 全量核实(Cited-but-Not-Verified 式全解析,不抽样)
        sampled = pairs
    else:
        step = max(1, len(pairs) // sample)
        sampled = pairs[::step][:sample]
    verdicts = []
    for claim, urls in sampled:
        best, used = "unreachable", urls[0]
        for url in urls:
            page = read_page(url, max_chars=4000)
            if not page or len(page) < 200:
                continue
            v = chat_json_eval(
                [{"role": "user", "content":
                  f"论断：{claim}\n\n网页内容摘录：{page}\n\n"
                  f'该网页内容是否支撑上述论断（部分支撑也算 supported）？只输出 JSON：'
                  f'{{"verdict":"supported|not_found|contradicted"}}'}],
                model=model_verify())
            verdict = v.get("verdict", "not_found")
            if best == "unreachable" or verdict == "supported":
                best, used = verdict, url
            if verdict == "supported":
                break
        verdicts.append({"url": used, "verdict": best, "claim": claim[:100]})
    bad = [v for v in verdicts if v["verdict"] in ("not_found", "contradicted")]
    fails = []
    if len(bad) >= 2 or any(v["verdict"] == "contradicted" for v in verdicts):
        detail = "；".join(f"不支撑论断：「{b['claim'][:60]}」({b['url'][:60]})"
                           for b in bad[:3])
        fails.append(f"引用抽查 {len(sampled)} 条中 {len(bad)} 条不支撑论断——{detail}"
                     f"——请针对这些论断补搜可支撑的信源，或核实后修改/删除论断")
    n_sup = sum(1 for v in verdicts if v["verdict"] == "supported")
    n_nf = sum(1 for v in verdicts if v["verdict"] == "not_found")
    n_con = sum(1 for v in verdicts if v["verdict"] == "contradicted")
    return fails, {"sampled": len(sampled), "total_pairs": len(pairs),
                   "supported": n_sup, "not_found": n_nf, "contradicted": n_con,
                   # over_cite: 引用未能支撑其论断的对数(DeepTRACE over-citation 度量)
                   "over_cite": n_nf + n_con,
                   "detail": verdicts}


def check_citation_support_v2(body: str) -> dict:
    """fact-v2 分层核验：区分"真超写"与两类测量假象（打包句/引用错位）。

    v1 的两个盲区：①打包句"一损俱损"（一句多事实共享引用，任一子事实不在页
    即整句 not_found）→ 先用快模型拆原子子论断逐条判；②跨源综合句只对单页判
    → 主引用页联合判定 + 失败后试同段/邻段 URL 池（命中=引用错位而非编造）。

    对级 verdict 分层：supported（主引用页联合支撑全部子论断）＞
    supported_by_neighbor（需借邻近页才全支撑=引用错位）＞ partial（部分子论断
    支撑）＞ not_found（真超写）＞ contradicted ｜ unreachable（页面全抓不到）。
    全量核验，无抽样。成本 ≈ 每对 2-3 次快模型调用 + 抓页（进程内缓存）。
    """
    from common.core import read_page
    pairs, para_urls = _extract_citation_pairs(body)
    if not pairs:
        return {"total_pairs": 0}

    def _fetch(urls, limit=2):
        pages = []
        for u in urls[:limit]:
            page = read_page(u, max_chars=3500)
            if page and len(page) >= 200:
                pages.append((u, page))
        return pages

    def _judge(subs, pages) -> list[str]:
        """联合判定：全部页面内容合起来，逐条判子论断。返回与 subs 等长 verdicts。

        矛盾分层（DRAGged into Conflicts 2506.08500 分类学适配）：时效性矛盾
        （信息时点不同）与实质矛盾（同口径对立）行为含义不同——前者可能只是
        报告用了旧数据，后者才是硬错误。表面粒度/表述差异不算矛盾。"""
        ctx = "\n\n".join(f"网页{chr(65+i)}（{u}）：{p}"
                          for i, (u, p) in enumerate(pages))
        subs_text = "\n".join(f"{i}. {s}" for i, s in enumerate(subs))
        v = chat_json_eval(
            [{"role": "user", "content":
              f"下面是 {len(subs)} 条子论断和若干网页内容摘录。逐条判断这些网页"
              f"内容【联合起来】与该子论断的关系，五选一：\n"
              f"- supported: 支撑该论断（部分支撑也算）\n"
              f"- not_found: 页面内容中找不到该论断的依据\n"
              f"- conflict_temporal: 与论断矛盾，但矛盾可能来自信息时点不同"
              f"（如旧时间表 vs 新时间表、数据统计期不同）\n"
              f"- conflict_substantive: 同口径下实质矛盾（数据/结论对立）\n"
              f"- contradicted: 明确矛盾但无法归类上述两种\n"
              f"注意：表面粒度或措辞差异不算矛盾。\n\n"
              f"子论断：\n{subs_text}\n\n{ctx}\n\n"
              f'只输出 JSON 数组（与子论断等长）：'
              f'[{{"idx": 0, "verdict": "supported|not_found|conflict_temporal|'
              f'conflict_substantive|contradicted"}}]'}],
            model=model_verify())
        out = ["not_found"] * len(subs)
        for item in v if isinstance(v, list) else []:
            i = item.get("idx")
            if isinstance(i, int) and 0 <= i < len(subs):
                out[i] = item.get("verdict", "not_found")
        return out

    detail = []
    for p in pairs:
        # ① 原子拆分（打包句 → 多条子论断；单事实句原样返回）
        try:
            subs = chat_json_eval(
                [{"role": "user", "content":
                  f"把下面的论断拆成独立的原子事实子论断（每条只含一个可核查的"
                  f"事实；若本身只有一个事实则原样返回一条）。"
                  f'只输出 JSON 数组：["..."]\n\n论断：{p["claim"]}'}],
                model=model_verify())
            subs = [str(s)[:300] for s in subs if str(s).strip()][:6] \
                if isinstance(subs, list) and subs else [p["claim"]]
        except Exception:  # noqa: BLE001 — 拆分失败退化为整句单条
            subs = [p["claim"]]
        # ② 主引用页联合判定
        pages = _fetch(p["urls"])
        if not pages:
            detail.append({"claim": p["claim"][:100], "urls": p["urls"],
                           "verdict": "unreachable", "subs": len(subs)})
            continue
        sub_v = _judge(subs, pages)
        # ③ 邻近池诊断：not_found 的子论断借同段/邻段 URL 再判一次
        by_neighbor = [False] * len(subs)
        if any(v == "not_found" for v in sub_v):
            seen = set(p["urls"])
            neigh = []
            for j in (p["pi"], p["pi"] - 1, p["pi"] + 1):
                if 0 <= j < len(para_urls):
                    for u in para_urls[j]:
                        if u not in seen:
                            seen.add(u)
                            neigh.append(u)
            n_pages = _fetch(neigh, limit=2)
            if n_pages:
                retry_idx = [i for i, v in enumerate(sub_v) if v == "not_found"]
                retry_v = _judge([subs[i] for i in retry_idx], n_pages)
                for i, v in zip(retry_idx, retry_v):
                    if v == "supported":
                        sub_v[i] = "supported"
                        by_neighbor[i] = True
        # ④ 对级聚合（矛盾按严重度取档:实质矛盾 > 未归类矛盾 > 时效矛盾）
        _CONFLICTS = ("conflict_substantive", "contradicted", "conflict_temporal")
        hit_conf = [k for k in _CONFLICTS if k in sub_v]
        if hit_conf:
            verdict = hit_conf[0]
        elif all(v == "supported" for v in sub_v):
            verdict = "supported_by_neighbor" if any(by_neighbor) else "supported"
        elif any(v == "supported" for v in sub_v):
            verdict = "partial"
        else:
            verdict = "not_found"
        detail.append({"claim": p["claim"][:100], "urls": p["urls"],
                       "verdict": verdict, "subs": len(subs),
                       "subs_supported": sum(1 for v in sub_v if v == "supported"),
                       "subs_by_neighbor": sum(by_neighbor),
                       # 子论断级审计：对级 worst-of 聚合会掩盖"6 子仅 1 冲突"
                       # 的构成,落全文+逐条 verdict 才能把矛盾定位到具体子句
                       "sub_detail": [{"text": s[:200], "verdict": v}
                                      for s, v in zip(subs, sub_v)]})
    layers = ("supported", "supported_by_neighbor", "partial", "not_found",
              "contradicted", "conflict_temporal", "conflict_substantive",
              "unreachable")
    pair_counts = {k: sum(1 for d in detail if d["verdict"] == k)
                   for k in layers}
    # 向后兼容:contradicted 汇总键包含全部矛盾档(旧消费方只读该键)
    pair_counts["contradicted"] += (pair_counts["conflict_temporal"]
                                    + pair_counts["conflict_substantive"])
    stats = {"total_pairs": len(pairs),
             "pairs": pair_counts,
             "subclaims": {
                 "total": sum(d["subs"] for d in detail),
                 "supported": sum(d.get("subs_supported", 0) for d in detail),
                 "by_neighbor": sum(d.get("subs_by_neighbor", 0) for d in detail),
                 # 子论断级矛盾数——对级 worst-of 会高估矛盾(1 子冲突整对记矛盾),
                 # 报矛盾必须用这个口径
                 "conflicted": sum(
                     1 for d in detail for sd in d.get("sub_detail", [])
                     if sd["verdict"] in ("contradicted", "conflict_temporal",
                                          "conflict_substantive"))},
             "detail": detail}
    return stats


# F9 系句级标记（含 agent 自创的字母后缀 ID,与 arm_f9_evidence._CIT_RE 同式）
_EVID_MARK_RE = re.compile(
    r"\[\s*(?:综合[:：]?\s*)?(E\d+[a-z]?(?:\s*[,，]\s*E\d+[a-z]?)*)\s*\]")


def check_claims_vs_evidence(raw_body: str, evidence: dict,
                             batch: int = 8) -> dict:
    """句级本地核验（F9 系专用，零抓页）：report_raw.md 中带 [En] 标记的
    句子，逐句对照 evidence.jsonl 登记的 quote 判定支撑性。

    相比 fact-v2 的优势：①句级粒度与 F9 的引用粒度对齐（段级解析会稀释）；
    ②不抓网页——论断只需对 ≤200 字的登记 quote 判定，快且判定面干净。
    quote 本身是否真在页面上由 arm 的 quote_check（子串匹配）另行审计，
    两者合起来构成完整证据链：论断→quote（本函数）→页面（子串审计）。
    verdict: supported / not_found / contradicted / no_evidence（标记的 ID
    未登记）。每 batch 句合一次快模型调用。
    """
    sents = [s.strip() for s in re.split(r"(?<=[。！？；])\s*|\n+", raw_body)
             if s.strip()]
    items = []  # (claim, quotes, ids)
    for s in sents:
        marks = _EVID_MARK_RE.findall(s)
        if not marks:
            continue
        ids = [i.strip() for m in marks for i in re.split(r"[,，]", m)]
        claim = re.sub(r"\s+", " ", _EVID_MARK_RE.sub("", s)).strip()
        if len(claim) < 15:
            continue
        # 优先用对齐回填的页面原文(quote_aligned),其次 agent 登记的原始摘录
        quotes = [str(evidence[i].get("quote_aligned") or evidence[i].get("quote", ""))
                  for i in ids
                  if i in evidence and (evidence[i].get("quote_aligned")
                                        or evidence[i].get("quote"))]
        items.append({"claim": claim[:300], "ids": ids, "quotes": quotes})
    detail = []
    todo = [it for it in items if it["quotes"]]
    for it in items:
        if not it["quotes"]:
            detail.append({"claim": it["claim"][:100], "ids": it["ids"],
                           "verdict": "no_evidence"})
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        listing = "\n\n".join(
            f"{j}. 论断：{c['claim']}\n   证据摘录：{' ｜ '.join(c['quotes'])[:600]}"
            for j, c in enumerate(chunk))
        try:
            v = chat_json_eval(
                [{"role": "user", "content":
                  f"下面是 {len(chunk)} 组「论断-证据摘录」。逐组判断：证据摘录"
                  f"（可能多条，联合看）是否支撑该论断（部分支撑也算 supported；"
                  f"论断强度明显超过摘录内容算 not_found；与摘录相悖算 "
                  f"contradicted）。\n\n{listing}\n\n"
                  f'只输出 JSON 数组（与组数等长）：'
                  f'[{{"idx": 0, "verdict": "supported|not_found|contradicted"}}]'}],
                model=model_verify())
        except Exception:  # noqa: BLE001 — 单批失败按 not_found 保守计
            v = []
        verdicts = ["not_found"] * len(chunk)
        for item in v if isinstance(v, list) else []:
            j = item.get("idx")
            if isinstance(j, int) and 0 <= j < len(chunk):
                verdicts[j] = item.get("verdict", "not_found")
        for c, vd in zip(chunk, verdicts):
            detail.append({"claim": c["claim"][:100], "ids": c["ids"],
                           "verdict": vd})
    stats = {"total_claims": len(items),
             "claims": {k: sum(1 for d in detail if d["verdict"] == k)
                        for k in ("supported", "not_found",
                                  "contradicted", "no_evidence")},
             "detail": detail}
    return stats


def risk_score(stats: dict) -> tuple[float, list[str]]:
    """机械统计 → 裁判失分风险预估（0-1）。用于决定是否触发深检/修订。"""
    risk, reasons = 0.0, []
    if stats.get("citation_coverage", 1) < 0.7:
        risk += 0.4; reasons.append(f"引用覆盖率低({stats['citation_coverage']})")
    if stats.get("ref_unique_ratio", 1) < 0.5:
        risk += 0.2; reasons.append("引用重复率高")
    doms = stats.get("section_domains", {})
    thin = [k for k, v in doms.items() if v <= 1]
    if doms and len(thin) / len(doms) > 0.4:
        risk += 0.3; reasons.append(f"多节信源单一({thin[:3]})")
    if stats.get("chars", 99999) < 6000:
        risk += 0.2; reasons.append("报告偏短")
    return min(risk, 1.0), reasons


def verify(report_path: str, question: str, deep: bool = False,
           rubric: dict | None = None, extended: bool = False,
           check_actions: bool = False, task_type: str | None = None) -> dict:
    body = Path(report_path).read_text()
    failures = []
    failures += check_truncation(body)
    dup_fails, uniq_ratio = check_ref_dup(body)
    failures += dup_fails
    cov_fails, cov_ratio = check_citation_coverage(body)
    failures += cov_fails
    div_fails, sec_domains = check_source_diversity(body)
    failures += div_fails
    req_fails, req_errors = check_requirements(question, body, rubric=rubric,
                                               check_actions=check_actions)
    failures += req_fails
    failures += check_type_requirements(body, task_type)
    stats = {"ref_unique_ratio": uniq_ratio,
             "citation_coverage": cov_ratio,
             "section_domains": sec_domains,
             "chars": len(body)}
    if extended:   # v5 起的扩展检查(信源分级/深度要素/冗长),不影响冻结的 F1-F4
        sq_fails, sq_stats = check_source_quality(body)
        failures += sq_fails
        dm_fails, dm_stats = check_depth_markers(body)
        failures += dm_fails
        failures += check_verbosity(body)
        stats["source_quality"] = sq_stats
        stats["depth_missing"] = {k: v for k, v in dm_stats.items() if v}
    if deep:
        cite_fails, cite_stats = check_citation_support(body)
        failures += cite_fails
        stats["citation_support"] = {k: v for k, v in cite_stats.items()
                                     if k != "detail"}
    stats["risk"], stats["risk_reasons"] = risk_score(stats)
    return {"pass": not failures, "failures": failures, "errors": req_errors,
            "stats": stats}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check"])
    ap.add_argument("report")
    ap.add_argument("--question", required=True)
    ap.add_argument("--rubric", help="预生成 rubric JSON 文件路径（与研究协议同源）")
    ap.add_argument("--deep", action="store_true", help="含引用支撑抽查（较慢）")
    ap.add_argument("--extended", action="store_true",
                    help="含信源分级/深度要素/冗长检查（v5+）")
    ap.add_argument("--actions", action="store_true",
                    help="含任务动作完成度判定（v6+）")
    ap.add_argument("--task-type", default=None,
                    help="任务类型专属验收 enumerative|comparative|evaluative（v7+）")
    args = ap.parse_args()
    q = args.question
    if Path(q).exists():
        q = Path(q).read_text()
    rb = json.loads(Path(args.rubric).read_text()) if args.rubric else None
    print(json.dumps(verify(args.report, q, deep=args.deep, rubric=rb,
                            extended=args.extended, check_actions=args.actions,
                            task_type=args.task_type),
                     ensure_ascii=False, indent=1))
