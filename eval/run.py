#!/usr/bin/env python3
"""评测总控：跑 指定arm × 指定题目，产物落盘 results/。

用法:
  python3 eval/run.py --arms A,C --questions q01,q02 --tag round1
  python3 eval/run.py --judge results/round1        # 对已有报告盲评打分
  python3 eval/run.py --summary results/round1      # 汇总表
"""
import argparse
import importlib
import json
import os
import random
import sys
import time
import traceback
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB))
from common.core import GATEWAY, MODEL_FAST, MODEL_MAIN, TraceLogger  # noqa: E402

# agent 系走 claude/opencode/codex 子进程，执行器网关看 LAB_CLAUDE_BASE_URL（arm 会
# 用它覆盖子进程的 ANTHROPIC_BASE_URL）；workflow 系走 core.chat 用 GATEWAY。
_AGENT_ARMS = {"B", "B2", "B3", "D", "E", "F", "F2", "F3", "F4",
               "F5", "F6", "F7", "F8", "F9", "F91", "F10", "F101", "F102", "F103", "F11", "F111", "F112", "F113", "F114", "F115", "G"}


def _provenance(arm: str) -> dict:
    """执行器 model + 网关落盘（补 meta.json.model=None 的黑洞）。agent 系的
    LLM 调用在子进程内、不进 trace，此前无法从产物自证跑的什么模型/网关。"""
    agent_gw = os.environ.get("LAB_CLAUDE_BASE_URL") or GATEWAY
    return {"model_main": MODEL_MAIN, "model_fast": MODEL_FAST,
            "gateway": (agent_gw if arm in _AGENT_ARMS else GATEWAY)}

ARM_MODULES = {"A": "arms.arm_a_fixed", "B": "arms.arm_b_claude_code",
               "B2": "arms.arm_b2_delegate", "B3": "arms.arm_b3_protocol",
               "C": "arms.arm_c_ours", "C2": "arms.arm_c2_ours",
               "C3": "arms.arm_c3_ours", "C4": "arms.arm_c4_ours",
               "D": "arms.arm_d_opencode", "E": "arms.arm_e_codex",
               "F": "arms.arm_f_scaffold", "F2": "arms.arm_f2_scaffold",
               "F3": "arms.arm_f3_scaffold", "F4": "arms.arm_f4_scaffold",
               "F5": "arms.arm_f5_scaffold", "F6": "arms.arm_f6_scaffold", "F7": "arms.arm_f7_scaffold",
               "F8": "arms.arm_f8_scaffold", "F9": "arms.arm_f9_evidence",
               "F91": "arms.arm_f91_evidence", "F10": "arms.arm_f10_postcite", "F101": "arms.arm_f101_postcite", "F102": "arms.arm_f102_postverify", "F103": "arms.arm_f103_exposure", "F11": "arms.arm_f11_precite", "F111": "arms.arm_f111_precite", "F112": "arms.arm_f112_dualchannel", "F113": "arms.arm_f113_atomic", "F114": "arms.arm_f114_precite", "F115": "arms.arm_f115_full", "G": "arms.arm_g_gptr"}


def _prev_status(dest: Path) -> str | None:
    """读取上次运行状态；meta 缺失/损坏视为未完成。"""
    try:
        return json.loads((dest / "meta.json").read_text()).get("status")
    except (OSError, json.JSONDecodeError):
        return None


def _load_questions() -> dict:
    """题面加载：主题库 questions.json + 可选扩展 questions_ext.json（DRB 借用的
    英文/垂直域题,id 前缀 e）。合并后所有下游(跑批/裁判/fact/污染)自动支持扩展题。"""
    qs = json.loads((LAB / "eval/questions.json").read_text())
    ext = LAB / "eval/questions_ext.json"
    if ext.exists():
        qs = qs + json.loads(ext.read_text())
    return {q["id"]: q for q in qs}


