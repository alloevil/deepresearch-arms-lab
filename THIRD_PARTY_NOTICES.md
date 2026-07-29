# Third-Party Notices

This repository's own code is licensed under the MIT License (see `LICENSE`).
It also redistributes a small amount of third-party data, listed below with
its original license and attribution.

## DeepResearch Bench questions (Apache License 2.0)

`eval/questions_ext.json` contains 24 research questions (ids `e01`–`e19`,
`e21`–`e25`; `e20` was intentionally skipped to avoid reusing the id of a
removed question — see below) borrowed verbatim from the **DeepResearch
Bench** project. Of these, `e11`–`e19` and `e21`–`e25` (14 questions) are
used in this repo's main n=24 comparison (added to the 10 self-authored
questions in `eval/questions.json`); `e01`–`e10` were used in earlier
exploratory generalization checks documented in `EXPERIMENTS.md` and are
not part of the main comparison table. (A 20th borrowed question,
box-office rankings, was tried and removed — see `EXPERIMENTS.md` for why.)

- Source: https://github.com/Ayanami0730/deep_research_bench
- License: Apache License 2.0 (full text: https://www.apache.org/licenses/LICENSE-2.0)
- Each borrowed question in `eval/questions_ext.json` carries a `"source"`
  field naming the exact upstream question id it was copied from
  (e.g. `"DeepResearch-Bench#6 (Apache-2.0, Ayanami0730/deep_research_bench)"`).

No other content from DeepResearch Bench (code, scoring rubric, or other
question sets) is included in this repository — only the question text
itself, used here as a held-out evaluation set for a different purpose
(comparing citation-faithfulness/report-quality tradeoffs across pipeline
designs on a weaker base model) than the original benchmark's intended use.

Per Apache-2.0 §4, this NOTICE file preserves attribution for the redistributed
content; it does not itself relicense this repository's own code, which
remains MIT (see `LICENSE`).
