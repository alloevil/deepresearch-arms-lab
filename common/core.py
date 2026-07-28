"""公共模块：LLM 客户端 + 搜索 + 网页阅读 + 轨迹日志。

搜索后端可插拔：默认 bing（HTML 抓取，无 key），设 SERPER_API_KEY 后自动切换 serper。
所有函数都把调用记录写入 TraceLogger，供评测的过程指标（防线三）使用。
"""
import hashlib
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx

GATEWAY = os.environ["ANTHROPIC_BASE_URL"].rstrip("/")
API_KEY = os.environ["ANTHROPIC_AUTH_TOKEN"]

# 从项目 .env 加载搜索 key（不依赖 shell 环境）
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

MODEL_MAIN = os.environ.get("LAB_MODEL_MAIN", "claude-sonnet-5")
MODEL_FAST = os.environ.get("LAB_MODEL_FAST", "claude-haiku-4-5")


def _eval_channel() -> tuple[str, str]:
    """评测通道（裁判/fact 核验/污染 EAL）的网关与 key，与执行器解耦。

    动机（2026-07-17 实测）：执行器网关不一定提供 Claude → 裁判 opus 直接
    400；且核验器若与执行器同模型 = 自评闭环，客观轴失效。未设环境变量时回落
    执行器通道（历史行为不变）。运行时读 env，便于测试与批内切换审计。"""
    return ((os.environ.get("LAB_EVAL_BASE_URL") or GATEWAY).rstrip("/"),
            os.environ.get("LAB_EVAL_AUTH_TOKEN") or API_KEY)


def model_verify() -> str:
    """fact/污染核验模型：默认 MODEL_FAST；MiMo 批次须设 LAB_MODEL_VERIFY 指向
    评测通道可用的模型（如 claude-haiku-4-5），避免执行器自评。"""
    return os.environ.get("LAB_MODEL_VERIFY") or MODEL_FAST

# 评测防线一：搜索结果进入 context 前过滤 benchmark 托管站（STC 论文的 BML 运行时过滤）
BML_BLOCKLIST = re.compile(
    r"huggingface\.co|github\.com/.*(bench|eval|dataset)|paperswithcode|quizlet|"
    r"studocu|coursehero|chegg", re.I)


