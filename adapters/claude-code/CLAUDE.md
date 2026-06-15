# Marvis 智能助手 — Claude Code 配置

## MCP 配置

在 Claude Code 的 `mcp.json` 中添加：

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

## CLAUDE.md（可选）

将以下内容添加到项目的 `CLAUDE.md` 中：

---

# Marvis 智能助手

当用户需要文件搜索、文档分析、系统管理、安全巡检等操作时，使用 Marvis MCP tools。

关键 Tool：
- `search_files` — 按名称/大小/时间搜索文件
- `search_file_content` — 搜索文件内容
- `read_document` — 读取文档（PDF/DOCX/XLSX）
- `contract_review` — 合同审查
- `data_analysis` — 数据分析
- `analyze_directory` — 分析目录结构
- `find_duplicates` — 查找重复文件
- `system_info` — 系统信息
- `disk_usage` — 磁盘使用
- `process_list` — 进程列表
- `port_check` — 端口检查
- `system_clean` — 系统清理扫描
- `ocr_image` — 图片 OCR
- `convert_format` — 格式转换
- `scan_project` — 项目分析
- `security_audit` — 安全巡检
- `batch_rename` — 批量重命名
- `compress_images` — 图片压缩
- `merge_pdfs` — PDF 合并
- `run_workflow` — 执行工作流
- `web_search` — 网页搜索

运行模式：默认效率模式，用户说"本地模式"时切为本地模式。
所有删除操作需确认，批量操作默认预览模式。
