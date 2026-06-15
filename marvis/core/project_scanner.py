"""
Marvis 项目感知分析 — 扫描项目结构、识别技术栈、依赖、入口、生成 README。

可导入使用：
    from marvis.core.project_scanner import scan_project, generate_readme, parse_dependencies
"""

import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Optional

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vs",
    "$RECYCLE.BIN", "dist", "build", ".next", ".nuxt", "target", ".tox",
    "vendor", "Pods", ".gradle", ".mvn", "bin", "obj", "Debug", "Release",
}

TECH_MARKERS: dict[str, dict[str, str]] = {
    "package.json": {"lang": "JavaScript/TypeScript", "type": "前端"},
    "tsconfig.json": {"lang": "TypeScript", "type": "前端"},
    "vue.config.js": {"lang": "Vue", "type": "前端"},
    "next.config.js": {"lang": "Next.js", "type": "前端"},
    "nuxt.config.js": {"lang": "Nuxt.js", "type": "前端"},
    "vite.config.ts": {"lang": "Vite", "type": "前端"},
    "tailwind.config.js": {"lang": "Tailwind CSS", "type": "前端"},
    "requirements.txt": {"lang": "Python", "type": "后端"},
    "setup.py": {"lang": "Python", "type": "后端"},
    "pyproject.toml": {"lang": "Python", "type": "后端"},
    "Pipfile": {"lang": "Python", "type": "后端"},
    "manage.py": {"lang": "Django", "type": "后端"},
    "go.mod": {"lang": "Go", "type": "后端"},
    "Cargo.toml": {"lang": "Rust", "type": "后端"},
    "pom.xml": {"lang": "Java/Maven", "type": "后端"},
    "build.gradle": {"lang": "Java/Gradle", "type": "后端"},
    "docker-compose.yml": {"lang": "Docker", "type": "基础设施"},
    "Dockerfile": {"lang": "Docker", "type": "基础设施"},
    "Jenkinsfile": {"lang": "Jenkins", "type": "CI/CD"},
    ".gitlab-ci.yml": {"lang": "GitLab CI", "type": "CI/CD"},
}

LANG_EXTENSIONS: dict[str, str] = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JSX", ".tsx": "TSX", ".vue": "Vue", ".svelte": "Svelte",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin",
    ".c": "C", ".cpp": "C++", ".h": "C/C++ Header", ".cs": "C#",
    ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".sh": "Shell",
    ".ps1": "PowerShell", ".sql": "SQL", ".r": "R", ".scala": "Scala",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".less": "Less",
}

ENTRY_NAMES = {
    "main.py", "app.py", "index.js", "index.ts", "main.go",
    "main.rs", "manage.py", "server.py", "__main__.py",
}


def scan_project(root: str, max_depth: int = 5) -> dict:
    """完整项目扫描：技术栈、语言分布、入口、依赖、建议"""
    result: dict = {
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
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        rel_depth = os.path.relpath(dirpath, root).count(os.sep)
        if rel_depth >= max_depth:
            dirnames.clear()
            continue

        for f in filenames:
            full = os.path.join(dirpath, f)
            try:
                st = os.stat(full)
                ext = os.path.splitext(f)[1].lower()
                rel_path = os.path.relpath(full, root)
                result["total_files"] += 1
                result["total_size"] += st.st_size
                if ext in LANG_EXTENSIONS:
                    result["languages"][LANG_EXTENSIONS[ext]] += 1
                result["file_stats"][ext if ext else "无扩展名"] += 1
                if f in ENTRY_NAMES:
                    result["entry_points"].append(rel_path)
                if f.startswith(".") or f in ("tsconfig.json", "Makefile", "Dockerfile"):
                    result["config_files"].append(rel_path)
                if f in TECH_MARKERS:
                    marker = TECH_MARKERS[f]
                    if marker not in result["tech_stack"]:
                        result["tech_stack"].append(marker)
            except (PermissionError, OSError):
                continue

    result["dependencies"] = parse_dependencies(root)
    result["suggestions"] = generate_suggestions(result)
    return result


def parse_dependencies(root: str) -> dict[str, list | dict]:
    """解析项目依赖"""
    deps: dict = {}

    pkg_json = os.path.join(root, "package.json")
    if os.path.isfile(pkg_json):
        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            prod = list((data.get("dependencies") or {}).keys())
            dev = list((data.get("devDependencies") or {}).keys())
            deps["npm"] = {"production": prod[:30], "dev": dev[:20]}
        except (json.JSONDecodeError, OSError):
            pass

    req_txt = os.path.join(root, "requirements.txt")
    if os.path.isfile(req_txt):
        try:
            with open(req_txt, "r", encoding="utf-8") as f:
                lines = [
                    l.strip().split("==")[0].split(">=")[0].split("~=")[0]
                    for l in f if l.strip() and not l.startswith("#")
                ]
            deps["pip"] = lines[:50]
        except OSError:
            pass

    go_mod = os.path.join(root, "go.mod")
    if os.path.isfile(go_mod):
        try:
            with open(go_mod, "r", encoding="utf-8") as f:
                lines = [
                    l.strip().split()[0] for l in f
                    if l.strip() and not l.startswith(("module", "go ", "//"))
                ]
            deps["go"] = lines[:30]
        except OSError:
            pass

    return deps


def generate_suggestions(result: dict) -> list[dict]:
    """根据扫描结果生成建议"""
    suggestions = []

    gitignore = os.path.join(result["root"], ".gitignore")
    if not os.path.isfile(gitignore) and result["total_files"] > 5:
        suggestions.append({"type": "配置缺失", "message": "缺少 .gitignore 文件", "priority": "中"})

    readme = None
    for name in ("README.md", "README.txt", "readme.md"):
        if os.path.isfile(os.path.join(result["root"], name)):
            readme = name
            break
    if not readme and result["total_files"] > 3:
        suggestions.append({"type": "文档缺失", "message": "缺少 README 文件", "priority": "中"})

    if not result["entry_points"]:
        suggestions.append({"type": "入口不明", "message": "未检测到标准入口文件", "priority": "低"})

    return suggestions


def generate_readme(result: dict) -> str:
    """根据扫描结果自动生成 README.md"""
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
            dep_list = deps.get("production", deps) if isinstance(deps, dict) else deps
            for d in (dep_list[:20] if isinstance(dep_list, list) else []):
                lines.append(f"- {d}")
            lines.append("")

    lines.append("## 快速开始\n```bash\n# TODO: 添加启动命令\n```\n")
    return "\n".join(lines)
