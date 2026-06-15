#!/usr/bin/env python3
"""Marvis 项目感知分析 - 扫描项目结构、识别技术栈、生成报告"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime


SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.idea', '.vs',
             '$RECYCLE.BIN', 'dist', 'build', '.next', '.nuxt', 'target', '.tox',
             'vendor', 'Pods', '.gradle', '.mvn', 'bin', 'obj', 'Debug', 'Release'}

TECH_MARKERS = {
    'package.json': {'lang': 'JavaScript/TypeScript', 'type': '前端'},
    'tsconfig.json': {'lang': 'TypeScript', 'type': '前端'},
    'vue.config.js': {'lang': 'Vue', 'type': '前端'},
    'next.config.js': {'lang': 'Next.js', 'type': '前端'},
    'nuxt.config.js': {'lang': 'Nuxt.js', 'type': '前端'},
    'vite.config.ts': {'lang': 'Vite', 'type': '前端'},
    'webpack.config.js': {'lang': 'Webpack', 'type': '前端'},
    'tailwind.config.js': {'lang': 'Tailwind CSS', 'type': '前端'},
    'requirements.txt': {'lang': 'Python', 'type': '后端'},
    'setup.py': {'lang': 'Python', 'type': '后端'},
    'pyproject.toml': {'lang': 'Python', 'type': '后端'},
    'Pipfile': {'lang': 'Python', 'type': '后端'},
    'manage.py': {'lang': 'Django', 'type': '后端'},
    'go.mod': {'lang': 'Go', 'type': '后端'},
    'Cargo.toml': {'lang': 'Rust', 'type': '后端'},
    'pom.xml': {'lang': 'Java/Maven', 'type': '后端'},
    'build.gradle': {'lang': 'Java/Gradle', 'type': '后端'},
    'docker-compose.yml': {'lang': 'Docker', 'type': '基础设施'},
    'Dockerfile': {'lang': 'Docker', 'type': '基础设施'},
    'Jenkinsfile': {'lang': 'Jenkins', 'type': 'CI/CD'},
    '.gitlab-ci.yml': {'lang': 'GitLab CI', 'type': 'CI/CD'},
}

LANG_EXTENSIONS = {
    '.py': 'Python', '.js': 'JavaScript', '.ts': 'TypeScript', '.jsx': 'JSX',
    '.tsx': 'TSX', '.vue': 'Vue', '.svelte': 'Svelte', '.go': 'Go', '.rs': 'Rust',
    '.java': 'Java', '.kt': 'Kotlin', '.c': 'C', '.cpp': 'C++', '.h': 'C/C++ Header',
    '.cs': 'C#', '.rb': 'Ruby', '.php': 'PHP', '.swift': 'Swift', '.sh': 'Shell',
    '.ps1': 'PowerShell', '.sql': 'SQL', '.r': 'R', '.scala': 'Scala',
    '.html': 'HTML', '.css': 'CSS', '.scss': 'SCSS', '.less': 'Less',
}


def scan_project(root, max_depth=5):
    result = {
        "root": os.path.abspath(root),
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tech_stack": [],
        "languages": defaultdict(int),
        "file_stats": defaultdict(int),
        "total_files": 0,
        "total_size": 0,
        "entry_points": [],
        "config_files": [],
        "dependencies": {},
        "suggestions": [],
    }

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
        rel_depth = os.path.relpath(dirpath, root).count(os.sep)
        if rel_depth >= max_depth:
            dirnames.clear()
            continue

        for f in filenames:
            full = os.path.join(dirpath, f)
            try:
                stat = os.stat(full)
                ext = os.path.splitext(f)[1].lower()
                rel_path = os.path.relpath(full, root)
                result["total_files"] += 1
                result["total_size"] += stat.st_size
                if ext in LANG_EXTENSIONS:
                    result["languages"][LANG_EXTENSIONS[ext]] += 1
                result["file_stats"][ext if ext else "无扩展名"] += 1
                if f in ('main.py', 'app.py', 'index.js', 'index.ts', 'main.go',
                         'main.rs', 'manage.py', 'server.py', '__main__.py'):
                    result["entry_points"].append(rel_path)
                if f.startswith('.') or f in ('tsconfig.json', 'Makefile', 'Dockerfile'):
                    result["config_files"].append(rel_path)
                if f in TECH_MARKERS and TECH_MARKERS[f]:
                    marker = TECH_MARKERS[f]
                    if marker not in result["tech_stack"]:
                        result["tech_stack"].append(marker)
            except (PermissionError, OSError):
                continue

    result["dependencies"] = parse_dependencies(root)
    result["suggestions"] = generate_suggestions(result)
    return result


def parse_dependencies(root):
    deps = {}
    pkg_json = os.path.join(root, 'package.json')
    if os.path.isfile(pkg_json):
        try:
            with open(pkg_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
            npm_deps = list((data.get('dependencies') or {}).keys())
            dev_deps = list((data.get('devDependencies') or {}).keys())
            deps['npm'] = {'production': npm_deps[:30], 'dev': dev_deps[:20]}
        except (json.JSONDecodeError, OSError):
            pass
    req_txt = os.path.join(root, 'requirements.txt')
    if os.path.isfile(req_txt):
        try:
            with open(req_txt, 'r', encoding='utf-8') as f:
                lines = [l.strip().split('==')[0].split('>=')[0].split('~=')[0]
                         for l in f if l.strip() and not l.startswith('#')]
            deps['pip'] = lines[:50]
        except OSError:
            pass
    go_mod = os.path.join(root, 'go.mod')
    if os.path.isfile(go_mod):
        try:
            with open(go_mod, 'r', encoding='utf-8') as f:
                lines = [l.strip().split()[0] for l in f
                         if l.strip() and not l.startswith(('module', 'go ', '//'))]
            deps['go'] = lines[:30]
        except OSError:
            pass
    return deps


def generate_suggestions(result):
    suggestions = []
    gitignore = os.path.join(result["root"], '.gitignore')
    if not os.path.isfile(gitignore) and result["total_files"] > 5:
        suggestions.append({"type": "配置缺失", "message": "缺少 .gitignore 文件", "priority": "中"})
    readme = None
    for name in ('README.md', 'README.txt', 'readme.md'):
        if os.path.isfile(os.path.join(result["root"], name)):
            readme = name
            break
    if not readme and result["total_files"] > 3:
        suggestions.append({"type": "文档缺失", "message": "缺少 README 文件", "priority": "中"})
    if not result["entry_points"]:
        suggestions.append({"type": "入口不明", "message": "未检测到标准入口文件", "priority": "低"})
    return suggestions


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def generate_readme(result):
    lines = [f"# {os.path.basename(result['root'])}\n"]
    if result["tech_stack"]:
        lines.append("## 技术栈\n")
        for ts in result["tech_stack"]:
            lines.append(f"- {ts['lang']} ({ts['type']})")
        lines.append("")
    if result["languages"]:
        lines.append("## 语言分布\n")
        for lang, count in sorted(result["languages"].items(), key=lambda x: -x[1]):
            lines.append(f"- {lang}: {count} 个文件")
        lines.append("")
    if result["entry_points"]:
        lines.append("## 入口文件\n")
        for ep in result["entry_points"]:
            lines.append(f"- `{ep}`")
        lines.append("")
    if result["dependencies"]:
        lines.append("## 依赖\n")
        for mgr, deps in result["dependencies"].items():
            lines.append(f"### {mgr}\n")
            dep_list = deps.get('production', deps) if isinstance(deps, dict) else deps
            for d in (dep_list[:20] if isinstance(dep_list, list) else []):
                lines.append(f"- {d}")
            lines.append("")
    lines.append("## 快速开始\n```bash\n# TODO: 添加启动命令\n```\n")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description="Marvis 项目感知分析")
    parser.add_argument("root", help="项目根目录")
    parser.add_argument("--action", choices=["scan", "readme", "deps"], default="scan")
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not os.path.isdir(args.root):
        print(f"错误: 目录不存在 - {args.root}", file=sys.stderr)
        sys.exit(1)

    result = scan_project(args.root, args.max_depth)

    if args.action == "readme":
        print(generate_readme(result))
    elif args.action == "deps":
        deps = result.get("dependencies", {})
        if args.json:
            print(json.dumps(deps, ensure_ascii=False, indent=2))
        else:
            for mgr, dep_list in deps.items():
                print(f"\n[{mgr}]")
                if isinstance(dep_list, dict):
                    for section, items in dep_list.items():
                        if items:
                            print(f"  {section}:")
                            for d in items:
                                print(f"    - {d}")
                else:
                    for d in dep_list:
                        print(f"  - {d}")
    else:
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            print(f"📂 项目: {result['root']}")
            print(f"📊 文件: {result['total_files']} 个, 总大小: {format_size(result['total_size'])}\n")
            if result["tech_stack"]:
                print("🔧 技术栈:")
                for ts in result["tech_stack"]:
                    print(f"  - {ts['lang']} ({ts['type']})")
                print()
            if result["languages"]:
                print("📝 语言分布:")
                for lang, count in sorted(result["languages"].items(), key=lambda x: -x[1]):
                    bar = '█' * min(count, 30)
                    print(f"  {lang:15s} {bar} {count}")
                print()
            if result["entry_points"]:
                print("🚀 入口文件:")
                for ep in result["entry_points"]:
                    print(f"  - {ep}")
                print()
            if result["suggestions"]:
                print("💡 建议:")
                for s in result["suggestions"]:
                    icon = "⚡" if s["priority"] == "高" else "📌" if s["priority"] == "中" else "💡"
                    print(f"  {icon} [{s['priority']}] {s['message']}")


if __name__ == "__main__":
    main()