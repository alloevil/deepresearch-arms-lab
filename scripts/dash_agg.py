#!/usr/bin/env python3
"""聚合 results/mimo_smoke 全部 arm 的 judge/fact 数据,输出汇总 JSON。

用法: python3 scripts/dash_agg.py
用于重新核算 dashboard.html 顶部统计牌和图表里的数字——如果你重跑了自己的
实验,先跑这个脚本看聚合结果,再手动把 dashboard.html 里的 DATA 对象更新。
"""
import json
import os
import statistics
from pathlib import Path

LAB = Path(os.environ.get("DR_LAB_ROOT", Path(__file__).resolve().parent.parent))
RESULTS_DIR = Path(os.environ.get("DR_RESULTS_DIR", LAB / "results/mimo_smoke"))
ARMS = ["B", "B3", "F91", "F10", "F101", "F102", "F103",
        "F11", "F111", "F112", "F113", "F114", "F115", "G"]


def build() -> dict:
    out = {}
    for arm in ARMS:
        dirs = sorted(d for d in RESULTS_DIR.iterdir()
                      if d.is_dir() and d.name.endswith(f"_{arm}")
                      and d.name.split("_", 1)[1] == arm)
        js = []
        sc_t = sc_s = 0
        pair_t = pair_s = unre = nf = 0
        conflicts = mis = 0
        secs = []
        for d in dirs:
            sf = d / "scores.json"
            if sf.exists():
                js.append(json.loads(sf.read_text())["overall"])
            mf = d / "meta.json"
            if mf.exists():
                m = json.loads(mf.read_text())
                if m.get("status") == "ok":
                    secs.append(m.get("seconds", 0))
            ff = d / "fact2.json"
            if ff.exists():
                st = json.loads(ff.read_text())
                if "pairs" in st:
                    p = st["pairs"]
                    pair_t += st["total_pairs"]
                    pair_s += p["supported"]
                    unre += p["unreachable"]
                    nf += p["not_found"]
                    mis += p.get("supported_by_neighbor", 0)
                    conflicts += (p["contradicted"] + p.get("conflict_temporal", 0)
                                  + p.get("conflict_substantive", 0))
                sc = st.get("subclaims") or {}
                sc_t += sc.get("total", 0)
                sc_s += sc.get("supported", 0)
        reach = pair_t - unre
        out[arm] = {
            "n_runs": len(dirs),
            "judge": round(statistics.mean(js), 2) if js else None,
            "judge_n": len(js),
            "sub": round(sc_s / sc_t, 2) if sc_t else None,
            "sub_n": sc_t,
            "pair_strict": round(pair_s / reach, 2) if reach else None,
            "pairs": pair_t,
            "overclaim": nf,
            "conflict": conflicts,
            "misattr": mis,
            "avg_secs": round(statistics.mean(secs)) if secs else None,
        }
    return out


if __name__ == "__main__":
    out = build()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (LAB / "dash_data.json").write_text(json.dumps(out, ensure_ascii=False))
