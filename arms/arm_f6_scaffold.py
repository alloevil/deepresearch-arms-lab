"""Arm F6 (Hybrid-v6)：F5 + 三个正确性修复（验收完整性/门控防绕过/交卷诚实）。

相对 arm_f5_scaffold 的改动（用户 review 定位的确定性缺陷）：
1. actions 验收 + discovered 同步：check_actions=True——任务动作（对比/评估）
   由快模型逐条判定实质完成度；discovered 合并下沉到 check_requirements，
   agent 自检（CLI）与外部门禁标准完全一致
2. 风险门控防绕过：ev_used_ratio（报告引用 URL ∩ search_calls.jsonl 真实访问）
   纳入快检——引用与真实检索行为不符时强制走深检，堵住"编造引用走快速通道"
   的 fail-silent 回归漏洞
3. 交卷诚实：二轮修订后仍未通过 → 追加一轮纯文本修订（便宜）；最终仍不过则
   在 trace 打 shipped-with-failures 标记（含失败清单），不再静默交卷
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import MODEL_MAIN, TraceLogger, now_str  # noqa: E402
from common.verify_cli import extract_rubric, verify  # noqa: E402

LAB = Path(__file__).resolve().parent.parent
SEARCH_CLI = LAB / "common" / "search_cli.py"
VERIFY_CLI = LAB / "common" / "verify_cli.py"

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
5. 【深度要求——原子论断法】写作每个主体章节前，先在草稿中列出该节的
   「原子论断清单」：每条 = 一句可核查的论断 + 支撑它的证据来源 URL。然后按
   清单成文，并保证全节覆盖四要素：
   a) 具体数据点（数字、日期、金额）；b) 多方对比（不同主体/口径/立场并列）；
   c) 机制解释（为什么会这样，因果链条）；d) 批判性评估（数据可信度、反例、不确定性）。
   无证据支撑的论断不得写入。
6. 【内省自检】把报告写入 {out} 后，必须运行上面的质量自检命令，若返回
   failures 非空，按失败项修改报告（缺证据的先补搜）后重新自检，直到通过
   或已尽力（最多自检 3 次）。
7. 重要论断标注来源 URL；报告用 Markdown 分节，含"参考来源"一节。

最终报告写入 {out}（只写报告本身）。"""

REVISE_PROMPT = """你之前完成的研究报告 {out} 未通过质量验证，问题如下：

{failures}
{search_hints}
请修订：
1. 先读取 {out} 了解现有内容（如你已有上下文可跳过）；
2. 检索类问题用搜索工具补充证据（可换英文、换角度）：
   - python3 {cli} search "查询词"
   - python3 {cli} read "URL"
3. 文本类问题（截断/重复/覆盖率）直接改写对应章节；
4. 把修订后的完整报告写回 {out}。"""

RETRIEVAL_PAT = re.compile(r"未在报告中出现|实质分析了|单一域名|checklist|不支撑论断")


def _classify(failures: list[str]) -> tuple[list[str], list[str]]:
    retrieval = [f for f in failures if RETRIEVAL_PAT.search(f)]
    textual = [f for f in failures if f not in retrieval]
    return retrieval, textual


def _search_hints(retrieval_fails: list[str]) -> str:
    if not retrieval_fails:
        return ""
    hints = []
    for f in retrieval_fails:
        m = re.search(r"「(.+?)」", f)
        if m:
            ent = m.group(1)
            hints.append(f'- 针对「{ent}」可尝试：search "{ent} 2025 2026"、'
                         f'search "{ent}" 的英文译名')
    return ("\n【建议搜索词】\n" + "\n".join(hints) + "\n") if hints else ""


def _run_claude(prompt: str, workdir: Path, logger: TraceLogger, tag: str,
                resume: str | None = None) -> str | None:
    """跑一次 claude -p，返回 session_id（供后续 --resume）。"""
    cmd = ["claude", "-p", prompt, "--model", MODEL_MAIN,
           "--output-format", "json",
           "--allowedTools", (f"Bash(python3 {SEARCH_CLI} *),"
                              f"Bash(python3 {VERIFY_CLI} *),Write,Read,Edit"),
           "--disallowedTools", "WebSearch,WebFetch,Task",
           "--max-turns", "100"]
    if resume:
        cmd += ["--resume", resume]
    env = dict(os.environ)
    if os.environ.get("LAB_CLAUDE_BASE_URL"):
        env["ANTHROPIC_BASE_URL"] = os.environ["LAB_CLAUDE_BASE_URL"]
        sf = workdir / "claude_settings.json"
        sf.write_text(json.dumps({"env": {
            "ANTHROPIC_BASE_URL": os.environ["LAB_CLAUDE_BASE_URL"],
            "ANTHROPIC_AUTH_TOKEN": os.environ["ANTHROPIC_AUTH_TOKEN"],
        }}))
        cmd += ["--settings", str(sf)]
    logger.log(f"{tag}-start", resume=bool(resume))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800,
                          cwd=workdir, env=env)
    session_id = None
    try:
        d = json.loads(proc.stdout)
        if isinstance(d, list):    # --output-format json 输出事件数组,init 事件含 session_id
            for ev in d:
                if isinstance(ev, dict) and ev.get("session_id"):
                    session_id = ev["session_id"]
                    break
        elif isinstance(d, dict):
            session_id = d.get("session_id")
    except json.JSONDecodeError:
        pass
    logger.log(f"{tag}-end", returncode=proc.returncode, session=session_id,
               stderr_tail=proc.stderr[-300:])
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: "
                           f"{(proc.stderr or proc.stdout)[-300:]}")
    return session_id


