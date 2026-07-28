#!/usr/bin/env python3
"""lab retriever bridge:把 common.core 的 search+read_page 暴露为 HTTP 端点,
供 gpt-researcher 的 custom retriever 使用(RETRIEVER=custom)。

公平性关键件:arm G 由此与 B/F10 共用完全相同的搜索后端与抓取链
(serper/firecrawl/tavily 配额耗尽时自动 bing 兜底,行为一致)。
返回契约(gpt-researcher custom.py):[{"url": ..., "raw_content": ...}]
raw_content 直接给全文 → gptr 跳过自己的 scraper(researcher.py:852 只认
raw_content>100 才视为已抓取)。

用法: .venv 无关,用系统 python3 起:
  python3 common/lab_retriever_bridge.py --port 8377
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.core import read_page, search  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        q = parse_qs(urlparse(self.path).query).get("query", [""])[0]
        results = []
        if q:
            try:
                hits = search(q, n=6)
            except Exception as e:  # noqa: BLE001
                hits = []
                print(f"[bridge] search failed: {e}", flush=True)
            # 并发抓正文;失败/过短的丢弃(gptr 侧 >100 才收)
            def fetch(h):
                try:
                    body = read_page(h["url"], max_chars=8000)
                    return {"url": h["url"], "raw_content": body or ""}
                except Exception:  # noqa: BLE001
                    return {"url": h["url"], "raw_content": ""}
            with ThreadPoolExecutor(max_workers=6) as ex:
                results = [r for r in ex.map(fetch, hits)
                           if len(r["raw_content"]) > 100]
        body = json.dumps(results, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(f"[bridge] q={q[:50]!r} -> {len(results)} results", flush=True)

    def log_message(self, *a):  # 静默默认访问日志
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8377)
    args = ap.parse_args()
    print(f"[bridge] listening on :{args.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