def run_arms(arms, qids, tag, closed_book=False):
    questions = _load_questions()
    if closed_book:
        # 闭卷基线：禁检索/阅读跑同题，Δ(开卷−闭卷)=检索净增益。
        # 产物落独立 tag，避免与开卷结果混在同目录被 --judge/--compare 误配对
        os.environ["LAB_CLOSED_BOOK"] = "1"
        tag = tag + "_closedbook"
    outdir = LAB / "results" / tag
    outdir.mkdir(parents=True, exist_ok=True)
    for qid in qids:
        q = questions[qid]
        for arm in arms:
            dest = outdir / f"{qid}_{arm}"
            report_file = dest / "report.md"
            # 续跑判据看 meta.status 而非 report.md 是否存在——arm（尤其 F 系,
            # agent 直接写 report.md）可能落了报告但后续步骤失败
            if report_file.exists() and _prev_status(dest) == "ok":
                print(f"skip {qid}/{arm} (done)")
                continue
            if report_file.exists():
                print(f"retry {qid}/{arm} (previous status={_prev_status(dest)})")
                report_file.unlink()  # 陈旧报告会被 arm 误判为本次产出
            dest.mkdir(parents=True, exist_ok=True)
            logger = TraceLogger(dest / "trace.jsonl")
            t0 = time.time()
            started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
            try:
                mod = importlib.import_module(ARM_MODULES[arm])
                if arm in _AGENT_ARMS:
                    report = mod.run(q["question"], logger, dest)
                else:
                    report = mod.run(q["question"], logger)
                report_file.write_text(report)
                meta = {"qid": qid, "arm": arm, "seconds": round(time.time() - t0),
                        "started_at": started_at, "closed_book": closed_book,
                        **_provenance(arm),
                        "tokens": logger.tokens, "status": "ok"}
            except Exception as e:  # noqa: BLE001 — 单个组合失败不中断整轮
                meta = {"qid": qid, "arm": arm, "seconds": round(time.time() - t0),
                        "started_at": started_at, "closed_book": closed_book,
                        **_provenance(arm),
                        "status": "error", "error": f"{e}\n{traceback.format_exc()[-800:]}"}
            (dest / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
            print(f"done {qid}/{arm}: {meta['status']} {meta['seconds']}s")


def judge_all(result_dir, n_samples=3, judges=""):
    from eval.judge import judge_report
    judge_models = [m.strip() for m in judges.split(",") if m.strip()] or None
    questions = _load_questions()
    dirs = sorted(p for p in Path(result_dir).iterdir()
                  if (p / "report.md").exists() and _prev_status(p) == "ok")
    random.shuffle(dirs)  # 盲评：打乱顺序，judge_report 本身不接收 arm 标识
    for d in dirs:
        score_file = d / "scores.json"
        if score_file.exists():
            continue
        qid = d.name.split("_")[0]
        report = (d / "report.md").read_text()
        try:
            scores = judge_report(questions[qid]["question"], report,
                                  n_samples=n_samples, judge_models=judge_models)
            score_file.write_text(json.dumps(scores, ensure_ascii=False, indent=1))
            print(f"judged {d.name}: overall={scores['overall']}")
        except Exception as e:  # noqa: BLE001
            print(f"judge FAILED {d.name}: {e}")


def pairwise_all(result_dir, arm_x, arm_y):
    """同题两 arm 的报告并排 pairwise 裁判（换位×2），产物落 pairwise_X_vs_Y/。"""
    from eval.judge import judge_pair
    questions = _load_questions()
    base = Path(result_dir)
    outdir = base / f"pairwise_{arm_x}_vs_{arm_y}"
    outdir.mkdir(exist_ok=True)
    qids = sorted(d.name.split("_")[0] for d in base.iterdir()
                  if d.name.endswith(f"_{arm_x}") and _prev_status(d) == "ok")
    for qid in qids:
        out_f = outdir / f"{qid}.json"
        if out_f.exists():
            print(f"skip {qid} (exists)")
            continue
        dx, dy = base / f"{qid}_{arm_x}", base / f"{qid}_{arm_y}"
        if not ((dx / "report.md").exists() and (dy / "report.md").exists()
                and _prev_status(dy) == "ok"):
            print(f"skip {qid} (missing counterpart)")
            continue
        try:
            r = judge_pair(questions[qid]["question"],
                           (dx / "report.md").read_text(),
                           (dy / "report.md").read_text())
            out_f.write_text(json.dumps(r, ensure_ascii=False, indent=1))
            print(f"paired {qid}: {arm_x}={r['x']['overall']} {arm_y}={r['y']['overall']} "
                  f"Δ={r['delta_overall']:+}")
        except Exception as e:  # noqa: BLE001
            print(f"pairwise FAILED {qid}: {e}")


def _bootstrap_ci(diffs, n_boot=10000, seed=42):
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(diffs, k=len(diffs))) / len(diffs)
                   for _ in range(n_boot))
    return means[int(n_boot * 0.025)], means[int(n_boot * 0.975)]


