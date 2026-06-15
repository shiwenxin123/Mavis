#!/usr/bin/env python3
"""
Marvis 安装脚本 — 支持 pip 安装、MCP 配置生成、多平台适配模板。
"""

import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_home():
    return os.path.expanduser("~")


def install_pip():
    """pip install 当前包"""
    print("📦 安装 Marvis 核心库...")
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", SCRIPT_DIR],
        capture_output=True, text=True
    )
    if proc.returncode == 0:
        print("  ✅ pip install -e . 成功")
    else:
        print(f"  ⚠️ pip install 失败:\n{proc.stderr[:500]}")

    print()
    print("💡 可选: 安装增强依赖")
    print("   python -m pip install marvis[full]")
    print("   python -m pip install marvis[mcp]")
    print("   python -m pip install marvis[ocr]")


def install_legacy_codex():
    """兼容旧版 Codex 目录结构"""
    dst = os.path.join(get_home(), ".codex", "skills", "marvis")
    print(f"📦 安装 Codex 适配 (兼容旧版)")
    print(f"   目标: {dst}")

    os.makedirs(os.path.join(dst, "scripts"), exist_ok=True)
    os.makedirs(os.path.join(dst, "agents"), exist_ok=True)
    os.makedirs(os.path.join(dst, "references"), exist_ok=True)

    shutil.copy2(
        os.path.join(SCRIPT_DIR, "adapters", "codex", "SKILL.md"),
        os.path.join(dst, "SKILL.md")
    )
    shutil.copy2(
        os.path.join(SCRIPT_DIR, "agents", "openai.yaml"),
        os.path.join(dst, "agents", "openai.yaml")
    )
    shutil.copy2(
        os.path.join(SCRIPT_DIR, "references", "capability_map.md"),
        os.path.join(dst, "references", "capability_map.md")
    )

    # 复制旧版 scripts 兼容
    scripts_src = os.path.join(SCRIPT_DIR, "scripts")
    if os.path.isdir(scripts_src):
        for f in os.listdir(scripts_src):
            if f.endswith(".py"):
                shutil.copy2(
                    os.path.join(scripts_src, f),
                    os.path.join(dst, "scripts", f)
                )
    print(f"  ✅ Codex 适配已安装")


def generate_mcp_config():
    """生成 MCP 配置模板"""
    config_dir = os.path.join(get_home(), ".marvis")
    os.makedirs(config_dir, exist_ok=True)

    mcp_config = {
        "mcpServers": {
            "marvis": {
                "command": sys.executable,
                "args": ["-m", "marvis.mcp.server"],
                "description": "Marvis 智能助手"
            }
        }
    }

    config_path = os.path.join(config_dir, "mcp_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(mcp_config, f, ensure_ascii=False, indent=2)

    print(f"📋 MCP 配置已生成: {config_path}")
    print()
    print("📖 各平台使用方法:")
    print()
    print("  Claude Desktop:")
    print(f'    将以上内容合并到 ~/AppData/Roaming/Claude/claude_desktop_config.json')
    print()
    print("  Claude Code:")
    print(f'    将以上内容添加到项目的 .mcp.json 或全局 mcp.json')
    print()
    print("  Cursor:")
    print("    Settings → MCP → Add Server → 填入以上配置")
    print()
    print("  Windsurf:")
    print("    将以上内容添加到 MCP 配置中")
    print()
    print("  GitHub Copilot:")
    print("    VS Code → .vscode/mcp.json → 填入以上配置")
    print()
    print("  Codex:")
    print("    将以上内容添加到 Codex 的 MCP 配置中")


def check_deps():
    """检查可选依赖"""
    print("📋 可选依赖检查:")
    deps = [
        ("pdfplumber", "PDF 文本提取"),
        ("docx", "Word 文档处理", "python-docx"),
        ("openpyxl", "Excel 文件处理"),
        ("matplotlib", "图表生成"),
        ("pandas", "数据分析"),
        ("PIL", "图片处理", "Pillow"),
        ("chardet", "编码检测"),
        ("pytesseract", "OCR", "pytesseract"),
    ]
    missing = []
    for dep in deps:
        mod_name = dep[0]
        desc = dep[1]
        pip_name = dep[2] if len(dep) > 2 else mod_name
        try:
            __import__(mod_name)
            print(f"  ✅ {pip_name:20s} ({desc})")
        except ImportError:
            print(f"  ❌ {pip_name:20s} ({desc}) — 未安装")
            missing.append(pip_name)

    if missing:
        print()
        print(f"💡 安装缺失依赖:")
        print(f"   python -m pip install {' '.join(missing)}")


def main():
    print("=" * 60)
    print("  Marvis 智能助手 v2 — 安装向导")
    print("  灵感源自腾讯 Marvis 马维斯")
    print("=" * 60)
    print()

    # 1. pip install
    install_pip()

    print()

    # 2. 兼容旧版 Codex
    install_legacy_codex()

    print()

    # 3. MCP 配置
    generate_mcp_config()

    print()

    # 4. 依赖检查
    check_deps()

    print()
    print("🎉 安装完成！")
    print()
    print("📖 快速开始:")
    print("   from marvis.core.search import search")
    print("   result = search('.', mode='name', keyword='README')")
    print("   print(result)")
    print()
    print("   或启动 MCP 服务器:")
    print(f"   {sys.executable} -m marvis.mcp.server")
    print()
    print("   或在 AI 工具中配置 MCP（见上方说明）")


if __name__ == "__main__":
    main()
