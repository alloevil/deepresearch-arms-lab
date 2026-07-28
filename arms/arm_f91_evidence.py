"""Arm F9.1：证据绑定写作·关键论断登记制（F9 的降摩擦版）。

F9 首战诊断（2026-07-08，3 题同批 vs B3）：证据绑定使子论断级可核实率
0.39→0.69、编造清零，但裁判 −0.29——**代价在覆盖与深度（各 −0.5）而非行文**：
「凡写必先逐字登记」的流程摩擦挤占了研究预算（漏主流主体、信源收窄）。

F9.1 单变量修改（仅第 5 条引用条款,其余与 F9 逐字同构——用切分重组保证）：
- 研究阶段照常充分检索,广度优先;登记改为写作前**批量**进行;
- 只对**关键事实论断**（数字/日期/金额/排名/点名主体/直接引语）要求登记标注,
  背景叙述与自有分析豁免;
- 强度纪律/综合判断标注/四要素要求不变,显式禁止"因登记成本省略覆盖"。

目标：收回 compr/depth 的 −0.5,保住 fact 优势。机械件与 F9 完全共用。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import TraceLogger  # noqa: E402
from arms.arm_f9_evidence import PROMPT as _F9_PROMPT  # noqa: E402
from arms.arm_f9_evidence import _run_evidence_arm  # noqa: E402

_NEW_CLAUSE5 = """5. 【证据绑定写作——关键论断登记制】
   a) 研究阶段照常充分检索与阅读，覆盖广度与分析深度优先。写作某一章节前，
      把该节要引用的证据批量登记进 evidence.jsonl（一行一条 JSON）：
      {{"id": "E1", "url": "来源URL", "quote": "从网页正文逐字复制的原文片段
      （≤200字）"}}。quote 必须逐字复制页面原文，不得改写、概括或翻译
      （英文页面就存英文原文）；需要原文时可用 read 工具重新打开页面。
   b) 只对【关键事实论断】要求登记与标注：具体数字、日期、金额、排名、
      点名主体的事实性陈述、直接引语。写作时在这些论断句末标注 [En]，
      一句一证据；来自不同证据的关键事实拆成不同句子、各标各的 ID。
      背景叙述、常识性铺垫、你自己的分析推断不需要登记或标注。
   c) 论断措辞强度不得超过 quote 原文：原文是"计划/目标/预计"，不得写成
      "将/已经/确定"；原文没有的数字与结论不得出现。
   d) 跨证据的综合判断（对比结论、趋势判断、评估）标注全部依据，如
      「……整体呈加速态势[综合 E2,E5]。」纯属你的分析推断可不标 ID。
   e) 深度四要素不变——每个主体章节须覆盖：具体数据点、多方对比、机制解释、
      批判性评估。**不得因登记成本而省略应有的覆盖、对比与深度**。
"""

# 切分重组：除第 5 条外与 F9 逐字一致（第 5 条是本消融的单变量）
_head, _rest = _F9_PROMPT.split("5. 【证据绑定写作", 1)
_tail = _rest.split("6. 【内省自检】", 1)[1]
PROMPT = _head + _NEW_CLAUSE5 + "6. 【内省自检】" + _tail


def run(question: str, logger: TraceLogger, workdir: Path) -> str:
    return _run_evidence_arm(question, logger, workdir, PROMPT)


if __name__ == "__main__":
    import tempfile
    wd = Path(tempfile.mkdtemp(prefix="armF91_"))
    logger = TraceLogger("/tmp/armF91_smoke.jsonl")
    print(run("简要调研 2025 年以来钠离子电池的商业化进展，列出至少三家厂商，并评估其中一家的降本路径。",
              logger, wd)[:1200])
