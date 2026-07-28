#!/usr/bin/env python3
"""把 qa_data.json 内嵌进 dashboard.html,让页面 file:// 双击直接可用。

背景:浏览器出于安全策略,禁止 file:// 页面用 fetch() 读本地 JSON —— 双击打开
dashboard.html 时,数据表点击 arm 会打开一个空弹窗("该组暂无落盘的逐题产物"),
看起来像是点击没反应。内嵌数据(而不是运行时 fetch)从根上解决这个问题,
GitHub Pages/本地 server 场景下行为不变。

用法: python3 scripts/embed_qa_data.py
依赖 dashboard.html 里存在这个精确的锚点(两行):
    let QA_DATA = {};
    fetch('qa_data.json').then(r => r.json()).then(d => { QA_DATA = d; }).catch(() => {});
重跑 scripts/dash_qa_build.py 生成新 qa_data.json 后,再跑本脚本重新内嵌。
"""
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
ANCHOR = ("let QA_DATA = {};\n"
          "fetch('qa_data.json').then(r => r.json()).then(d => { QA_DATA = d; }).catch(() => {});")


def embed() -> None:
    html_path = LAB / "dashboard.html"
    qa_path = LAB / "qa_data.json"
    html = html_path.read_text()
    qa_raw = qa_path.read_text()

    if ANCHOR not in html:
        print("锚点未找到——dashboard.html 可能已经是内嵌版本,或加载逻辑已变更。"
              "先从 git 历史恢复 fetch 版本再重跑本脚本。", file=sys.stderr)
        sys.exit(1)

    # 转义 </script>,避免报告全文里偶然出现这个子串把 <script> 标签提前截断
    qa_safe = qa_raw.replace("</script", "<\\/script")
    html = html.replace(ANCHOR, f"const QA_DATA = {qa_safe};")
    html_path.write_text(html)
    print(f"已内嵌 {qa_path.name}({len(qa_raw)/1024:.0f} KB)到 dashboard.html"
          f"(新体积 {len(html)/1024:.0f} KB)。")


if __name__ == "__main__":
    embed()
