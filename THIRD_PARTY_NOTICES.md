# Third-Party Notices

This repository's own code is licensed under the MIT License (see `LICENSE`).
It also redistributes a small amount of third-party data, listed below with
its original license and attribution.

## DeepResearch Bench questions (Apache License 2.0)

`eval/questions_ext.json` contains 10 research questions (ids `e07`–`e15`,
plus `e01`–`e06`) borrowed verbatim from the **DeepResearch Bench** project:

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