def _run_dirs(base: Path, arm: str):
    """某 arm 的所有 run 目录（题 id 前缀不限 q/e——扩展题库用 e）。
    排除 pairwise_ 汇总目录（名字含 _vs_）。"""
    return [d for d in base.iterdir()
            if d.is_dir() and d.name.endswith(f"_{arm}")
            and "_vs_" not in d.name]


def _exec_dates(base: Path, arm: str) -> set[str]:
    dates = set()
    for d in _run_dirs(base, arm):
        try:
            m = json.loads((d / "meta.json").read_text())
            dates.add((m.get("started_at") or "unknown")[:10])
        except (OSError, json.JSONDecodeError):
            dates.add("unknown")
    return dates


def _exec_models(base: Path, arm: str) -> set[str]:
    """某 arm 各 run 的 执行器model@网关（provenance 落盘后可核对；旧批为 unknown）。"""
    seen = set()
    for d in _run_dirs(base, arm):
        try:
            m = json.loads((d / "meta.json").read_text())
            mm, gw = m.get("model_main"), m.get("gateway")
            seen.add(f"{mm}@{gw}" if mm else "unknown")
        except (OSError, json.JSONDecodeError):
            seen.add("unknown")
    return seen


def compare(result_dir, arm_x, arm_y):
    """配对比较：逐题差、bootstrap 95% CI、胜平负。absolute 分数与 pairwise 产物都汇总。"""
    base = Path(result_dir)
    dx, dy = _exec_dates(base, arm_x), _exec_dates(base, arm_y)
    if dx != dy:
        print(f"⚠ 批次警告：{arm_x} 执行于 {sorted(dx)}，{arm_y} 执行于 {sorted(dy)}。"
              f"\n  同系统重跑的批间方差实测 ~0.25（见 EXPERIMENTS.md），"
              f"跨执行批次的分差可能主要是批次效应而非机制差异。")
    elif "unknown" in dx:
        print(f"ℹ {arm_x}/{arm_y} 的执行日期未记录（旧版 meta），无法核对是否同批执行。")

    mx, my = _exec_models(base, arm_x), _exec_models(base, arm_y)
    if mx == {"unknown"} or my == {"unknown"}:
        print(f"ℹ {arm_x}/{arm_y} 的执行器 model/网关未记录（旧版 meta，provenance 落盘前）——"
              f"无法核对是否同模型。")
    elif mx != my:
        print(f"⚠ 模型警告：{arm_x} 执行器 {sorted(mx)}，{arm_y} 执行器 {sorted(my)}。"
              f"\n  跨模型/跨网关的分差不可归因于机制——换执行器会改变全部结论"
              f"（如 sonnet 上的 B3/F9.1 结论不迁移到 MiMo）。")

    def paired_scores(source_fn, label):
        rows = []  # (qid, x_overall, y_overall)
        for qid, sx, sy in source_fn():
            rows.append((qid, sx, sy))
        if not rows:
            return
        diffs = [round(sx - sy, 4) for _, sx, sy in rows]
        mean = sum(diffs) / len(diffs)
        lo, hi = _bootstrap_ci(diffs)
        win = sum(1 for d in diffs if d > 0.001)
        loss = sum(1 for d in diffs if d < -0.001)
        tie = len(diffs) - win - loss
        print(f"\n[{label}] {arm_x} vs {arm_y}  (n={len(rows)})")
        for (qid, sx, sy), d in zip(rows, diffs):
            print(f"  {qid}: {sx:.2f} vs {sy:.2f}  Δ={d:+.2f}")
        sig = "显著" if (lo > 0 or hi < 0) else "不显著（CI 跨 0）"
        print(f"  均差 {mean:+.3f}  bootstrap95%CI [{lo:+.3f}, {hi:+.3f}] → {sig}")
        print(f"  胜/平/负 = {win}/{tie}/{loss}")

    def from_absolute():
        for dx in sorted(_run_dirs(base, arm_x)):
            qid = dx.name[:-(len(arm_x) + 1)]  # 去掉 "_{arm}" 后缀,保留完整 qid
            fx, fy = dx / "scores.json", base / f"{qid}_{arm_y}" / "scores.json"
            if fx.exists() and fy.exists():
                yield (qid, json.loads(fx.read_text())["overall"],
                       json.loads(fy.read_text())["overall"])

    def from_pairwise():
        pd = base / f"pairwise_{arm_x}_vs_{arm_y}"
        for f in sorted(pd.glob("*.json")) if pd.exists() else []:
            r = json.loads(f.read_text())
            yield (f.stem, r["x"]["overall"], r["y"]["overall"])

    paired_scores(from_absolute, "absolute 独立打分")
    paired_scores(from_pairwise, "pairwise 并排比较")


