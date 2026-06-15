#!/usr/bin/env python3
"""Marvis 文件智能整理 - 归类、重命名、去重、清理"""

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

TYPE_MAP = {
    '文档': {'.pdf', '.doc', '.docx', '.txt', '.md', '.rtf', '.odt', '.wps', '.ppt', '.pptx'},
    '表格': {'.xls', '.xlsx', '.csv', '.ods'},
    '图片': {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.webp', '.ico', '.tiff'},
    '视频': {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'},
    '音频': {'.mp3', '.wav', '.flac', '.aac', '.ogg', '.wma', '.m4a'},
    '代码': {'.py', '.js', '.ts', '.java', '.c', '.cpp', '.h', '.go', '.rs', '.rb', '.php', '.sh', '.ps1', '.html', '.css', '.json', '.yaml', '.yml', '.xml', '.sql'},
    '压缩包': {'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2'},
    '可执行': {'.exe', '.msi', '.dmg', '.deb', '.rpm', '.apk'},
}

SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.idea', '.vs', '.BIN', 'System Volume Information'}

EXT_TEMP = {'.tmp', '.temp', '.log', '.cache', '.bak', '.old', '.swp'}
EXT_CACHE_DIRS = {'__pycache__', '.cache', 'node_modules', '.tmp'}


def get_category(ext):
    """根据扩展名获取文件类别"""
    ext = ext.lower()
    for cat, exts in TYPE_MAP.items():
        if ext in exts:
            return cat
    return '其他'


def scan_files(root, max_depth=None):
    """扫描目录下所有文件"""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 跳过系统目录
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        
        rel_depth = os.path.relpath(dirpath, root).count(os.sep)
        if max_depth and rel_depth >= max_depth:
            dirnames.clear()
            continue

        for f in filenames:
            full = os.path.join(dirpath, f)
            try:
                stat = os.stat(full)
                ext = os.path.splitext(f)[1].lower()
                files.append({
                    'path': os.path.abspath(full),
                    'name': f,
                    'ext': ext,
                    'category': get_category(ext),
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                })
            except (PermissionError, OSError):
                continue
    return files


def analyze_structure(files):
    """分析文件结构，生成统计"""
    stats = defaultdict(lambda: {'count': 0, 'size': 0, 'exts': defaultdict(int)})
    for f in files:
        cat = f['category']
        stats[cat]['count'] += 1
        stats[cat]['size'] += f['size']
        stats[cat]['exts'][f['ext']] += 1
    return dict(stats)


def generate_organize_plan(files, target_dir, mode='type'):
    """生成整理计划（预览，不实际执行）"""
    plan = []
    for f in files:
        if mode == 'type':
            dest_dir = os.path.join(target_dir, f['category'])
        elif mode == 'time':
            mtime = datetime.strptime(f['modified'], '%Y-%m-%d %H:%M:%S')
            dest_dir = os.path.join(target_dir, str(mtime.year), f'{mtime.month:02d}')
        else:
            dest_dir = target_dir

        dest = os.path.join(dest_dir, f['name'])
        if os.path.abspath(f['path']) != os.path.abspath(dest):
            plan.append({
                'source': f['path'],
                'destination': dest,
                'category': f['category'],
            })
    return plan


def find_duplicates(files):
    """基于文件大小+哈希检测重复文件"""
    size_groups = defaultdict(list)
    for f in files:
        size_groups[f['size']].append(f)

    duplicates = []
    for size, group in size_groups.items():
        if len(group) < 2 or size == 0:
            continue
        hash_groups = defaultdict(list)
        for f in group:
            try:
                with open(f['path'], 'rb') as fh:
                    h = hashlib.md5(fh.read()).hexdigest()
                hash_groups[h].append(f)
            except (PermissionError, OSError):
                continue
        for h, hgroup in hash_groups.items():
            if len(hgroup) > 1:
                duplicates.append({
                    'hash': h,
                    'size': format_size(size),
                    'files': [f['path'] for f in hgroup]
                })
    return duplicates


def find_temp_files(files):
    """查找临时/缓存文件"""
    temp = []
    for f in files:
        if f['ext'] in EXT_TEMP:
            temp.append(f)
    return temp


def find_empty_dirs(root):
    """查找空目录"""
    empty = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        if not dirnames and not filenames:
            rel = os.path.relpath(dirpath, root)
            if rel == '.':
                continue
            if any(skip in dirpath for skip in SKIP_DIRS):
                continue
            empty.append(dirpath)
    return empty


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def main():
    parser = argparse.ArgumentParser(description='Marvis 文件智能整理')
    parser.add_argument('root', help='扫描根目录')
    parser.add_argument('--action', choices=['analyze', 'organize', 'duplicates', 'temp', 'empty-dirs'], default='analyze', help='操作类型')
    parser.add_argument('--mode', choices=['type', 'time'], default='type', help='整理模式')
    parser.add_argument('--target', '-t', help='整理目标目录')
    parser.add_argument('--max-depth', type=int, help='最大扫描深度')
    parser.add_argument('--json', action='store_true', help='JSON 格式输出')

    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print(f"错误: 目录不存在 - {args.root}", file=sys.stderr)
        sys.exit(1)

    files = scan_files(args.root, args.max_depth)

    if args.action == 'analyze':
        stats = analyze_structure(files)
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2, default=str))
        else:
            total_size = sum(f['size'] for f in files)
            print(f"目录分析: {args.root}")
            print(f"文件总数: {len(files)}, 总大小: {format_size(total_size)}\n")
            for cat, info in sorted(stats.items(), key=lambda x: -x[1]['size']):
                ext_list = ', '.join(f"{ext}({cnt})" for ext, cnt in sorted(info['exts'].items(), key=lambda x: -x[1]))
                print(f"  [{cat}] {info['count']} 个文件, {format_size(info['size'])}")
                print(f"    扩展名: {ext_list}")
            print()

    elif args.action == 'organize':
        if not args.target:
            print("错误: organize 需要指定 --target 目标目录", file=sys.stderr)
            sys.exit(1)
        plan = generate_organize_plan(files, args.target, args.mode)
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(f"整理计划 ({args.mode} 模式): {len(plan)} 个文件需要移动\n")
            for item in plan[:30]:
                print(f"  {item['source']}")
                print(f"    → {item['destination']} [{item['category']}]")
            if len(plan) > 30:
                print(f"  ... 还有 {len(plan) - 30} 个文件")
            print(f"\n⚠️ 以上为预览，未实际执行。确认后使用 --execute 参数执行。")

    elif args.action == 'duplicates':
        dups = find_duplicates(files)
        if args.json:
            print(json.dumps(dups, ensure_ascii=False, indent=2))
        else:
            if not dups:
                print("未发现重复文件。")
            else:
                wasted = sum(
                    os.path.getsize(d['files'][0]) * (len(d['files']) - 1)
                    for d in dups if os.path.exists(d['files'][0])
                )
                print(f"发现 {len(dups)} 组重复文件, 浪费空间: {format_size(wasted)}\n")
                for d in dups:
                    print(f"  [{d['hash'][:8]}] {d['size']}")
                    for f in d['files']:
                        print(f"    {f}")
                    print()

    elif args.action == 'temp':
        temp = find_temp_files(files)
        if args.json:
            print(json.dumps(temp, ensure_ascii=False, indent=2))
        else:
            if not temp:
                print("未发现临时文件。")
            else:
                total = sum(f['size'] for f in temp)
                print(f"发现 {len(temp)} 个临时/缓存文件, 占用: {format_size(total)}\n")
                for f in temp[:20]:
                    print(f"  {f['path']} ({format_size(f['size'])})")
                if len(temp) > 20:
                    print(f"  ... 还有 {len(temp) - 20} 个文件")

    elif args.action == 'empty-dirs':
        empty = find_empty_dirs(args.root)
        if args.json:
            print(json.dumps(empty, ensure_ascii=False, indent=2))
        else:
            if not empty:
                print("未发现空目录。")
            else:
                print(f"发现 {len(empty)} 个空目录:\n")
                for d in empty[:30]:
                    print(f"  {d}")


if __name__ == '__main__':
    main()