class TraceLogger:
    """每题一个 jsonl 文件，记录全部 LLM 调用与搜索/阅读事件。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self.tokens = {"in": 0, "out": 0}

    def log(self, kind: str, **kw):
        rec = {"t": round(time.time() - self.t0, 1), "kind": kind, **kw}
        with self.path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def chat(messages, model=MODEL_MAIN, max_tokens=4000, temperature=None,
         logger: TraceLogger | None = None, tag="", retries=3,
         base_url: str | None = None, api_key: str | None = None) -> str:
    """OpenAI 兼容的 chat completion，带重试与轨迹日志。

    temperature=None 时不传该参数（部分 Bedrock 新模型已弃用 temperature，传了会 400）。
    base_url/api_key 缺省走执行器网关；评测侧调用应经 chat_json_eval 走评测通道。
    """
    body = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if temperature is not None:
        body["temperature"] = temperature
    last_err = None
    for attempt in range(retries):
        try:
            r = httpx.post(f"{(base_url or GATEWAY)}/v1/chat/completions",
                           headers={"Authorization": f"Bearer {api_key or API_KEY}"},
                           json=body, timeout=300)
            d = r.json()
            if "choices" not in d:
                err = str(d)
                if "temperature" in err and "temperature" in body:
                    body.pop("temperature")  # 模型不支持则去掉后重试
                raise RuntimeError(err[:300])
            usage = d.get("usage", {})
            text = d["choices"][0]["message"]["content"]
            if not text:
                # 推理模型（如 MiMo）思考过长时 content 为 None，加预算重试
                body["max_tokens"] = min(body["max_tokens"] * 3, 16000)
                raise RuntimeError("empty content (reasoning consumed max_tokens)")
            if logger:
                logger.tokens["in"] += usage.get("prompt_tokens", 0)
                logger.tokens["out"] += usage.get("completion_tokens", 0)
                logger.log("llm", model=model, tag=tag,
                           tokens_in=usage.get("prompt_tokens"),
                           tokens_out=usage.get("completion_tokens"))
            return text
        except Exception as e:  # noqa: BLE001 — 网关 5xx/超时统一重试
            last_err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"chat failed after {retries} tries: {last_err}")


def chat_json(messages, schema_hint="", **kw) -> dict | list:
    """要求模型输出 JSON 并解析；失败时带错误信息重试一次。"""
    text = chat(messages, **kw)
    for candidate in _extract_json_candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    fix = messages + [
        {"role": "assistant", "content": text},
        {"role": "user", "content": f"上面的输出不是合法 JSON。只输出符合要求的 JSON{schema_hint}，不要任何其他文字。"}]
    text2 = chat(fix, **kw)
    for candidate in _extract_json_candidates(text2):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"JSON parse failed: {text2[:200]}")


def chat_json_eval(messages, **kw) -> dict | list:
    """评测通道版 chat_json（裁判/fact 核验/污染 EAL 专用）：网关与 key 走
    _eval_channel()，与执行器解耦。显式传入的 base_url/api_key 优先。"""
    gw, key = _eval_channel()
    kw.setdefault("base_url", gw)
    kw.setdefault("api_key", key)
    return chat_json(messages, **kw)


def _extract_json_candidates(text: str):
    fence = re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)
    yield from fence
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if m:
        yield m.group(0)
    # 截断修复：max_tokens 截断导致数组未闭合时，丢弃最后一个不完整元素再闭合
    start = text.find("[")
    if start >= 0:
        body = text[start:]
        last = body.rfind("},")
        if last > 0:
            yield body[:last + 1] + "]"


# ---------------- 搜索 ----------------

_search_zero_streak = 0        # 连续"所有后端都拿不到结果"的次数，fail-loud 保险丝
_SEARCH_ZERO_LIMIT = 6


def search(query: str, logger: TraceLogger | None = None, n=8) -> list[dict]:
    """返回 [{title, url, snippet}]。BML 过滤在此统一执行。

    结果级降级链：serper（Google，免费额度大）> firecrawl > tavily > bing 兜底。
    某后端异常或返回空结果时自动尝试下一个（Tavily 配额耗尽事故的教训：
    只按 key 是否存在选后端会静默产出空结果，污染整轮评测）。
    连续 _SEARCH_ZERO_LIMIT 次全链路为空则抛异常——宁可 run 失败也不污染数据。
    """
    global _search_zero_streak
    # 评测防线二：闭卷基线模式——禁检索跑同题，Δ(开卷−闭卷)=检索净增益
    # （LiveBrowseComp 参数化知识依赖诊断）。read_page 同样短路。
    if os.environ.get("LAB_CLOSED_BOOK"):
        if logger:
            logger.log("closed_book", query=query)
        return []
    chain = []
    if os.environ.get("SERPER_API_KEY"):
        chain.append(("serper", _search_serper))
    if os.environ.get("FIRECRAWL_API_KEY"):
        chain.append(("firecrawl", _search_firecrawl))
    if os.environ.get("TAVILY_API_KEY"):
        chain.append(("tavily", _search_tavily))
    chain.append(("bing", _search_bing))

    backend, results, errors = None, [], []
    for name, fn in chain:
        try:
            results = fn(query, n)
        except Exception as e:  # noqa: BLE001 — 单后端故障降级到下一个
            errors.append(f"{name}: {str(e)[:120]}")
            continue
        if results:
            backend = name
            break
        errors.append(f"{name}: empty")

    if results:
        _search_zero_streak = 0
    else:
        _search_zero_streak += 1
        if _search_zero_streak >= _SEARCH_ZERO_LIMIT:
            raise RuntimeError(
                f"search infrastructure down: {_search_zero_streak} consecutive "
                f"all-backend failures. last errors: {errors}")

    kept = [r for r in results if not BML_BLOCKLIST.search(r["url"])]
    if logger:
        logger.log("search", backend=backend or "none", query=query,
                   n_raw=len(results), n_kept=len(kept),
                   urls=[r["url"] for r in kept],
                   **({"errors": errors} if errors else {}))
    return kept


def _search_firecrawl(query: str, n: int) -> list[dict]:
    r = httpx.post("https://api.firecrawl.dev/v2/search",
                   headers={"Authorization": f"Bearer {os.environ['FIRECRAWL_API_KEY']}"},
                   json={"query": query, "limit": n}, timeout=30)
    d = r.json()
    if not d.get("success", False):
        raise RuntimeError(f"firecrawl error: {str(d)[:200]}")
    return [{"title": o.get("title", ""), "url": o.get("url", ""),
             "snippet": (o.get("description") or o.get("markdown") or "")[:300]}
            for o in d.get("data", {}).get("web", [])][:n]


def _search_tavily(query: str, n: int) -> list[dict]:
    r = httpx.post("https://api.tavily.com/search",
                   json={"api_key": os.environ["TAVILY_API_KEY"], "query": query,
                         "max_results": n, "search_depth": "basic",
                         "include_raw_content": False}, timeout=30)
    d = r.json()
    if "results" not in d:   # 配额耗尽等错误响应没有 results 字段，必须显式报错
        raise RuntimeError(f"tavily error: {str(d)[:200]}")
    return [{"title": o.get("title", ""), "url": o.get("url", ""),
             "snippet": o.get("content", "")[:300]}
            for o in d["results"]][:n]


def _search_serper(query: str, n: int) -> list[dict]:
    r = httpx.post("https://google.serper.dev/search",
                   headers={"X-API-KEY": os.environ["SERPER_API_KEY"]},
                   json={"q": query, "num": n, "hl": "zh-cn"}, timeout=30)
    d = r.json()
    if "organic" not in d:   # 配额/鉴权错误没有 organic 字段，显式报错触发降级
        raise RuntimeError(f"serper error: {str(d)[:200]}")
    return [{"title": o.get("title", ""), "url": o.get("link", ""),
             "snippet": o.get("snippet", "")} for o in d["organic"]][:n]


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _search_bing(query: str, n: int) -> list[dict]:
    from bs4 import BeautifulSoup
    r = httpx.get("https://www.bing.com/search",
                  params={"q": query, "count": n, "mkt": "zh-CN"},
                  headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
                  timeout=30, follow_redirects=True)
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for li in soup.select("li.b_algo")[:n]:
        h = li.select_one("h2 a")
        p = li.select_one(".b_caption p, p")
        if h and h.get("href", "").startswith("http"):
            out.append({"title": h.get_text(strip=True),
                        "url": h["href"],
                        "snippet": p.get_text(strip=True) if p else ""})
    return out


# ---------------- 网页阅读 ----------------

_page_cache: dict[str, str] = {}
LAST_READ_VIA = "httpx"   # 最近一次 read_page 的抓取方式，供 search_cli 审计日志


def _browser_render_text(url: str) -> str:
    """browser-use CLI 渲染页面后抽正文，处理 JS 渲染页（httpx 拿不到内容的场景）。

    需要环境变量 BU_CDP_URL 指向一个开着 CDP 的浏览器
    （如 google-chrome --headless=new --remote-debugging-port=9222）。
    未配置或失败时返回空串，调用方按普通抓取失败处理。
    """
    import shutil
    import subprocess
    if not (os.environ.get("BU_CDP_URL") and shutil.which("browser-use")):
        return ""
    script = (f"new_tab({url!r})\nwait(2.5)\n"
              'print(js("document.documentElement.outerHTML"))\nclose_tab()\n')
    try:
        p = subprocess.run(["browser-use"], input=script, capture_output=True,
                           text=True, timeout=90)
        html_text = p.stdout
        if len(html_text) < 500:
            return ""
        import trafilatura
        return trafilatura.extract(html_text) or ""
    except Exception:  # noqa: BLE001 — 渲染降级失败不应中断研究流程
        return ""


def read_page(url: str, logger: TraceLogger | None = None, max_chars=6000) -> str:
    """抓取网页正文（trafilatura 抽取），带内存缓存。失败返回空串。

    降级链：httpx 静态抓取 → browser-use 渲染（JS 页面）。"""
    if os.environ.get("LAB_CLOSED_BOOK"):  # 闭卷基线：禁绕过 search 直读 URL
        if logger:
            logger.log("closed_book", url=url)
        return ""
    key = hashlib.md5(url.encode()).hexdigest()
    if key in _page_cache:
        return _page_cache[key][:max_chars]
    text, via = "", "httpx"
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=25,
                      follow_redirects=True)
        import trafilatura
        text = trafilatura.extract(r.text) or ""
    except Exception:  # noqa: BLE001 — 单页失败不应中断研究流程
        pass
    if len(text) < 200:   # 静态抓取拿不到正文（JS 渲染/反爬）→ 浏览器渲染兜底
        btext = _browser_render_text(url)
        if len(btext) > len(text):
            text, via = btext, "browser"
    global LAST_READ_VIA
    LAST_READ_VIA = via
    _page_cache[key] = text
    if logger:
        logger.log("read", url=url, chars=len(text), via=via)
    return text[:max_chars]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
