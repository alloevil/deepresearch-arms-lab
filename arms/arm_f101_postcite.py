"""Arm F10.1:引用后置化 + draft 阶段检索纪律(F10 的单点修复)。

F10 三题诊断(2026-07-20,q01/q05/q09 vs B):cite 阶段机制成立(错位/超写/
不可达≈0,DEER-VERI 复证 引用准确 B=0.21 vs F10=0.40),但 draft 阶段
"豁免引用职责"意外连检索动力一起豁免(draft 仅 5.5-6K 字符,q01 自述"多数
内容基于训练知识撰写")→ 覆盖塌缩(引用对 2-12 vs B 的 23-32),judge
−0.75~−2.26。外部印证(arXiv 2607.12257):忠实性由曝光决定,覆盖由检索
决定——F10 修了前者,伤了后者。

F10.1 单变量修改(仅 draft prompt 的检索条款;cite 阶段与兜底逻辑复用 F10):
- 恢复 B3 式检索纪律:每个主体章节至少精读 2 个不同网站的页面后才可写;
- 篇幅纪律 700-1200 字/节(对齐 B3,防"少写少检索");
- 引用豁免不变(不标 URL、无参考节)——这仍是与 B 的单变量差异。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger  # noqa: E402
from arms.arm_f10_postcite import run as _run_f10  # noqa: E402

PROMPT_DRAFT_V2 = """今天是 {date}。你是一名研究员，请完成下面的深度研究任务，产出一份中文研究报告。

【研究任务】
{question}

【可用工具】只能用这两个命令联网（内置的网页搜索不可用）：
- python3 {cli} search "中文查询词" —— 搜索，返回 JSON 结果
- python3 {cli} read "URL" —— 读取网页正文

【要求】
1. 【检索纪律】写作前必须充分检索：每个主体章节至少用 read 精读 2 个不同网站
   的页面后才可动笔写该节；检索不到时换语言（英文）、换角度再试至少一次。
   事实论断必须来自你读过的页面内容，不得依赖你的训练知识编造具体数字与日期。
2. 报告不需要标注引用或来源 URL，也不需要"参考来源"一节——引用由后续
   编辑流程统一补挂，你专注于检索充分、内容准确、写作质量。
3. 【篇幅纪律】每个主体章节 700-1200 字；宁可信息密集，不要复述与注水。
4. 报告用 Markdown，含分节结构和明确结论；
5. 把最终报告完整写入文件 {out}（只写报告本身）。"""


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    # draft_max_turns=90:检索纪律使工具调用轮数结构性增加,q05 实证撞 60 上限;
    # F 系先例(F8 用 100)支持放宽,不破 B 对照(B 的 60 按其自身工作量标定)
    return _run_f10(question, logger, workdir, draft_prompt=PROMPT_DRAFT_V2,
                    draft_max_turns=90)


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF101_"))
    logger = TraceLogger("/tmp/armF101_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商。",
              logger, wd)[:1200])
