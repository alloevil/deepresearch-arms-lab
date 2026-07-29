<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:0D1117,50:1F6FEB,100:8B5CF6&height=220&section=header&text=deepresearch-arms-lab&fontSize=60&fontColor=FFFFFF&fontAlignY=35&desc=14-arm%20ablation%20study%20on%20deep%20research%20pipelines&descSize=18&descAlignY=55&animation=fadeIn" width="100%" alt="deepresearch-arms-lab — 14-arm ablation study on deep research pipelines"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Focus-Deep%20Research%20Pipeline%20Design-FF6B6B?style=for-the-badge&labelColor=0D1117&logo=target&logoColor=white" />
  <img src="https://img.shields.io/badge/Method-14_arm%20Ablation-8B5CF6?style=for-the-badge&labelColor=0D1117&logo=flask&logoColor=white" />
  <img src="https://img.shields.io/badge/Eval-Claude%20Opus%204.8%20Blind%20Judging-58A6FF?style=for-the-badge&labelColor=0D1117&logo=openai&logoColor=white" />
</p>

<br/>

## 🎯 The Question

> **Can a weak Chinese base model write well AND avoid fabricating citations when doing deep research (autonomous search + report writing)?**

14 prompt/pipeline designs ("arms"), a unified evaluation system, all tested on the same weak base model (**MiMo 2.5 Pro**) with the same set of Chinese research topics — documenting which mechanisms actually work and which seem reasonable but fail in practice.

<br/>

## 🔑 Key Findings

<table>
<tr>
<td width="50%">

### ❌ Negative Result

**"Self-disciplined citation during writing" doesn't work.**

Having the model maintain a "key claims registry" (F9.1) is essentially adding a heavy protocol — the weak base model can't hold it. Sentence-level support rate stays flat, latency doubles.

</td>
<td width="50%">

### ⚖️ The Real Tradeoff (revised at n=20)

**Pipeline structure reliably buys faithfulness — but it isn't free, and there's no dual-optimal winner.**

All three structural mechanisms (F10.2, F11, F115) now score *below* the bare baseline on judged quality at n=20. The discount for faithfulness ranges from mild (F115: −0.10 judge for +0.25 faithfulness) to steep (F102: −0.30 for +0.13). Pick based on which axis your use case actually weights.

</td>
</tr>
<tr>
<td width="50%">

### ⚠️ Boundary Finding

**A single writing pass can't have both breadth and discipline.**

Three independent perturbations (F11.1/F11.2/F11.3) all degraded faithfulness — the cognitive budget of a single pass is insufficient. This boundary is stably reproduced.

</td>
<td width="50%">

### 📐 The Cost of Honesty Generalizes

**Not a single-question fluke — it's a systematic effect on low-evidence topics, confirmed by expanding the test set.**

At n=15, one retrieval-poor question made F115 honestly report a blank answer and get penalized. Expanding to n=20 with more soft, less-quantifiable topics (low-code tooling debates, education policy, box-office rankings) reproduced the same penalty across most of the new questions — flipping F115's net judge-quality delta from +0.12 to **−0.10**.

</td>
</tr>
</table>

<br/>

## 📊 Arm Comparison

> Judge = Claude Opus 4.8 blind eval ×3 median; Fact = fact-v2 clause-level support rate. **n is a critical column to check.**

### 🔬 Highest Faithfulness-Per-Point-Lost: F115 — Three-Stage Pipeline

Pre-cite research → offline writing → post-hoc verification. **At n=20, this is no longer dual-optimal** — it trades a small amount of judged quality for the biggest faithfulness gain among the full pipelines. Not "the winner," but the best rate on this specific tradeoff.

| Arm | judge | faithful. | n | delta vs B (n=20) |
|:---|---:|---:|---:|---:|
| [**F115**](arms/arm_f115_full.py) | **7.94** | **0.65** | **20** | quality −0.10, faith. +0.25 |

### 📌 Baseline & Negative Results

> These arms tested "self-discipline" approaches that **don't work** on weak base models.