def _merged_rubric(initial: dict, workdir: Path) -> dict:
    """初始 rubric ∪ agent 追加项（只增不减:agent 改/删初始项不生效）。"""
    merged = {k: list(initial.get(k) or []) for k in ("entities", "counts", "actions")}
    try:
        cur = json.loads((workdir / "rubric.json").read_text())
    except (OSError, json.JSONDecodeError):
        return merged
    for d in cur.get("discovered") or []:
        if isinstance(d, str) and d not in merged["entities"]:
            merged["entities"].append(d)
        elif isinstance(d, dict) and d.get("what"):
            merged["counts"].append(d)
    return merged


def _verify_plus(out_file: Path, question: str, workdir: Path,
                 deep: bool = False, rubric: dict | None = None) -> dict:
    result = verify(str(out_file), question, deep=deep, rubric=rubric,
                    extended=True, check_actions=True)
    if not (workdir / "checklist.md").exists():
        result["failures"].append(
            "研究协议要求的 checklist.md 未创建——请补建硬性要求清单并逐项核对报告")
        result["pass"] = False
    return result


def _rubric_text(rubric: dict) -> str:
    lines = []
    for e in rubric.get("entities", []):
        lines.append(f"- 必须覆盖点名实体：{e}")
    for c in rubric.get("counts", []):
        if c.get("what") and int(c.get("min") or 0) > 0:
            lines.append(f"- 「{c['what']}」至少 {c['min']} 个（实质分析，非仅提及）")
    for a in rubric.get("actions", []):
        lines.append(f"- 必须完成动作：{a}")
    return "\n".join(lines) or "-（无特殊硬性要求）"



def _ev_used_ratio(out_file: Path, workdir: Path) -> float | None:
    """报告引用 URL 中有多少来自真实检索行为（search_calls.jsonl 审计日志）。"""
    log = workdir / "search_calls.jsonl"
    if not log.exists():
        return None
    def norm(u):
        u = re.sub(r"^https?://(www\.)?", "", u)
        return u.split("#")[0].split("?")[0].rstrip("/")[:80]
    visited = set()
    for line in log.read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        for u in e.get("urls") or ([e["url"]] if e.get("url") else []):
            visited.add(norm(u))
    cited = {norm(u) for u in re.findall(r"https?://[^\s)）\]」>]+",
                                          out_file.read_text())}
    if not cited:
        return 0.0
    return round(sum(1 for u in cited if u in visited) / len(cited), 2)


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    # 统一 rubric：一次抽取,协议与验证共用
    rubric = extract_rubric(question)
    (workdir / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False))
    (workdir / "question.txt").write_text(question)
    logger.log("rubric", **{k: rubric.get(k) for k in ("entities", "counts", "actions")})

    session = _run_claude(PROMPT.format(date=now_str(), question=question,
                                        cli=SEARCH_CLI, vcli=VERIFY_CLI,
                                        out=out_file,
                                        rubric_text=_rubric_text(rubric)),
                          workdir, logger, "draft")
    if not out_file.exists() or len(out_file.read_text()) < 1000:
        raise RuntimeError("draft report missing or too short")

    # 风险门控：先跑廉价机械检查，低风险且零失败 → 直接交卷
    rubric_now = _merged_rubric(rubric, workdir)
    quick = _verify_plus(out_file, question, workdir, deep=False, rubric=rubric_now)
    risk = quick["stats"].get("risk", 1.0)
    # v6:引用真实性纳入快检——引用 URL 与真实检索行为不符则强制深检,
    # 防止"编造引用但格式漂亮"的报告走快速通道(fail-silent 回归漏洞)
    ev_ratio = _ev_used_ratio(out_file, workdir)
    if ev_ratio is not None and ev_ratio < 0.9:
        risk = max(risk, 0.9)
    logger.log("verify-quick", risk=risk, ev_used_ratio=ev_ratio,
               risk_reasons=quick["stats"].get("risk_reasons"),
               **{k: v for k, v in quick.items() if k != "stats"})
    if quick["pass"] and risk < 0.4:
        logger.log("risk-gate", action="ship-without-deep-check")
        return out_file.read_text()

    # 高风险或有失败 → 深检 + 最多三轮修订(第三轮仅文本类,便宜)，每轮修订后复检
    result = None
    for attempt in (1, 2, 3, 4):
        rubric_now = _merged_rubric(rubric, workdir)
        result = _verify_plus(out_file, question, workdir, deep=True, rubric=rubric_now)
        logger.log(f"verify-deep-{attempt}",
                   **{k: (v if k != "stats" else
                          {kk: vv for kk, vv in v.items() if kk != "section_domains"})
                      for k, v in result.items()})
        if result["pass"] or attempt == 4:
            break
        retrieval, textual = _classify(result["failures"])
        # 前两轮全量修订；第三轮检索类已尽力,只做便宜的纯文本修订
        failures_list = (textual if attempt == 3 else retrieval + textual)
        if not failures_list:
            break
        failures = "\n".join(f"- {f}" for f in failures_list)
        session = _run_claude(
            REVISE_PROMPT.format(out=out_file, failures=failures,
                                 search_hints=_search_hints(retrieval if attempt < 3 else []),
                                 cli=SEARCH_CLI),
            workdir, logger, f"revise-{attempt}", resume=session) or session

    if result and not result["pass"]:
        # v6:不再静默交卷——把未解决的失败显式落 trace,供评测端与复盘审计
        logger.log("shipped-with-failures", failures=result["failures"][:6])

    report = out_file.read_text()
    if len(report) < 1000:
        raise RuntimeError(f"final report too short ({len(report)} chars)")
    return report


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF6_"))
    logger = TraceLogger("/tmp/armF6_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商，并评估其中一家的降本路径。",
              logger, wd)[:1200])
