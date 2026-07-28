"""Arm F11:采集侧预引用(pre-cited collection,路径 C 的 training-free 近似)。

依据(research-dr-mainstream-20260720.md P0 第二条):
- Perplexity 拆解:引用在生成前由检索层预绑定 provenance,模型只写标号;
- GPT-Researcher +89% 验证引用归因于"pre-cited synthesis 而非搜索摘要";
- Cohere/Gemini 平台层引用 = 结构化 span,模型不在散文里自由发挥 URL。
verify 侧关账结论(07-21):精度上限由 draft 引用质量决定 → 本 arm 直接改
draft 侧引用的产生方式。

机制:LAB_PRECITE=1 时 search_cli read 给每个成功读到的页面机械分配稳定
编号 [Sn](页眉注入+precite_map.json 落盘)。写作协议从"标注来源 URL"
(B)降为"写作时句末标 [Sn]"——模型的引用职责收缩为"写个标号",URL 的
正确性由 harness 保证(模型永远不可能写错 URL,只可能标错页)。
成文后程序渲染:[Sn]→[n] + 机械生成参考来源节(fact-v2 可解析)。
对照:F11 vs B = 引用表达形式单变量(自由 URL vs 预编号标号)。
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import MODEL_MAIN, TraceLogger, now_str  # noqa: E402
from arms.arm_b_claude_code import PROMPT_CLOSED  # noqa: E402
from arms.arm_f10_postcite import SEARCH_CLI, _claude  # noqa: E402

PROMPT_DRAFT = """今天是 {date}。你是一名研究员，请完成下面的深度研究任务，产出一份带来源引用的中文研究报告。

【研究任务】
{question}

【可用工具】只能用这两个命令联网（内置的网页搜索不可用）：
- python3 {cli} search "中文查询词" —— 搜索，返回 JSON 结果
- python3 {cli} read "URL" —— 读取网页正文。每个成功读取的页面开头会给出
  该页的来源编号,如【本页来源编号 [S3]】。

【要求】
1. 多角度充分检索、精读后再写作;
2. 【引用方式】写作时,来自某个页面的事实论断在句末标注该页的来源编号,
   如「……出货量达 5 GWh[S3]。」一句可标多个编号[S2][S5]。**不要在正文写
   任何 URL,也不要自己编来源编号——只用 read 页面给出的编号**;
   没读过的页面的内容不得写入报告。
3. 报告不需要"参考来源"一节——系统会根据编号自动生成;
4. 报告用 Markdown,含分节结构和明确结论;
5. 把最终报告完整写入文件 {out}（只写报告本身）。"""

_SID_RE = re.compile(r"\[(S\d+)\]")


def _render(report: str, mp: dict, logger: TraceLogger) -> str:
    """[Sn] → [n](按首现顺序重编号)+ 机械生成参考来源节。
    未知编号(模型自编)原样保留并计数——这是协议违规信号,进 trace。"""
    order: dict[str, int] = {}
    unknown = set()

    def repl(m):
        sid = m.group(1)
        if sid not in mp:
            unknown.add(sid)
            return m.group(0)
        if sid not in order:
            order[sid] = len(order) + 1
        return f"[{order[sid]}]"

    body = _SID_RE.sub(repl, report)
    refs = "\n".join(f"[{n}] {mp[sid]}" for sid, n in
                     sorted(order.items(), key=lambda kv: kv[1]))
    logger.log("precite-render", cited=len(order), unknown=sorted(unknown),
               total_sources=len(mp))
    if refs:
        body += "\n\n## 参考来源\n\n" + refs + "\n"
    return body


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    out_file = workdir / "report.md"
    timeout = int(os.environ.get("LAB_AGENT_TIMEOUT", "1800"))

    if os.environ.get("LAB_CLOSED_BOOK"):
        prompt = PROMPT_CLOSED.format(date=now_str(), question=question,
                                      out=out_file)
        _claude(prompt, workdir, logger, "draft", "Write,Read", timeout, 60)
        report = out_file.read_text() if out_file.exists() else ""
        if len(report) < 1000:
            raise RuntimeError(f"closed-book report too short ({len(report)})")
        return report

    prompt = PROMPT_DRAFT.format(date=now_str(), question=question,
                                 cli=SEARCH_CLI, out=out_file)
    _claude(prompt, workdir, logger, "draft",
            f"Bash(python3 {SEARCH_CLI} *),Write,Read", timeout, 60,
            extra_env={"LAB_PRECITE": "1"})
    report = out_file.read_text() if out_file.exists() else ""
    if len(report) < 1000:
        raise RuntimeError(f"report too short ({len(report)} chars)")

    mp_f = workdir / "precite_map.json"
    mp = json.loads(mp_f.read_text()) if mp_f.exists() else {}
    final = _render(report, mp, logger)
    out_file.write_text(final)
    return final


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF11_"))
    logger = TraceLogger("/tmp/armF11_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