def fact_check(result_dir, arms="", sample=6):
    """客观指标：引用可核实率（FACT 风格）——核查"论断-引用"对，抓真实网页
    判定支撑与否。锚在网页内容上，不依赖裁判 rubric，跨批次可比性更强。
    sample=0 为全量核实（解析报告中所有论断-引用对，Cited-but-Not-Verified 式；
    贵——每对一次抓页+快模型判定，按需使用）。
    产物落各 run 目录 fact.json，末尾按 arm 汇总。"""
    from common.verify_cli import check_citation_support
    base = Path(result_dir)
    want = set(arms.split(",")) if arms else None
    rows = []
    for d in sorted(base.iterdir()):
        if not (d / "report.md").exists() or _prev_status(d) != "ok":
            continue
        arm = d.name.split("_", 1)[1]
        if want and arm not in want:
            continue
        ff = d / "fact.json"
        st = json.loads(ff.read_text()) if ff.exists() else None
        # 缓存的抽样结果在请求全量时失效（sampled < total_pairs 或旧版无 total_pairs）
        if st is not None and sample <= 0 and \
                st.get("sampled", 0) < st.get("total_pairs", float("inf")):
            st = None
        if st is None:
            try:
                _, st = check_citation_support((d / "report.md").read_text(),
                                               sample=sample)
                st.pop("detail", None)
                ff.write_text(json.dumps(st, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                print(f"fact FAILED {d.name}: {e}")
                continue
        if st.get("sampled"):
            rate = st["supported"] / st["sampled"]
            rows.append((d.name, arm, st["sampled"], round(rate, 2),
                         st.get("not_found"), st.get("over_cite")))
            extra = (f" not_found={st['not_found']} over_cite={st['over_cite']}"
                     if st.get("not_found") is not None else "")
            print(f"{d.name}: sampled={st['sampled']}/{st.get('total_pairs', '?')} "
                  f"supported_rate={rate:.2f}{extra}")
    for arm in sorted({r[1] for r in rows}):
        sub = [r for r in rows if r[1] == arm]
        tot = sum(r[2] for r in sub)
        avg = sum(r[3] * r[2] for r in sub) / tot if tot else 0
        nf = sum(r[4] or 0 for r in sub)
        oc = sum(r[5] or 0 for r in sub)
        print(f"ARM {arm} (n={len(sub)}): 引用可核实率 {avg:.2f}（核查 {tot} 对，"
              f"not_found {nf}，over_cite {oc}，not_found率 {nf/tot:.2f}）" if tot
              else f"ARM {arm} (n={len(sub)}): 无可核查对")


def fact_check_v2(result_dir, arms="", qids=""):
    """fact-v2 分层核验（全量）：拆原子子论断 + 多源联合判定 + 邻近池诊断。
    把 v1 的 not_found 拆解为 引用错位(supported_by_neighbor) / 部分真(partial) /
    真超写(not_found)，为写作侧修复(F9)提供靶子。产物 fact2.json。"""
    from common.verify_cli import check_citation_support_v2
    base = Path(result_dir)
    want = set(arms.split(",")) if arms else None
    want_q = set(qids.split(",")) if qids else None
    rows = []
    for d in sorted(base.iterdir()):
        if not (d / "report.md").exists() or _prev_status(d) != "ok":
            continue
        qid, arm = d.name.split("_", 1)
        if (want and arm not in want) or (want_q and qid not in want_q):
            continue
        ff = d / "fact2.json"
        if ff.exists():
            st = json.loads(ff.read_text())
        else:
            try:
                st = check_citation_support_v2((d / "report.md").read_text())
                ff.write_text(json.dumps(st, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                print(f"fact2 FAILED {d.name}: {e}")
                continue
        if st.get("total_pairs"):
            rows.append((d.name, arm, st))
            pc = st["pairs"]
            print(f"{d.name}: n={st['total_pairs']}  sup={pc['supported']} "
                  f"错位={pc['supported_by_neighbor']} 部分={pc['partial']} "
                  f"超写={pc['not_found']} 矛盾={pc['contradicted']} "
                  f"不可达={pc['unreachable']}")
    for arm in sorted({r[1] for r in rows}):
        sub = [r[2] for r in rows if r[1] == arm]
        tot = sum(s["total_pairs"] for s in sub)
        agg = {k: sum(s["pairs"].get(k, 0) for s in sub)
               for k in ("supported", "supported_by_neighbor", "partial",
                         "not_found", "contradicted", "conflict_temporal",
                         "conflict_substantive", "unreachable")}
        ok = agg["supported"] + agg["supported_by_neighbor"]
        reach = tot - agg["unreachable"]
        sc = {"total": sum(s["subclaims"]["total"] for s in sub),
              "supported": sum(s["subclaims"]["supported"] for s in sub)}
        conf_detail = (f"(时效 {agg['conflict_temporal']} 实质 "
                       f"{agg['conflict_substantive']})"
                       if agg["conflict_temporal"] or agg["conflict_substantive"]
                       else "")
        print(f"ARM {arm} (n={len(sub)}题, {tot}对): 严格可核实率 "
              f"{agg['supported']/reach:.2f} | 含错位 {ok/reach:.2f} | "
              f"子论断级 {sc['supported']/sc['total']:.2f} | "
              f"错位 {agg['supported_by_neighbor']} 部分 {agg['partial']} "
              f"真超写 {agg['not_found']} 矛盾 {agg['contradicted']}{conf_detail}"
              if reach else f"ARM {arm}: 全部不可达")


def fact_check_evidence(result_dir, arms=""):
    """句级本地核验（F9 系）：report_raw.md 的 [En] 句 vs evidence.jsonl 登记
    quote，零抓页。与 quote_check（摘录→页面子串审计）合成完整证据链。
    产物 fact_ev.json。"""
    from arms.arm_f9_evidence import _load_evidence
    from common.verify_cli import check_claims_vs_evidence
    base = Path(result_dir)
    want = set(arms.split(",")) if arms else None
    rows = []
    for d in sorted(base.iterdir()):
        raw = d / "report_raw.md"
        if not raw.exists() or _prev_status(d) != "ok":
            continue
        arm = d.name.split("_", 1)[1]
        if want and arm not in want:
            continue
        ff = d / "fact_ev.json"
        if ff.exists():
            st = json.loads(ff.read_text())
        else:
            try:
                st = check_claims_vs_evidence(raw.read_text(), _load_evidence(d))
                ff.write_text(json.dumps(st, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                print(f"fact_ev FAILED {d.name}: {e}")
                continue
        if st.get("total_claims"):
            rows.append((d.name, arm, st))
            c = st["claims"]
            print(f"{d.name}: 标记句={st['total_claims']}  sup={c['supported']} "
                  f"超写={c['not_found']} 矛盾={c['contradicted']} "
                  f"未登记={c['no_evidence']}")
    for arm in sorted({r[1] for r in rows}):
        sub = [r[2] for r in rows if r[1] == arm]
        tot = sum(s["total_claims"] for s in sub)
        agg = {k: sum(s["claims"][k] for s in sub)
               for k in ("supported", "not_found", "contradicted", "no_evidence")}
        judged = tot - agg["no_evidence"]
        print(f"ARM {arm} (n={len(sub)}题, {tot} 标记句): "
              f"句级支撑率 {agg['supported']/judged:.2f}（判定 {judged} 句）| "
              f"超写 {agg['not_found']} 矛盾 {agg['contradicted']} "
              f"未登记 {agg['no_evidence']}" if judged
              else f"ARM {arm}: 无可判定句")


def judge_drift(result_dir, limit=0):
    """rubric 措辞漂移诊断（JudgeSense 式）：同批报告用语义等价的两版 rubric
    各打一次，量化"裁判 prompt 微调导致 ±0.3-0.6 漂移"这一经验观察。
    一次性诊断工具，不进主评测路径；产物 <dir>/judge_drift.json。"""
    from eval.judge import RUBRIC_ALT, score_once
    questions = _load_questions()
    base = Path(result_dir)
    dirs = sorted(p for p in base.iterdir()
                  if (p / "report.md").exists() and _prev_status(p) == "ok")
    if limit:
        dirs = dirs[:limit]
    rows = []
    for d in dirs:
        qid = d.name.split("_")[0]
        report = (d / "report.md").read_text()
        try:
            s1 = score_once(questions[qid]["question"], report)
            s2 = score_once(questions[qid]["question"], report, rubric=RUBRIC_ALT)
        except Exception as e:  # noqa: BLE001
            print(f"drift FAILED {d.name}: {e}")
            continue
        delta = round(s1["overall"] - s2["overall"], 2)
        rows.append({"run": d.name, "rubric_main": s1["overall"],
                     "rubric_alt": s2["overall"], "delta": delta})
        print(f"{d.name}: 主rubric={s1['overall']} 改写版={s2['overall']} Δ={delta:+}")
    if rows:
        deltas = [r["delta"] for r in rows]
        mean_abs = sum(abs(x) for x in deltas) / len(deltas)
        mean_bias = sum(deltas) / len(deltas)
        print(f"\nrubric 措辞漂移 (n={len(rows)}): 平均|Δ|={mean_abs:.2f}，"
              f"系统性偏移={mean_bias:+.2f}，最大|Δ|={max(abs(x) for x in deltas):.2f}")
        print("解读：平均|Δ| 是裁判分数中'措辞噪声'的下界——小于它的 arm 间分差不可归因于机制")
        (base / "judge_drift.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1))


def summary(result_dir):
    rows = []
    for d in sorted(Path(result_dir).iterdir()):
        meta_f, score_f = d / "meta.json", d / "scores.json"
        if not meta_f.exists():
            continue
        meta = json.loads(meta_f.read_text())
        row = {"qid": meta["qid"], "arm": meta["arm"], "status": meta["status"],
               "sec": meta.get("seconds"), "tok_out": meta.get("tokens", {}).get("out")}
        if score_f.exists():
            s = json.loads(score_f.read_text())
            row.update({k: s[k] for k in
                        ("comprehensiveness", "depth", "instruction_following",
                         "readability", "overall")})
        rows.append(row)
    # 按 arm 汇总
    print(f"{'qid':6}{'arm':4}{'overall':8}{'compr':7}{'depth':7}{'instr':7}{'read':6}{'sec':6}")
    for r in rows:
        print(f"{r['qid']:6}{r['arm']:4}{r.get('overall','—'):<8}{r.get('comprehensiveness','—'):<7}"
              f"{r.get('depth','—'):<7}{r.get('instruction_following','—'):<7}"
              f"{r.get('readability','—'):<6}{r.get('sec','—'):<6}")
    for arm in sorted({r["arm"] for r in rows}):
        sub = [r for r in rows if r["arm"] == arm and "overall" in r]
        if sub:
            avg = {k: round(sum(r[k] for r in sub) / len(sub), 2)
                   for k in ("overall", "comprehensiveness", "depth",
                             "instruction_following", "readability")}
            print(f"ARM {arm} (n={len(sub)}): {avg}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="")
    ap.add_argument("--questions", default="")
    ap.add_argument("--tag", default="dev")
    ap.add_argument("--judge", default="")
    ap.add_argument("--samples", type=int, default=3,
                    help="每份报告独立打分次数（取中位数），默认 3")
    ap.add_argument("--summary", default="")
    ap.add_argument("--pairwise", default="", metavar="DIR",
                    help="对 --arms X,Y 两 arm 做 pairwise 裁判")
    ap.add_argument("--compare", default="", metavar="DIR",
                    help="对 --arms X,Y 两 arm 做配对比较（bootstrap CI）")
    ap.add_argument("--fact", default="", metavar="DIR",
                    help="客观指标：引用可核实率（可配 --arms 过滤）")
    ap.add_argument("--fact-sample", type=int, default=6, dest="fact_sample",
                    help="每份报告核查的论断-引用对数，0=全量（贵），默认 6")
    ap.add_argument("--v2", action="store_true",
                    help="配 --fact：用 fact-v2 分层核验（拆子论断/联合判定/邻近池）")
    ap.add_argument("--fact-ev", default="", metavar="DIR", dest="fact_ev",
                    help="句级本地核验（F9 系）：[En] 句 vs 登记 quote，零抓页")
    ap.add_argument("--judge-drift", default="", metavar="DIR", dest="judge_drift",
                    help="rubric 措辞漂移诊断（两版等价 rubric 各打一次）")
    ap.add_argument("--limit", type=int, default=0,
                    help="--judge-drift 限制诊断的报告数（省 API），0=全部")
    ap.add_argument("--no-search", action="store_true", dest="no_search",
                    help="闭卷基线：禁检索/阅读跑同题，产物 tag 自动加 _closedbook")
    ap.add_argument("--judges", default="", metavar="M1,M2",
                    help="多裁判鲁棒聚合（默认关闭；开启会改变分数量纲，仅专门批次用）")
    args = ap.parse_args()
    if args.judge:
        judge_all(args.judge, n_samples=args.samples, judges=args.judges)
    elif args.fact:
        if args.v2:
            fact_check_v2(args.fact, arms=args.arms, qids=args.questions)
        else:
            fact_check(args.fact, arms=args.arms, sample=args.fact_sample)
    elif args.fact_ev:
        fact_check_evidence(args.fact_ev, arms=args.arms)
    elif args.judge_drift:
        judge_drift(args.judge_drift, limit=args.limit)
    elif args.pairwise or args.compare:
        two = args.arms.split(",")
        if len(two) != 2:
            ap.error("--pairwise/--compare 需要 --arms X,Y 恰好两个 arm")
        if args.pairwise:
            pairwise_all(args.pairwise, *two)
        else:
            compare(args.compare, *two)
    elif args.summary:
        summary(args.summary)
    else:
        run_arms(args.arms.split(","), args.questions.split(","), args.tag,
                 closed_book=args.no_search)
