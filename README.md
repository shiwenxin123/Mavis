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
| 网络修复 | 默认只预览；`--execute` 后才刷新 DNS / 重置 Winsock | `marvis system repair` |
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

- **效率模式**（默认）：网页工具可以访问外部网络，适合非敏感任务
- **本地模式**：不访问外部网络。`marvis --local …`，或设置 `MARVIS_MODE=local`，或在 `~/.marvis/config.json` 写 `{"mode": "local"}`

## 📦 安装

当前版本 **2.1.4**（[更新说明](CHANGELOG.md)）。本仓库尚未配置 PyPI 发布。

### 从 GitHub 安装

```bash
pip install "git+https://github.com/shiwenxin123/Mavis.git"
```

已打标签的 2.1.0：`pip install "git+https://github.com/shiwenxin123/Mavis.git@v2.1.0"`。

### 方式一：pip 安装（本地开发）

```bash
# 基础安装
pip install -e .

# 安装全部依赖
pip install -e ".[full]"

# 仅安装 MCP 支持
pip install -e ".[mcp]"

# 仅安装 OCR 支持
pip install -e ".[ocr]"

# 开发与测试（推送后 GitHub Actions 会在 Python 3.10–3.13 上跑同样的检查）
pip install -e ".[dev]"
pytest
marvis doctor
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
# 看看当前装了什么、是不是本地模式
marvis doctor

# 搜索文件
marvis search ~/Documents --keyword 合同 --ext .pdf

# 系统信息
marvis system info

# 清理扫描（只列出可清理项，不删除）
marvis system clean

# 网络修复默认只预览
marvis system repair
# 确认后再执行
marvis system repair --execute

# 合同审查
marvis analyze contract.pdf --action contract

# 项目分析
marvis project ~/myproject --action scan

# 安全巡检（报告文件位置和类型，不打印密钥正文）
marvis security ~/myproject --action full

# 批量重命名（默认预览，确认后加 --execute）
marvis batch rename ~/photos --pattern date-prefix --execute

# 查看工作流模板（敏感文件卫生标成可直接运行）
marvis workflow templates

# 只读扫描示例目录，打印卫生报告，不删除文件
marvis workflow run --template 敏感文件卫生 --root samples/hygiene

# 别名 hygiene。报告写到新文件；文件已存在则拒绝覆盖
marvis workflow run --template hygiene --root samples/hygiene --output ./hygiene-report.txt

# 机器可读结果
marvis workflow run --template hygiene --root samples/hygiene --json

# 只读查看示例目录所在磁盘、最大的文件和子目录；不删除、不移动
marvis workflow run --template 磁盘与大文件巡检 --root samples/disk

# 别名 disk。前 5 项，超过 30 天且不小于 1MB 算久未修改
marvis workflow run --template disk --root samples/disk --top 5 --days 30

# 只读摘要示例日志里的错误和警告；令牌和密码会打码，不修改文件
marvis workflow run --template 日志错误摘要 --root samples/logs

# 别名 logs。只看最近 7 天、每种级别最多 5 条
marvis workflow run --template logs --root samples/logs --top 5 --days 7

# 只读查看本机占用较高的进程和监听端口；不结束进程
marvis workflow run --template 进程与监听端口巡检

# 别名 procs。用静态样本，不探测本机；各列前 5 项
marvis workflow run --template procs --root samples/procs --top 5

# 本地模式：下面这条会拒绝访问网络
marvis --local web search --query 关键词
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
from marvis.core.workflow import run_workflow, builtin_templates, run_builtin_template
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
├── CHANGELOG.md                # 版本说明
├── install.py                  # Codex Skill 一键安装
├── LICENSE                     # MIT License
└── README.md
```

## 🔌 多平台适配

Marvis v2.1 支持多种 AI 编码工具：

| 平台 | 适配方式 | 配置文件 |
|------|---------|---------|
| Codex CLI | Skill + MCP | `adapters/codex/SKILL.md` |
| Claude Code | MCP + CLAUDE.md | `adapters/claude-code/CLAUDE.md` |
| GitHub Copilot | Copilot Instructions | `adapters/copilot/.github/copilot-instructions.md` |
| Cursor | .cursorrules | `adapters/cursor/.cursorrules` |
| Windsurf | .windsurfrules | `adapters/windsurf/.windsurfrules` |

## 🛡️ 安全准则

- 文件整理/批量操作默认**预览模式**，不直接执行
- 网络修复（`marvis system repair` / MCP `net_repair`）默认只预览，确认后加 `--execute`
- 任何删除操作必须经用户确认
- 不修改系统关键注册表路径
- 系统修改前说明具体变更和影响
- 本地模式下不访问外部网络和 API（网页搜索、读取、监控、URL 探活都会拒绝）
- 安全巡检仅做检测，不自动修复，也不把密钥正文写进结果
- 工作流模板「敏感文件卫生」「磁盘与大文件巡检」「日志错误摘要」和「进程与监听端口巡检」只读，不删除、不移动、不修改文件，也不结束进程
- 日志摘要只读文件末尾，不跟随符号链接，不解压，示例行里的令牌和密码会打码
- 进程列表和进程巡检会打码命令行里的 token / 密钥样式文本。巡检不读其它用户的命令行，也不结束进程

## 🤝 致谢

- [腾讯 Marvis 马维斯](https://marvis.qq.com/) — 产品灵感来源
- [Codex CLI](https://github.com/openai/codex) — Skill 运行平台
- [MCP](https://modelcontextprotocol.io/) — 工具协议标准

## 📄 License

[MIT License](LICENSE)