#!/usr/bin/env python3
"""Marvis 网页信息搜索与监控"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import hashlib
from datetime import datetime

SNAPSHOT_DIR = os.path.join(os.path.expanduser("~"), ".marvis", "web_snapshots")


def ensure_snapshot_dir():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def fetch_page(url, timeout=15):
    """使用 PowerShell 抓取网页内容"""
    ps_script = f"""
try {{
    $resp = Invoke-WebRequest -Uri '{url}' -UseBasicParsing -TimeoutSec {timeout} -MaximumRedirection 5
    $resp.Content
}} catch {{
    Write-Error $_.Exception.Message
}}
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", encoding="utf-8-sig", delete=False) as f:
        f.write(ps_script)
        tmp = f.name
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp],
            capture_output=True, text=True, encoding="utf-8", timeout=timeout + 10
        )
        return result.stdout, result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "请求超时", 1
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def extract_text(html):
    """从 HTML 中提取纯文本"""
    # 移除 script/style
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 移除 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', html)
    # 清理空白
    text = re.sub(r'\s+', ' ', text).strip()
    # 解码常见 HTML 实体
    for entity, char in [('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), 
                         ('&quot;', '"'), ('&#39;', "'"), ('&nbsp;', ' ')]:
        text = text.replace(entity, char)
    return text


def extract_links(html, base_url=""):
    """从 HTML 中提取链接"""
    links = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
    result = []
    for link in links:
        if link.startswith('#') or link.startswith('javascript:') or link.startswith('mailto:'):
            continue
        if link.startswith('/') and base_url:
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            link = f"{parsed.scheme}://{parsed.netloc}{link}"
        result.append(link)
    return result[:50]


def extract_meta(html):
    """提取页面元信息"""
    title = ""
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()
    
    desc = ""
    desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']', html, re.IGNORECASE)
    if desc_match:
        desc = desc_match.group(1).strip()
    
    keywords = ""
    kw_match = re.search(r'<meta[^>]*name=["\']keywords["\'][^>]*content=["\']([^"\']*)["\']', html, re.IGNORECASE)
    if kw_match:
        keywords = kw_match.group(1).strip()
    
    return {"title": title, "description": desc, "keywords": keywords}


def search_web(query, count=10):
    """使用 Bing 搜索（无需 API key）"""
    from urllib.parse import quote_plus
    url = f"https://www.bing.com/search?q={quote_plus(query)}&count={count}"
    html, err, rc = fetch_page(url)
    if rc != 0 or not html:
        return {"error": f"搜索失败: {err}"}
    
    # 提取搜索结果
    results = []
    # Bing 搜索结果模式
    pattern = r'<li class="b_algo"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<p[^>]*>(.*?)</p>'
    for match in re.finditer(pattern, html, re.DOTALL | re.IGNORECASE):
        link = match.group(1)
        title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        snippet = re.sub(r'<[^>]+>', '', match.group(3)).strip()
        if title and link.startswith('http'):
            results.append({"title": title, "url": link, "snippet": snippet})
    
    return {"query": query, "results": results[:count]}


def monitor_page(url, keyword=None):
    """监控页面变化"""
    ensure_snapshot_dir()
    
    # 抓取当前内容
    html, err, rc = fetch_page(url)
    if rc != 0 or not html:
        return {"error": f"抓取失败: {err}"}
    
    text = extract_text(html)
    meta = extract_meta(html)
    current_hash = hashlib.md5(text.encode()).hexdigest()
    
    # 检查快照
    url_hash = hashlib.md5(url.encode()).hexdigest()
    snapshot_file = os.path.join(SNAPSHOT_DIR, f"{url_hash}.json")
    
    previous_hash = None
    changed = False
    keyword_found = False
    
    if os.path.isfile(snapshot_file):
        with open(snapshot_file, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        previous_hash = snapshot.get("hash")
        changed = current_hash != previous_hash
    
    # 保存当前快照
    snapshot = {
        "url": url,
        "hash": current_hash,
        "title": meta.get("title", ""),
        "checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "text_length": len(text),
    }
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    
    # 检查关键词
    if keyword:
        keyword_found = keyword.lower() in text.lower()
        keyword_context = []
        for i, line in enumerate(text.split('.')):
            if keyword.lower() in line.lower():
                keyword_context.append(line.strip()[:200])
    
    result = {
        "url": url,
        "title": meta.get("title", ""),
        "changed": changed,
        "previous_hash": previous_hash,
        "current_hash": current_hash,
        "text_preview": text[:500] if text else "",
        "keyword_found": keyword_found if keyword else None,
    }
    
    if keyword and keyword_found:
        result["keyword_context"] = keyword_context[:5]
    
    return result


def read_page(url, max_length=5000):
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


def main():
    parser = argparse.ArgumentParser(description="Marvis 网页信息搜索与监控")
    parser.add_argument("--action", choices=["search", "read", "monitor"], required=True, help="操作类型")
    parser.add_argument("--query", "-q", help="搜索关键词")
    parser.add_argument("--url", "-u", help="网页 URL")
    parser.add_argument("--keyword", "-k", help="监控关键词")
    parser.add_argument("--count", "-n", type=int, default=10, help="搜索结果数量")
    parser.add_argument("--max-length", type=int, default=5000, help="最大内容长度")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    args = parser.parse_args()

    if args.action == "search":
        if not args.query:
            print("错误: search 需要指定 --query", file=sys.stderr)
            sys.exit(1)
        result = search_web(args.query, args.count)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if "error" in result:
                print(f"搜索失败: {result['error']}")
            else:
                print(f"搜索: {result['query']}\n")
                for i, r in enumerate(result.get("results", []), 1):
                    print(f"  {i}. {r['title']}")
                    print(f"     {r['url']}")
                    print(f"     {r['snippet'][:100]}")
                    print()

    elif args.action == "read":
        if not args.url:
            print("错误: read 需要指定 --url", file=sys.stderr)
            sys.exit(1)
        result = read_page(args.url, args.max_length)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if "error" in result:
                print(f"读取失败: {result['error']}")
            else:
                print(f"标题: {result['title']}")
                print(f"描述: {result['description']}")
                print(f"链接数: {result['link_count']}")
                print(f"\n正文:\n{result['content']}")

    elif args.action == "monitor":
        if not args.url:
            print("错误: monitor 需要指定 --url", file=sys.stderr)
            sys.exit(1)
        result = monitor_page(args.url, args.keyword)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if "error" in result:
                print(f"监控失败: {result['error']}")
            else:
                print(f"URL: {result['url']}")
                print(f"标题: {result['title']}")
                print(f"内容变化: {'是 ⚠️' if result['changed'] else '否 ✅'}")
                if result['changed']:
                    print(f"  上次哈希: {result['previous_hash']}")
                    print(f"  当前哈希: {result['current_hash']}")
                if args.keyword:
                    print(f"关键词 '{args.keyword}': {'出现 ✅' if result['keyword_found'] else '未出现 ❌'}")
                    if result.get('keyword_context'):
                        for ctx in result['keyword_context']:
                            print(f"  上下文: {ctx}")


if __name__ == "__main__":
    main()