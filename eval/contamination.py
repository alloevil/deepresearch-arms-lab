"""污染审计(STC 三级分类的自建题库适配,见 EXPERIMENTS.md §污染审计)。

对单个 run 目录的 search_calls.jsonl 做两项离线审计:
- BML:检索结果 URL 命中 benchmark 托管站(运行时 core.BML_BLOCKLIST 已拦,这里统计残留)
- QCL(query_echo):检索 query 与题面归一化后的最长公共子串 / query 长度,取所有 query 的最大值。
  照抄题面搜索最易命中现成综述,echo>=0.8 视为照抄。

EAL(高重合页面 LLM 判"一站式直答页")需要抓页与 LLM,不在本模块内。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 审计纯离线,但 common.core 在导入时要求网关配置;给占位值,不触网。
os.environ.setdefault("ANTHROPIC_BASE_URL", "http://localhost:9")
os.environ.setdefault("ANTHROPIC_AUTH_TOKEN", "dummy")
from common.core import BML_BLOCKLIST  # noqa: E402

_NORM = re.compile(r"[\s\W_]+", re.UNICODE)
# 短于此的公共片段(单字/常用双字如"进展")不算照抄,否则任意题面都会有 1-2 字的偶然重合。
MIN_ECHO_SPAN = 4


def normalize(s: str) -> str:
    """去空白与标点、小写;中英混排题面按字符级比较。"""
    return _NORM.sub("", s or "").lower()


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度(O(len a * len b),query 与题面都很短)。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def query_echo(query: str, question: str) -> float:
    """query 中被题面覆盖的最长连续片段占 query 的比例,∈[0,1]。"""
    q = normalize(query)
    if not q:
        return 0.0
    span = _lcs_len(q, normalize(question))
    return span / len(q) if span >= MIN_ECHO_SPAN else 0.0


def iter_events(run_dir: Path):
    p = Path(run_dir) / "search_calls.jsonl"
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def audit_run(run_dir: Path, question: str) -> dict:
    """返回 {run, n_queries, bml_hits, bml_urls, query_echo, echo_queries}。"""
    n_queries = 0
    bml_urls: list[str] = []
    echoes: list[tuple[float, str]] = []
    for ev in iter_events(run_dir):
        if ev.get("kind") != "search":
            continue
        n_queries += 1
        echoes.append((query_echo(ev.get("query", ""), question), ev.get("query", "")))
        for url in ev.get("urls") or []:
            if BML_BLOCKLIST.search(url):
                bml_urls.append(url)
    max_echo = max((e for e, _ in echoes), default=0.0)
    return {
        "run": Path(run_dir).name,
        "n_queries": n_queries,
        "bml_hits": len(bml_urls),
        "bml_urls": bml_urls,
        "query_echo": round(max_echo, 3),
        "echo_queries": [q for e, q in echoes if e >= 0.8],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="BML / QCL contamination audit over run dirs")
    ap.add_argument("runs", nargs="+", help="run directories containing search_calls.jsonl")
    ap.add_argument("--questions", default=str(Path(__file__).with_name("questions.json")),
                    help="questions.json; run dir name prefix qNN selects the question")
    ap.add_argument("--json", action="store_true", help="emit JSON lines instead of a table")
    a = ap.parse_args(argv)

    qs = json.loads(Path(a.questions).read_text(encoding="utf-8"))
    by_id = {q["id"]: q["question"] for q in qs} if isinstance(qs, list) else qs

    rows = []
    for r in a.runs:
        rd = Path(r)
        qid = rd.name.split("_", 1)[0]
        rows.append(audit_run(rd, by_id.get(qid, "")))
    if a.json:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
    else:
        print(f"{'run':28s} {'queries':>7s} {'bml':>4s} {'echo':>5s}")
        for row in rows:
            print(f"{row['run']:28s} {row['n_queries']:7d} {row['bml_hits']:4d} {row['query_echo']:5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
