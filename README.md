<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:0D1117,50:1F6FEB,100:8B5CF6&height=220&section=header&text=deepresearch-arms-lab&fontSize=60&fontColor=FFFFFF&fontAlignY=35&desc=14-arm%20ablation%20study%20on%20deep%20research%20pipelines&descSize=18&descAlignY=55&animation=fadeIn" width="100%" alt="deepresearch-arms-lab — 14-arm ablation study on deep research pipelines"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Focus-Deep%20Research%20Pipeline%20Design-FF6B6B?style=for-the-badge&labelColor=0D1117" />
  <img src="https://img.shields.io/badge/Method-14--arm%20Ablation-8B5CF6?style=for-the-badge&labelColor=0D1117" />
  <img src="https://img.shields.io/badge/Eval-Claude%20Opus%204.8%20Blind%20Judging-58A6FF?style=for-the-badge&labelColor=0D1117" />
</p>

<br/>

## 🎯 The Question

> **能不能让一个弱的中文基座模型，在做 deep research（自主检索+写报告）时，既写得好、又不瞎编引用？**

14 个 prompt/pipeline 方案（"arm"），同一套评测体系，在同一个弱基座模型（**MiMo 2.5 Pro**）上跑同一批中文调研题——记录哪些机制真的有效、哪些看起来合理但实测无效。

<br/>

## 🔑 Key Findings

<table>
<tr>
<td width="50%">

### ❌ 负结果

**"模型写作时自觉遵守引用协议"这条路走不通。**

让模型维护"关键论断登记表"（F9.1）本质上是给它加重协议——弱基座守不住，句级支撑率原地踏步，耗时翻倍。

</td>
<td width="50%">

### ✅ 正结果

**可信性问题可以靠 pipeline 结构解决，但要分阶段付认知账。**

三个方向都被验证有效：引用后置化（F10.2）、采集侧预引用（F11）、研究写作分离（F115）。

</td>
</tr>
<tr>
<td width="50%">

### ⚠️ 边界发现

**单个写作 pass 里不能既要广度又要纪律。**

三次独立扰动（F11.1/F11.2/F11.3）全部让忠实度变差——同一个 pass 的认知预算不够，这条边界稳定复现。

</td>
<td width="50%">

### 📐 诚实的代价

**"诚实"在裁判眼里不一定是优点，会随题目难度放大。**

F115 的"没读过不得写"纪律在冷门题上诚实交了白卷，裸模型靠参数化知识反而分数更高。

</td>
</tr>
</table>

<br/>

## 📊 Arm Comparison

> Judge = Claude Opus 4.8 盲评 ×3 取中位; Fact = fact-v2 子句级支持率。**n 是判读时必须看的一列。**

| Arm | 机制 | judge | 忠实度 | n | 备注 |
|:---:|:---|---:|---:|---:|:---|
| B | 裸执行（无引用协议） | 8.09 | 0.47 | 15 | 基线 |
| B3 | + 引用协议 prompt | 8.04 | 0.48 | 10 | 早期模型增益未迁移到弱基座 |
| F9.1 | + 生成时关键论断登记 | 8.13 | 0.48 | 10 | 负结果：弱基座守不住 |
| F10 | 引用后置化（撤协议） | 7.58 | 0.72 | 3 | 精度赢但覆盖塌 |
| **F10.2** | **B 原样 + 独立后置核修** | **7.67** | **0.72** | **3** | 覆盖修复+诚实标注 |
| **F11** | **采集侧预引用** | 7.63 | **0.73** | 10 | 错位/矛盾结构性清零 |
| F11.1 | F11 + 允许背景知识 | 7.80 | 0.55 | 3 | 忠实度变差 |
| F11.2 | F11 + 放宽单源上限 | 7.97 | 0.55 | 3 | 忠实度变差 |
| F11.3 | F11 + 原子句拆分 | 8.17 | 0.59 | 3 | 忠实度变差 |
| **F115** | **预引用研究 → 无网写作 → 后置核修** | **8.75** | **0.67** | **15** | 双优方案（n=15 验证） |

<br/>

## 🏗️ Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                     deepresearch-arms-lab                       │
├──────────────┬──────────────┬──────────────┬───────────────────┤
│   arms/      │   eval/      │   common/    │   scripts/        │
│              │              │              │                   │
│  30 个 arm   │  judge.py    │  共享工具    │  dash_agg.py      │
│  实现文件    │  run.py      │  函数库     │  dash_qa_build.py │
│              │  questions   │              │  sanitize.py      │
│  B/F/G 系列  │  .json       │              │                   │
└──────────────┴──────────────┴──────────────┴───────────────────┘
```

<br/>

## 📈 Interactive Dashboard

双击 `dashboard.html` 或用任意静态服务器打开，不需要联网/不需要后端：

- 散点图：质量-可信性权衡
- 条形图：arm 排名
- 时间线：实验推进过程
- 点击任意 arm/题目：问题原文 + 报告全文 + 评分理由

```bash
# 本地打开
open dashboard.html
# 或
python3 -m http.server 8080
```

<br/>

## 🚀 Quick Start

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp env_example.sh .env
# 编辑 .env 填入 API key

# 运行评测
python3 eval/run.py
```

<br/>

## 📂 Project Structure

```text
deepresearch-arms-lab/
├── arms/                    # 30 个 arm 实现
│   ├── arm_b_claude_code.py # 基线：裸执行
│   ├── arm_f102_postverify.py  # 引用后置化
│   ├── arm_f11_precite.py      # 采集侧预引用
│   ├── arm_f115_full.py        # 三阶段全流水线
│   └── ...
├── eval/                    # 评测体系
│   ├── judge.py             # Claude Opus 4.8 盲评
│   ├── questions.json       # 主题库（10 题）
│   ├── questions_ext.json   # 扩展题库（15 题）
│   └── run.py               # 评测入口
├── common/                  # 共享工具函数
├── scripts/                 # 数据处理脚本
├── dashboard.html           # 交互式结果面板
├── EXPERIMENTS.md           # 实验详细记录
└── requirements.txt
```

<br/>

## 🙏 Acknowledgments

- 5 题借自 [DeepResearch Bench](https://github.com/GAIR-NLP/DeepResearch-Bench) 用于交叉验证
- 评测体系参考 Anthropic CitationAgent、Perplexity 检索层预绑定引用的设计思路

<br/>

<p align="center">
  <img src="https://capsule-render.vercel.app/api?type=waving&color=0:0D1117,50:1F6FEB,100:8B5CF6&height=100&section=footer" width="100%" />
</p>
