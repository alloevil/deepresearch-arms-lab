#!/usr/bin/env python3
"""发布前脱敏扫描:对暂存目录做字面检查,报告任何残留的内部基建字符串。

这不是自动替换脚本(措辞类改写需要人工判断怎么改才通顺),而是发布前的
硬门槛检查——CI/发布脚本可以直接调用,非零退出码=不能发布。

用法: python3 scripts/sanitize_for_publish.py <暂存目录>
"""
import re
import sys
from pathlib import Path

BANNED_PATTERNS = [
    re.compile(r"mify", re.IGNORECASE),
    re.compile(r"mimorouter", re.IGNORECASE),
    re.compile(r"model\.mify\.ai\.srv"),
    re.compile(r"mimorouter\.llmcore\.ai\.srv"),
]
TEXT_EXTS = {".py", ".md", ".sh", ".html", ".json", ".txt", ".yml", ".yaml"}
SKIP_DIRS = {".git", "__pycache__", "node_modules"}


def scan(root: Path) -> list[tuple[Path, int, str]]:
    self_path = Path(__file__).resolve()
    hits = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_EXTS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.resolve() == self_path:
            continue  # 本文件自身按定义就含有这些字符串,不算残留
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in BANNED_PATTERNS:
                if pat.search(line):
                    hits.append((path.relative_to(root), lineno, line.strip()[:120]))
                    break
    return hits


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"用法: {sys.argv[0]} <暂存目录>")
        sys.exit(2)
    root = Path(sys.argv[1]).resolve()
    hits = scan(root)
    if not hits:
        print(f"OK: {root} 未发现内部基建字符串残留。")
        sys.exit(0)
    print(f"发现 {len(hits)} 处残留,发布前必须清理:")
    for path, lineno, line in hits:
        print(f"  {path}:{lineno}: {line}")
    sys.exit(1)
