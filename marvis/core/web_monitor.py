"""
Marvis 网页信息搜索与监控 — 网页抓取、内容提取、变化监控。

可导入使用：
    from marvis.core.web_monitor import fetch_page, search_web, read_page, monitor_page
"""

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus, urlparse

_MAX_BYTES = 2_000_000
_UA = "Marvis/2.1"


def _snapshot_dir() -> str:
    from marvis.utils.config import marvis_home
    return str(marvis_home() / "web_snapshots")


def ensure_snapshot_dir():
    os.makedirs(_snapshot_dir(), exist_ok=True)


def http_get(url: str, timeout: int = 15, read_limit: int = _MAX_BYTES) -> tuple[str, str, int]:
    """抓取 URL。返回 (body, error, status)。status 为 0 表示请求未发出。"""
    from marvis.utils.config import network_allowed

    allowed, reason = network_allowed()
    if not allowed:
        return "", reason, 0

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "", "仅允许 http/https URL", 0

    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200) or 200)
            raw = response.read(read_limit) if read_limit else b""
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), "", status
    except urllib.error.HTTPError as exc:
        return "", f"HTTP {exc.code}", int(exc.code)
    except Exception as exc:
        return "", f"抓取失败: {exc}", 0


def fetch_page(url: str, timeout: int = 15) -> tuple[str, str, int]:
    """抓取网页 HTML，返回 (html, error, returncode)"""
    body, err, status = http_get(url, timeout=timeout)
    if err or status == 0:
        return "", err or "抓取失败", 1
    if status >= 400:
        return body, f"HTTP {status}", 1
    return body, "", 0


def extract_text(html: str) -> str:
    """从 HTML 中提取纯文本"""
    # 移除 script/style
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 移除 HTML 标签
    text = re.sub(r"<[^>]+>", " ", html)
    # 清理空白
    text = re.sub(r"\s+", " ", text).strip()
    # 解码 HTML 实体
    entities = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&nbsp;": " "}
    for entity, char in entities.items():
        text = text.replace(entity, char)
    return text


def extract_links(html: str, base_url: str = "") -> list[str]:
    """从 HTML 中提取链接"""
    links = re.findall(r"""href=["']([^"']+)["']""", html, re.IGNORECASE)
    result = []
    for link in links:
        if link.startswith(("#", "javascript:", "mailto:")):
            continue
        if link.startswith("/") and base_url:
            parsed = urlparse(base_url)
            link = f"{parsed.scheme}://{parsed.netloc}{link}"
        result.append(link)
    return result[:50]


def extract_meta(html: str) -> dict:
    """提取页面元信息"""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = m.group(1).strip()

    desc = ""
    m = re.search(r"""<meta[^>]*name=["']description["'][^>]*content=["']([^"']*)["']""", html, re.IGNORECASE)
    if m:
        desc = m.group(1).strip()

    keywords = ""
    m = re.search(r"""<meta[^>]*name=["']keywords["'][^>]*content=["']([^"']*)["']""", html, re.IGNORECASE)
    if m:
        keywords = m.group(1).strip()

    return {"title": title, "description": desc, "keywords": keywords}


def search_web(query: str, count: int = 10) -> dict:
    """使用 Bing 搜索（无需 API Key）"""
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={count}"
    html, err, rc = fetch_page(url)
    if rc != 0 or not html:
        return {"error": f"搜索失败: {err}"}

    results = []
    pattern = r'<li class="b_algo"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<p[^>]*>(.*?)</p>'
    for match in re.finditer(pattern, html, re.DOTALL | re.IGNORECASE):
        link = match.group(1)
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        snippet = re.sub(r"<[^>]+>", "", match.group(3)).strip()
        if title and link.startswith("http"):
            results.append({"title": title, "url": link, "snippet": snippet})

    return {"query": query, "results": results[:count]}


def monitor_page(url: str, keyword: Optional[str] = None) -> dict:
    """监控页面变化，可选关键词检测"""
    ensure_snapshot_dir()

    html, err, rc = fetch_page(url)
    if rc != 0 or not html:
        return {"error": f"抓取失败: {err}"}

    text = extract_text(html)
    meta = extract_meta(html)
    current_hash = hashlib.md5(text.encode()).hexdigest()

    url_hash = hashlib.md5(url.encode()).hexdigest()
    snapshot_file = os.path.join(_snapshot_dir(), f"{url_hash}.json")

    previous_hash = None
    changed = False

    if os.path.isfile(snapshot_file):
        with open(snapshot_file, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        previous_hash = snapshot.get("hash")
        changed = current_hash != previous_hash

    snapshot = {
        "url": url,
        "hash": current_hash,
        "title": meta.get("title", ""),
        "checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "text_length": len(text),
    }
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    result: dict = {
        "url": url,
        "title": meta.get("title", ""),
        "changed": changed,
        "previous_hash": previous_hash,
        "current_hash": current_hash,
        "text_preview": text[:500] if text else "",
    }

    if keyword:
        kw_lower = keyword.lower()
        found = kw_lower in text.lower()
        result["keyword_found"] = found
        if found:
            contexts = [
                line.strip()[:200] for line in text.split(".")
                if kw_lower in line.lower()
            ]
            result["keyword_context"] = contexts[:5]

    return result


def read_page(url: str, max_length: int = 5000) -> dict:
    """读取网页正文内容"""
    html, err, rc = fetch_page(url)
    if rc != 0 or not html:
        return {"error": f"抓取失败: {err}"}

    text = extract_text(html)
    meta = extract_meta(html)
    links = extract_links(html, url)

    return {
        "url": url,
        "title": meta.get("title", ""),
        "description": meta.get("description", ""),
        "content": text[:max_length],
        "content_length": len(text),
        "link_count": len(links),
        "links_sample": links[:10],
    }
