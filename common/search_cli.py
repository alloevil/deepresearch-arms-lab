#!/usr/bin/env python3
"""搜索 CLI：给 Claude Code arm 用的搜索工具，与其他 arm 共用同一后端（公平性控制）。

用法:
  search_cli.py search "查询词"     → JSON 结果列表
  search_cli.py read "URL"          → 网页正文
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import read_page, search  # noqa: E402


def _log(kind: str, **kw):
    """落盘到调用方 cwd（即 run 目录），供过程指标审计 agent 的真实检索行为。"""
    try:
        with open("search_calls.jsonl", "a") as f:
            f.write(json.dumps({"t": round(time.time()), "kind": kind, **kw},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass

if __name__ == "__main__":
    cmd, arg = sys.argv[1], sys.argv[2]
    # 闭卷评测模式：不是基础设施故障，须明确告知 agent 用自身知识作答
    # （否则 agent 会按"搜索故障勿编造"的提示拒写，测不出参数化知识水位）
    if os.environ.get("LAB_CLOSED_BOOK"):
        _log(cmd, closed_book=True, **({"query": arg} if cmd == "search"
                                       else {"url": arg}))
        print(json.dumps({"closed_book": True,
                          "note": "闭卷评测模式：检索/阅读不可用。请基于你自身的知识"
                                  "完成报告，不要编造具体的引用 URL。"},
                         ensure_ascii=False))
        sys.exit(0)
    if cmd == "search":
        try:
            results = search(arg, n=8)
        except Exception as e:  # noqa: BLE001 — 让 agent 看到基础设施故障而不是空结果
            print(json.dumps({"error": f"search backend failure: {e}"},
                             ensure_ascii=False))
            sys.exit(1)
        if not results:
            print(json.dumps({"error": "no results from any search backend",
                              "hint": "do NOT fabricate content; report the failure"},
                             ensure_ascii=False))
            sys.exit(1)
        print(json.dumps(results, ensure_ascii=False, indent=1))
        _log("search", query=arg, n=len(results), urls=[r["url"] for r in results])
    elif cmd == "read":
        # LAB_READ_MAX:单页曝光上限(默认 8000)。依据 arXiv 2607.12257:引用
        # 忠实性由"模型看到多少原文"决定——核修阶段可调大(F10.3 消融变量)
        body = read_page(arg, max_chars=int(os.environ.get("LAB_READ_MAX", "8000")))
        from common import core
        _log("read", url=arg, chars=len(body or ""), via=core.LAST_READ_VIA)
        # LAB_PRECITE:采集侧预引用(F11)。read 成功即机械分配稳定编号并注入
        # 页眉,写作模型引用=写 [Sn] 标号;编号→URL 映射落 precite_map.json,
        # 渲染由 arm 侧程序完成——引用绑定职责从模型转移到 harness
        if os.environ.get("LAB_PRECITE") and body:
            mp_f = "precite_map.json"
            try:
                mp = json.load(open(mp_f))
            except (OSError, json.JSONDecodeError):
                mp = {}
            sid = next((k for k, v in mp.items() if v == arg), None)
            if sid is None:
                sid = f"S{len(mp) + 1}"
                mp[sid] = arg
                with open(mp_f, "w") as f:
                    json.dump(mp, f, ensure_ascii=False, indent=1)
            print(f"【本页来源编号 [{sid}]——报告中引用本页内容时句末标 [{sid}]】")
        print(body or "(抓取失败或空页面)")
