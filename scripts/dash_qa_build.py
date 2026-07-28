#!/usr/bin/env python3
"""聚合 results/mimo_smoke 全部产物为逐题 QA 详情,供 dashboard.html 点击查看。

用法: python3 scripts/dash_qa_build.py
默认假定你已经用 eval/run.py 跑出了自己的 results/mimo_smoke/ 产物,脚本会
把 report/judge/fact 汇总进仓库根目录的 qa_data.json。gateway 字段只落一个
脱敏后的通用标签,不会把你本地的网关地址写进产物里。
"""
import json
import os
import re
from pathlib import Path

LAB = Path(os.environ.get("DR_LAB_ROOT", Path(__file__).resolve().parent.parent))
RESULTS_DIR = Path(os.environ.get("DR_RESULTS_DIR", LAB / "results/mimo_smoke"))
ARMS = ["B", "B3", "F91", "F10", "F101", "F102", "F103",
        "F11", "F111", "F112", "F113", "F114", "F115", "G"]

# 把 gateway URL 归一成一个不泄露具体基建信息的标签,而不是原样落盘。
_GATEWAY_LABELS = {"agent": "executor-gateway", "eval": "eval-gateway"}


def _gateway_label(meta: dict) -> str:
    gw = (meta.get("gateway") or "").lower()
    if not gw:
        return ""
    return _GATEWAY_LABELS["agent"]


def build() -> dict:
    if not RESULTS_DIR.exists():
        print(f"未找到 {RESULTS_DIR} —— 先跑 eval/run.py 产出结果,再执行本脚本。")
        return {}

    questions = json.loads((LAB / "eval/questions.json").read_text())
    ext = LAB / "eval/questions_ext.json"
    if ext.exists():
        questions += json.loads(ext.read_text())
    qmap = {q["id"]: q for q in questions}

    out = {}
    for arm in ARMS:
        dirs = sorted(d for d in RESULTS_DIR.iterdir()
                      if d.is_dir() and d.name.endswith(f"_{arm}")
                      and d.name.rsplit("_", 1)[-1] == arm)
        items = []
        for d in dirs:
            qid = d.name.rsplit("_", 1)[0]
            mf = d / "meta.json"
            if not mf.exists():
                continue
            meta = json.loads(mf.read_text())
            if meta.get("status") != "ok":
                continue
            rf = d / "report.md"
            report = rf.read_text() if rf.exists() else ""
            judge = None
            sf = d / "scores.json"
            if sf.exists():
                sj = json.loads(sf.read_text())
                judge = {"overall": sj.get("overall"), "rationale": sj.get("rationale"),
                          "samples": [s.get("overall") for s in sj.get("samples", [])]}
            fact = None
            ff = d / "fact2.json"
            if ff.exists():
                fj = json.loads(ff.read_text())
                fact = {"pairs": fj.get("pairs"), "total_pairs": fj.get("total_pairs"),
                         "subclaims": fj.get("subclaims")}
            q = qmap.get(qid, {})
            items.append({
                "qid": qid,
                "topic": q.get("topic", ""),
                "question": q.get("question", ""),
                "report": report,
                "judge": judge,
                "fact": fact,
                "seconds": meta.get("seconds"),
                "model_main": meta.get("model_main"),
                "gateway": _gateway_label(meta),
            })
        if items:
            out[arm] = items
    return out


if __name__ == "__main__":
    out = build()
    path = LAB / "qa_data.json"
    path.write_text(json.dumps(out, ensure_ascii=False))
    n_items = sum(len(v) for v in out.values())
    print(f"wrote {path} : {len(out)} arms, {n_items} qa records, {path.stat().st_size/1024:.0f} KB")
