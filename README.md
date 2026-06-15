# Marvis

> 灵感源自腾讯 [Marvis 马维斯](https://marvis.qq.com/) AI 助手，打造通用 AI 智能助手核心库。
> 支持文件搜索、文档分析、系统管理、安全巡检、工作流引擎，可通过 CLI / MCP / Codex Skill 多种方式使用。

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

## ✨ 能力总览（25+ Tools）

### 📄 源自 Marvis 的能力

| 类别 | 功能 | CLI 命令 |
|------|------|---------|
| 文件搜索 | 按文件名/内容/大小/时间/正则搜索 | `marvis search` |
| 文档分析 | 合同审查、运营分析、文案润色、图表生成 | `marvis analyze` |
| 文件整理 | 按类型/时间归档、去重、清理 | `marvis organize` |
| AI 图库 | 按人像/主题/时间/地点维度管理图片 | `marvis knowledge --mode image-gallery` |
| AI 文档库 | 构建个人知识库，自动打标签 | `marvis knowledge --mode doc-library` |
| 系统管理 | 系统信息/进程/服务/磁盘/防火墙 | `marvis system info` |
| 系统清理 | 扫描并清理临时文件/缓存 | `marvis system clean` |
| 网络修复 | 刷新 DNS / 重置 Winsock / 重置 IP | `marvis system repair` |
| 图片 OCR | 提取图片文字，关键词搜索 | `marvis ocr` |
| 格式转换 | PDF/DOCX/XLSX/CSV/JSON/Markdown 互转 | `marvis convert` |
| 定时任务 | 定时执行脚本/提醒/监控 | `marvis workflow` |
| 网页工具 | 搜索/读取网页/监控页面变化 | `marvis web` |

### ★ 独有扩展能力

| 类别 | 功能 | CLI 命令 |
|------|------|---------|
| 项目分析 | 识别技术栈/依赖/入口，自动生成 README | `marvis project` |
| 安全巡检 | 扫描密钥泄露/端口暴露/弱密码/防火墙 | `marvis security` |
| 批量处理 | 批量重命名/图片压缩/PDF合并/编码转换 | `marvis batch` |
| 工作流引擎 | 组合操作为可复用流程，内置常用模板 | `marvis workflow` |

### 运行模式

- **效率模式**（默认）：可调用外部 API，适合非敏感任务
- **本地模式**：所有文件不离开本机，不调用外部 API，保护隐私

## 📦 安装

### 方式一：pip 安装（推荐）

```bash
# 基础安装
pip install -e .

# 安装全部依赖
pip install -e ".[full]"

# 仅安装 MCP 支持
pip install -e ".[mcp]"

# 仅安装 OCR 支持
pip install -e ".[ocr]"
```

### 方式二：Codex Skill 安装

将本项目文件夹复制到 Codex skills 目录：

```bash
# Windows
xcopy /E /I . %USERPROFILE%\.codex\skills\marvis

# macOS / Linux
cp -r . ~/.codex/skills/marvis
```

### 依赖说明

大部分功能开箱即用，部分功能需要额外依赖（`pip install -e ".[full]"` 一键安装）：

| 依赖 | 用途 |
|------|------|
| `pdfplumber` | PDF 文本提取 |
| `python-docx` | Word 文档处理 |
| `openpyxl` | Excel 文件处理 |
| `matplotlib` | 图表生成 |
| `pandas` | 数据分析 |
| `Pillow` | 图片处理 |
| `chardet` | 编码检测 |
| `mcp` | MCP 服务器 |

OCR 额外需要安装 [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) + `pytesseract`。

## 🚀 使用

### CLI

```bash
# 搜索文件
marvis search ~/Documents --keyword 合同 --ext .pdf

# 系统信息
marvis system info

# 清理垃圾
marvis system clean

# 合同审查
marvis analyze contract.pdf --action contract

# 项目分析
marvis project ~/myproject --action scan

# 安全巡检
marvis security ~/myproject --action full

# 批量重命名
marvis batch rename ~/photos --pattern date-prefix --execute

# 查看工作流模板
marvis workflow templates
```

### MCP 服务器

启动 MCP 服务器，供任意 MCP 客户端使用：

```bash
marvis-mcp
# 或
python -m marvis.mcp.server
```

在 Codex / Claude Desktop / Cursor / Windsurf 等的 MCP 配置中添加：

```json
{
  "mcpServers": {
    "marvis": {
      "command": "python",
      "args": ["-m", "marvis.mcp.server"]
    }
  }
}
```

### Python API

```python
from marvis.core.search import search_by_name, search_by_content
from marvis.core.doc_analyzer import contract_review, generate_chart
from marvis.core.system_manager import sys_info, system_clean, net_repair
from marvis.core.security_audit import full_audit
from marvis.core.project_scanner import scan_project
from marvis.core.workflow import run_workflow, builtin_workflows
```

### Codex Skill

安装后在 Codex 中直接对话即可触发：

```
帮我搜索桌面上所有的 PDF 文件
电脑配置怎么样
清理一下系统垃圾
审查一下这份合同的风险
做个安全巡检
```

## 📁 项目结构

```
marvis/
├── marvis/                     # 核心 Python 包
│   ├── cli.py                  # CLI 入口
│   ├── core/                   # 核心功能模块
│   │   ├── search.py           # 文件智能搜索
│   │   ├── doc_analyzer.py     # 文档深度分析
│   │   ├── file_organizer.py   # 文件智能整理
│   │   ├── knowledge_base.py   # AI 图库 / 文档库
│   │   ├── system_manager.py   # 系统管理 + 清理 + 网络修复
│   │   ├── ocr.py              # 图片 OCR 搜索
│   │   ├── format_converter.py # 文件格式转换
│   │   ├── task_scheduler.py   # 定时任务与自动化
│   │   ├── web_monitor.py      # 网页搜索与监控
│   │   ├── project_scanner.py  # ★ 项目感知分析
│   │   ├── security_audit.py   # ★ 安全巡检
│   │   ├── batch_processor.py  # ★ 批量文件处理
│   │   └── workflow.py         # ★ 快捷工作流
│   ├── mcp/                    # MCP 服务器
│   │   ├── server.py
│   │   └── tools/
│   └── utils/                  # 工具函数
│       ├── config.py
│       ├── fs.py
│       └── shell.py
├── adapters/                   # 多平台适配
│   ├── codex/SKILL.md          # Codex Skill 适配
│   ├── claude-code/CLAUDE.md   # Claude Code 适配
│   ├── copilot/                # GitHub Copilot 适配
│   ├── cursor/                 # Cursor 适配
│   ├── windsurf/               # Windsurf 适配
│   └── mcp.json                # MCP 配置模板
├── scripts/                    # 独立脚本（Codex Skill 用）
├── agents/openai.yaml          # Codex UI 元数据
├── references/                 # 参考文档
├── pyproject.toml              # Python 包配置
├── install.py                  # Codex Skill 一键安装
├── LICENSE                     # MIT License
└── README.md
```

## 🔌 多平台适配

Marvis v2 支持多种 AI 编码工具：

| 平台 | 适配方式 | 配置文件 |
|------|---------|---------|
| Codex CLI | Skill + MCP | `adapters/codex/SKILL.md` |
| Claude Code | MCP + CLAUDE.md | `adapters/claude-code/CLAUDE.md` |
| GitHub Copilot | Copilot Instructions | `adapters/copilot/.github/copilot-instructions.md` |
| Cursor | .cursorrules | `adapters/cursor/.cursorrules` |
| Windsurf | .windsurfrules | `adapters/windsurf/.windsurfrules` |

## 🛡️ 安全准则

- 文件整理/批量操作默认**预览模式**，不直接执行
- 任何删除操作必须经用户确认
- 不修改系统关键注册表路径
- 系统修改前说明具体变更和影响
- 本地模式下不访问外部网络和 API
- 安全巡检仅做检测，不自动修复

## 🤝 致谢

- [腾讯 Marvis 马维斯](https://marvis.qq.com/) — 产品灵感来源
- [Codex CLI](https://github.com/openai/codex) — Skill 运行平台
- [MCP](https://modelcontextprotocol.io/) — 工具协议标准

## 📄 License

[MIT License](LICENSE)