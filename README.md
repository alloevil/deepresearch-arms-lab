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

### ✅ Positive Result

**Credibility can be solved via pipeline structure, but requires phased cognitive budgeting.**

Three directions validated: post-hoc citation repair (F10.2), source-side pre-citation (F11), and research/writing separation (F115).

</td>
</tr>
<tr>
<td width="50%">

### ⚠️ Boundary Finding

**A single writing pass can't have both breadth and discipline.**

Three independent perturbations (F11.1/F11.2/F11.3) all degraded faithfulness — the cognitive budget of a single pass is insufficient. This boundary is stably reproduced.

</td>
<td width="50%">

### 📐 The Cost of Honesty

**"Honesty" isn't always rewarded by judges, and this effect scales with topic difficulty.**

F115's "no read, no write" discipline honestly reported blank answers on obscure topics, while the unconstrained base model padded out a readable (but unverifiable) report and scored higher.

</td>
</tr>
</table>

<br/>

## 📊 Arm Comparison

> Judge = Claude Opus 4.8 blind eval ×3 median; Fact = fact-v2 clause-level support rate. **n is a critical column to check.**

| Arm | Mechanism | judge | faithful. | n | Notes |
|:---:|:---|---:|---:|---:|:---|
| B | Bare execution (no citation protocol) | 8.09 | 0.47 | 15 | Baseline |
| B3 | + citation protocol prompt | 8.04 | 0.48 | 10 | Gains from early models didn't transfer to weak base |
| F9.1 | + key claims registry during generation | 8.13 | 0.48 | 10 | Negative: weak model can't hold the protocol |
| F10 | Post-hoc citation (withdraw protocol) | 7.58 | 0.72 | 3 | Precision wins but coverage collapses |
| **F10.2** | **B as-is + independent post-hoc verification** | **7.67** | **0.72** | **3** | Coverage repair + honest annotation |
| **F11** | **Source-side pre-citation** | 7.63 | **0.73** | 10 | Structural elimination of misalignment |
| F11.1 | F11 + allow background knowledge | 7.80 | 0.55 | 3 | Faithfulness degraded |
| F11.2 | F11 + relax per-source limit | 7.97 | 0.55 | 3 | Faithfulness degraded |
| F11.3 | F11 + atomic sentence splitting | 8.17 | 0.59 | 3 | Faithfulness degraded |
| **F115** | **Pre-cite research → offline writing → post-hoc verification** | **8.75** | **0.67** | **15** | Dual-optimal (n=15 validated) |

<br/>

## 🏗️ Project Structure

| Directory | Contents | Description |
|:---|:---|:---|
| `arms/` | 30 arm implementations | B/F/G series pipeline designs |
| `eval/` | judge.py, run.py, questions.json | Evaluation system (Claude Opus blind judging) |
| `common/` | Shared utility functions | Common dependencies across arms |
| `scripts/` | dash_agg.py, dash_qa_build.py, sanitize.py | Data processing & dashboard generation |

```
deepresearch-arms-lab/
├── arms/              # 30 arm implementations
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

# Configure environment
cp env_example.sh .env
# Edit .env with your API keys

# Run evaluation
python3 eval/run.py
```

<br/>

## 🙏 Acknowledgments

- 5 topics borrowed from [DeepResearch Bench](https://github.com/GAIR-NLP/DeepResearch-Bench) for cross-validation
- Evaluation design inspired by Anthropic's CitationAgent and Perplexity's search-layer pre-binding citation approach

<br/>

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:0D1117,50:1F6FEB,100:8B5CF6&height=100&section=footer" width="100%" />
</p>