| Arm | Mechanism | judge | faithful. | n | Verdict |
|:---:|:---|---:|---:|---:|:---:|
| [B](arms/arm_b_claude_code.py) | Bare execution (no citation protocol) | 8.04 | 0.40 | 20 | ![baseline](https://img.shields.io/badge/●-Baseline-gray?style=flat&labelColor=transparent) |
| [B3](arms/arm_b3_protocol.py) | + citation protocol prompt | 8.04 | 0.48 | 10 | ![negative](https://img.shields.io/badge/●-Gains%20didn't%20transfer-red?style=flat&labelColor=transparent) |
| [F9.1](arms/arm_f91_evidence.py) | + key claims registry during generation | 8.13 | 0.48 | 10 | ![negative](https://img.shields.io/badge/●-Weak%20model%20can't%20hold%20protocol-red?style=flat&labelColor=transparent) |

### 🔀 Faithfulness vs. Quality: Structural Solutions

> Three directions that **reliably improve faithfulness** via structural changes — but all now cost judged quality at n=20. Worth it depends on your priorities, not a free win.

| Arm | Mechanism | judge | faithful. | n | delta judge / faith. vs B |
|:---:|:---|---:|---:|---:|:---:|
| [F10](arms/arm_f10_postcite.py) | Post-hoc citation (withdraw protocol) | 7.58 | 0.72 | 3 | ![post-hoc](https://img.shields.io/badge/●-Post--hoc-blue?style=flat&labelColor=transparent) |
| [**F10.2**](arms/arm_f102_postverify.py) | **B + independent post-hoc verification** | **7.74** | **0.53** | **20** | −0.30 / +0.13 |
| [**F11**](arms/arm_f11_precite.py) | **Source-side pre-citation** | **7.81** | **0.69** | **19** | −0.23 / +0.29 |

*F11 is n=19 not 20 — it hit a reproducible 60-turn budget ceiling on one question (a "top-10 box office, compare 4 dimensions" prompt that needs many source reads); retried twice with the identical failure, so it's recorded as a genuine negative result rather than patched by raising the turn limit just for that question.*

### ⚠️ Boundary Exploration

> Perturbations to F11 that **all degraded faithfulness** — single-pass cognitive budget is insufficient.

| Arm | Variation | judge | faithful. | n | Effect |
|:---:|:---|---:|---:|---:|:---:|
| [F11.1](arms/arm_f111_precite.py) | + breadth quota (wider retrieval budget) | 7.54 | 0.68 | 3 | ![degraded](https://img.shields.io/badge/●-degraded-orange?style=flat&labelColor=transparent) ↓ faith. −0.05, misattribution appears with more sources |
| [F11.2](arms/arm_f112_dualchannel.py) | + dual-channel (allow background/parametric knowledge alongside citations) | 8.83 | 0.74 | 3 | ![degraded](https://img.shields.io/badge/●-degraded-orange?style=flat&labelColor=transparent) discipline ignored — contradictions return despite similar subclaim rate |
| [F11.3](arms/arm_f113_atomic.py) | + force one atomic claim per sentence | 8.60 | 0.55 | 3 | ![degraded](https://img.shields.io/badge/●-degraded-orange?style=flat&labelColor=transparent) ↓ faith. −0.18, induces more weakly-grounded assertions |

### 🌍 External System Comparison

> A sanity check, not a firm conclusion — **n=3, labeled preliminary.**

| Arm | Mechanism | judge | faithful. | n | Verdict |
|:---:|:---|---:|---:|---:|:---:|
| [G](arms/arm_g_gptr.py) | GPT-Researcher (mature external framework) + same weak base model | 5.75 | 0.45 | 3 | ![negative](https://img.shields.io/badge/●-Preliminary%2C%20not%20a%20conclusion-red?style=flat&labelColor=transparent) |

GPT-Researcher is a well-regarded open-source deep-research framework, but swapping in this weak Chinese base model collapsed its results — a leaderboard-strong pipeline's advantage doesn't automatically transfer across model/language/retrieval-source changes. Only 3 questions were run (search-quota and embedding-language issues made a larger batch impractical in this round), so treat this as a preliminary signal, not proof that external frameworks can't work here.

<br/>

## 🔬 How Each Approach Works

The one-line "Mechanism" column above compresses a lot — here's what each family actually does, mechanically. Every arm shares the same base agent loop (search → read → write); what differs is *when citations get attached and by which pass*.

### 1️⃣ Self-discipline during writing (B → B3 → F9.1) — doesn't hold up

- **[B](arms/arm_b_claude_code.py)**: one continuous pass, ordinary prompting. No special citation machinery — this is "just ask the model to do deep research."
- **[B3](arms/arm_b3_protocol.py)**: same single pass, but the prompt adds an explicit citation protocol (cite every factual claim, follow a specific format). Tests whether *asking nicely* is enough.
- **[F9.1](arms/arm_f91_evidence.py)**: goes further — the model must maintain a running "key-claims ledger" file, appending each claim and its verbatim source excerpt *before* it's allowed to use that claim in the report. Tests whether external bookkeeping discipline holds up under a heavier protocol. It doesn't: the weak model can't reliably maintain the ledger, and latency roughly doubles for no faithfulness gain.

### 2️⃣ Post-hoc citation repair (F10 → F10.2) — audit after the fact

- **[F10](arms/arm_f10_postcite.py)**: the drafting pass writes completely freely (citation protocol removed from the prompt entirely). A second, independent pass then reads the draft plus the raw tool-call trace (`search_calls.jsonl`) and retroactively attaches citations to whichever sentences it can back up with something actually retrieved.
- **[F10.2](arms/arm_f102_postverify.py)**: same second pass, but instead of attaching citations from scratch, it *audits what B already wrote* — for each existing citation it decides keep / weaken / replace / flag `[unverified]`, checking the claim against the real fetched page content. This is the lighter-touch version: it doesn't touch the drafting pass at all, just fact-checks and honestly labels it afterward.

### 3️⃣ Source-side pre-citation (F11 and its perturbations) — cite by ID, not by memory

- **[F11](arms/arm_f11_precite.py)**: the search/read tool is wrapped so every fetched page gets a stable numeric id `[Sn]` injected into a header the model sees. The writing prompt's rule is simple: *you may only cite a page you were assigned a number for, and you write the number — never a URL.* A mechanical post-processing step converts `[Sn]` into real numbered footnotes with the actual URL filled in by code, not by the model. The model structurally cannot fabricate a URL, because it never writes one.
- **[F11.1](arms/arm_f111_precite.py)**: same mechanism, larger retrieval budget (reads more sources before writing) — tests whether breadth alone helps. It doesn't: more sources in play means more chances to cite the wrong number.
- **[F11.2](arms/arm_f112_dualchannel.py)**: same mechanism, but the writing prompt now also permits stating things from general/background knowledge alongside numbered citations (a second, uncited "channel"). Tests whether relaxing "cite it or don't say it" even slightly is safe. It isn't: once an escape hatch exists, the model leans on it and contradictions creep back in.
- **[F11.3](arms/arm_f113_atomic.py)**: same mechanism, plus a structural constraint forcing exactly one atomic factual claim per sentence (no compound sentences bundling multiple claims under one citation). Tests whether finer-grained sentences produce cleaner citations. It backfires — more, weaker-grounded micro-claims.

### 4️⃣ Research/writing separation (F11.4 → F115) — split the cognitive budget across passes

- **F11.4** (precursor to F115, not separately tabled above): splits F11 into two hard-separated passes. A dedicated *research* pass does the broad reading and takes verbatim notes (with `[Sn]` numbers) into a notes file. A separate *writing* pass drafts the report from *only* that notes file — it has no search/read tool access at all, a tool-level constraint, not just an instruction. This is what let breadth and citation discipline coexist without one pass having to hold both jobs.
- **[F115](arms/arm_f115_full.py)**: F11.4's two stages, plus a third — the F10.2-style post-hoc audit runs on the output, flagging anything that's still unverified. Three passes, each with exactly one job: **research broadly → write offline from notes only → audit and honestly label what didn't hold up.**

### 🌍 External baseline (G)

- **[G](arms/arm_g_gptr.py)**: the entire pipeline is swapped for [GPT-Researcher](https://github.com/assafelovic/gpt-researcher), pointed at the same base model and (as far as practical) the same search backend, to check whether a mature off-the-shelf framework simply does better than any custom design here.

<br/>

## ⚠️ Known Limitations

Disclosed here instead of glossed over, since the project's own thesis is that honesty about gaps beats a smoother-looking number:

- **No token/cost instrumentation.** `meta.json`'s `tokens.in/out` fields are always 0 in this round — `avg_secs` (wall-clock time per run) is the only cost proxy available. "Is the extra pipeline stage worth it?" can only be answered on latency here, not token spend.
- **The GPT-Researcher comparison (arm G) is n=3.** Labeled preliminary everywhere it's mentioned — not enough samples to support "external systems necessarily fail on weak base models" as a strong claim.
- **Judge scores have real run-to-run variance** (~1.0 on the same prompt, measured empirically). Any two-arm comparison should be read alongside its `n`, not as a bare point estimate.
- **The topic mix changes the headline numbers a lot.** At n=10, F115 led B by +0.66 judge; at n=15, +0.12; at n=20 (after adding softer, less-quantifiable topics), **−0.10**. The mechanism behind this (honest disclosure of retrieval gaps gets penalized more than confident glossing-over) is consistent and explainable, not noise — but it means none of these numbers should be treated as a fixed, topic-independent property of the arm. Expect them to keep moving as the test set grows.

<br/>

## 🏗️ Project Structure

`arms/` has 31 files in total — the 14 covered in the comparison above, plus
17 earlier-round experiments (workflow/scaffold designs, model-choice arms)
that are superseded but kept for the historical record; see `EXPERIMENTS.md`
for their story.

| Directory | Contents | Description |
|:---|:---|:---|
| `arms/` | 31 arm implementations | B/F/G series pipeline designs |
| `eval/` | judge.py, run.py, questions.json | Evaluation system (Claude Opus blind judging) |
| `common/` | Shared utility functions | Common dependencies across arms |
| `scripts/` | dash_agg.py, dash_qa_build.py, sanitize.py | Data processing & dashboard generation |

```
deepresearch-arms-lab/
├── arms/              # 31 arm implementations
│   ├── arm_b_claude_code.py
│   ├── arm_f102_postverify.py
│   ├── arm_f11_precite.py
│   ├── arm_f115_full.py
│   └── ...
├── eval/              # Evaluation system
├── common/            # Shared utilities
├── scripts/           # Data processing
├── dashboard.html     # Interactive results dashboard
├── EXPERIMENTS.md     # Detailed experiment log
└── qa_data.json       # Evaluation data
```

<br/>

## 📈 Interactive Dashboard

Open `dashboard.html` in any browser — no server, no internet required:

- **Scatter plot**: quality vs. faithfulness tradeoff
- **Bar chart**: arm rankings
- **Timeline**: experiment progression
- **Click any arm/topic**: original question + full report + scoring rationale

```bash
open dashboard.html
# or
python3 -m http.server 8080
```

<br/>

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment (edit, then source — this is a shell script, not a .env file)
cp env_example.sh env.sh
# edit env.sh: point ANTHROPIC_BASE_URL/ANTHROPIC_AUTH_TOKEN at your own
# Anthropic-compatible gateway (https://api.anthropic.com works with no code changes)
source env.sh

# Run an arm on specific questions, then judge + fact-check the results
python3 -m eval.run --arms B,F102,F11,F115 --questions q01,q02 --tag my_run
python3 -m eval.run --judge results/my_run --samples 3
python3 -m eval.run --fact results/my_run --v2 --arms B,F102,F11,F115

# Rebuild dashboard data from your own run
python3 scripts/dash_agg.py
python3 scripts/dash_qa_build.py
python3 scripts/embed_qa_data.py   # inline qa_data.json into dashboard.html
```

<br/>

## 🙏 Acknowledgments

- 10 of the 20 topics in `eval/questions_ext.json` (`e11`–`e20`) are used in the main n=20 comparison, borrowed verbatim from [DeepResearch Bench](https://github.com/Ayanami0730/deep_research_bench) (Apache-2.0) — see `THIRD_PARTY_NOTICES.md` for full attribution
- Evaluation design inspired by Anthropic's CitationAgent and Perplexity's search-layer pre-binding citation approach

<br/>

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:0D1117,50:1F6FEB,100:8B5CF6&height=100&section=footer" width="100%" />
</p>
