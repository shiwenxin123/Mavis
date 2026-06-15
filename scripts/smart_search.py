#!/usr/bin/env python3
"""Marvis 智能文件搜索 - 按语义/内容/元数据搜索本地文件"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


def search_by_name(root, pattern, ext=None):
    """按文件名模式搜索"""
    results = []
    regex = re.compile(re.escape(pattern), re.IGNORECASE)
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if regex.search(f):
                if ext and not f.lower().endswith(ext.lower()):
                    continue
                full = os.path.join(dirpath, f)
                results.append(file_info(full))
    return results


def search_by_content(root, keyword, ext=None, max_size_mb=10, encoding='utf-8'):
    """按文件内容搜索关键词"""
    results = []
    max_bytes = max_size_mb * 1024 * 1024
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
                if size > max_bytes or size == 0:
                    continue
                with open(full, 'r', encoding=encoding, errors='ignore') as fh:
                    for i, line in enumerate(fh, 1):
                        if keyword.lower() in line.lower():
                            results.append({
                                **file_info(full),
                                'match_line': i,
                                'match_text': line.strip()[:200]
                            })
                            break
            except (PermissionError, OSError):
                continue
    return results


def search_by_size(root, min_mb=0, max_mb=0, ext=None):
    """按文件大小搜索"""
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
                size_mb = size / (1024 * 1024)
                if min_mb and size_mb < min_mb:
                    continue
                if max_mb and size_mb > max_mb:
                    continue
                results.append(file_info(full))
            except (PermissionError, OSError):
                continue
    return results


def search_by_time(root, days=None, after=None, before=None, ext=None):
    """按修改时间搜索"""
    results = []
    now = datetime.now()
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(full))
                if days and (now - mtime).days > days:
                    continue
                if after:
                    after_dt = datetime.strptime(after, '%Y-%m-%d')
                    if mtime < after_dt:
                        continue
                if before:
                    before_dt = datetime.strptime(before, '%Y-%m-%d')
                    if mtime > before_dt:
                        continue
                results.append(file_info(full))
            except (PermissionError, OSError):
                continue
    return results


def search_by_regex_content(root, pattern, ext=None, max_size_mb=10):
    """按正则表达式搜索文件内容"""
    results = []
    max_bytes = max_size_mb * 1024 * 1024
    regex = re.compile(pattern, re.IGNORECASE)
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            if ext and not f.lower().endswith(ext.lower()):
                continue
            full = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(full)
                if size > max_bytes or size == 0:
                    continue
                with open(full, 'r', encoding='utf-8', errors='ignore') as fh:
                    for i, line in enumerate(fh, 1):
                        if regex.search(line):
                            results.append({
                                **file_info(full),
                                'match_line': i,
                                'match_text': line.strip()[:200]
                            })
                            break
            except (PermissionError, OSError):
                continue
    return results


def file_info(path):
    """获取文件基本信息"""
    try:
        stat = os.stat(path)
        return {
            'path': os.path.abspath(path),
            'name': os.path.basename(path),
            'ext': os.path.splitext(path)[1].lower(),
            'size_bytes': stat.st_size,
            'size_readable': format_size(stat.st_size),
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
        }
    except (PermissionError, OSError) as e:
        return {'path': os.path.abspath(path), 'error': str(e)}


def format_size(size_bytes):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.idea', '.vs', '.BIN', 'System Volume Information'}

def should_skip(dirpath):
    """判断是否跳过目录"""
    return any(skip in dirpath for skip in SKIP_DIRS)


def main():
    parser = argparse.ArgumentParser(description='Marvis 智能文件搜索')
    parser.add_argument('root', help='搜索根目录')
    parser.add_argument('--mode', choices=['name', 'content', 'size', 'time', 'regex'], default='name', help='搜索模式')
    parser.add_argument('--keyword', '-k', help='搜索关键词')
    parser.add_argument('--pattern', '-p', help='正则表达式模式')
    parser.add_argument('--ext', '-e', help='文件扩展名过滤 (如 .pdf, .docx)')
    parser.add_argument('--min-size', type=float, help='最小文件大小 (MB)')
    parser.add_argument('--max-size', type=float, help='最大文件大小 (MB)')
    parser.add_argument('--days', type=int, help='最近 N 天内修改的文件')
    parser.add_argument('--after', help='修改日期晚于此日期 (YYYY-MM-DD)')
    parser.add_argument('--before', help='修改日期早于此日期 (YYYY-MM-DD)')
    parser.add_argument('--limit', type=int, default=50, help='最大结果数')
    parser.add_argument('--json', action='store_true', help='JSON 格式输出')

    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print(f"错误: 目录不存在 - {args.root}", file=sys.stderr)
        sys.exit(1)

    if args.mode == 'name':
        if not args.keyword:
            print("错误: name 模式需要 --keyword", file=sys.stderr)
            sys.exit(1)
        results = search_by_name(args.root, args.keyword, args.ext)
    elif args.mode == 'content':
        if not args.keyword:
            print("错误: content 模式需要 --keyword", file=sys.stderr)
            sys.exit(1)
        results = search_by_content(args.root, args.keyword, args.ext)
    elif args.mode == 'size':
        results = search_by_size(args.root, args.min_size or 0, args.max_size or 0, args.ext)
    elif args.mode == 'time':
        results = search_by_time(args.root, args.days, args.after, args.before, args.ext)
    elif args.mode == 'regex':
        if not args.pattern:
            print("错误: regex 模式需要 --pattern", file=sys.stderr)
            sys.exit(1)
        results = search_by_regex_content(args.root, args.pattern, args.ext)
    else:
        results = []

    results = results[:args.limit]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        if not results:
            print("未找到匹配文件。")
            return
        print(f"找到 {len(results)} 个文件:\n")
        for r in results:
            print(f"  {r['path']}")
            print(f"    大小: {r.get('size_readable', 'N/A')}  修改: {r.get('modified', 'N/A')}")
            if 'match_text' in r:
                print(f"    匹配 (行{r['match_line']}): {r['match_text']}")
            print()


if __name__ == '__main__':
    main()
