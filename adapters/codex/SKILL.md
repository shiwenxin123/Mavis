---
name: marvis
description: 通用智能文件搜索、深度理解、整理归档、系统管理、安全巡检、自动化与项目分析助手。通过 MCP 协议适配 Codex。
---

# Marvis 智能助手 v2

## 重要：Marvis v2 通过 MCP 协议工作

Marvis v2 已重构为 MCP Server。在 Codex 中使用前，需先配置 MCP：

### 方式一：配置 MCP（推荐）

在 Codex 的 MCP 配置中添加：

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

安装：`pip install -e .` 或 `pip install marvis`

### 方式二：直接 Python 调用（兼容旧版）

```python
from marvis.core.search import search
from marvis.core.doc_analyzer import contract_review
from marvis.core.system_manager import sys_info
```

## 所有能力（25+ Tools）

| 类别 | MCP Tool | 功能 |
|------|----------|------|
| 搜索 | `search_files` | 按文件名/大小/时间搜索 |
| 搜索 | `search_file_content` | 搜索文件内容 |
| 文档 | `read_document` | 读取文档内容 |
| 文档 | `contract_review` | 合同审查 |
| 文档 | `data_analysis` | 数据分析 |
| 文档 | `generate_chart` | 生成图表 |
| 整理 | `analyze_directory` | 目录分析 |
| 整理 | `find_duplicates` | 查找重复文件 |
| 知识库 | `build_image_gallery` | 构建图库 |
| 知识库 | `build_doc_library` | 构建文档库 |
| 系统 | `system_info` | 系统信息 |
| 系统 | `disk_usage` | 磁盘使用 |
| 系统 | `process_list` | 进程列表 |
| 系统 | `port_check` | 端口检查 |
| 系统 | `system_clean` | 系统清理 |
| 系统 | `net_repair` | 网络修复 |
| OCR | `ocr_image` | 图片OCR |
| OCR | `ocr_search` | OCR搜索 |
| 转换 | `convert_format` | 格式转换 |
| 任务 | `create_task` | 创建定时任务 |
| 网页 | `web_search` | 网页搜索 |
| 网页 | `web_monitor` | 网页监控 |
| 项目 | `scan_project` | 项目分析 |
| 安全 | `security_audit` | 安全巡检 |
| 批量 | `batch_rename` | 批量重命名 |
| 批量 | `compress_images` | 图片压缩 |
| 批量 | `merge_pdfs` | PDF合并 |
| 工作流 | `run_workflow` | 执行工作流 |

## 安全准则

- 文件整理/批量操作默认预览模式
- 删除操作须经用户确认
- 不修改系统关键注册表
- 系统修改前说明具体变更和影响
