# Marvis 智能助手 — GitHub Copilot 配置

## MCP 配置

在 VS Code 的 `.vscode/mcp.json` 中添加：

```json
{
  "servers": {
    "marvis": {
      "command": "python",
      "args": ["-m", "marvis.mcp.server"]
    }
  }
}
```

## .github/copilot-instructions.md

将以下内容添加到 `.github/copilot-instructions.md` 或在 VS Code 设置中配置自定义指令：

---

You have access to the Marvis MCP server with the following tools:

**File Search & Management**
- `search_files` — Search files by name/size/time
- `search_file_content` — Search file contents
- `analyze_directory` — Analyze directory structure
- `find_duplicates` — Detect duplicate files
- `batch_rename` — Batch rename files (preview mode by default)
- `compress_images` — Batch compress images
- `merge_pdfs` — Merge PDF files

**Document Processing**
- `read_document` — Read PDF/DOCX/XLSX content
- `contract_review` — Review contract risks
- `data_analysis` — Analyze Excel/CSV data
- `generate_chart` — Generate charts from data
- `convert_format` — Convert between formats
- `ocr_image` — Extract text from images

**System Management** (Windows)
- `system_info` — System hardware/OS info
- `disk_usage` — Disk space usage
- `process_list` — Running processes
- `port_check` — Check if port is open
- `system_clean` — Scan temp files
- `net_repair` — Network repair (DNS flush, Winsock reset)

**Security & Project**
- `scan_project` — Analyze project structure/tech stack
- `security_audit` — Full security audit
- `web_search` — Web search via Bing
- `web_monitor` — Monitor webpage changes

**Automation**
- `create_task` — Create scheduled task
- `run_task` — Run task manually
- `run_workflow` — Execute a workflow
- `list_workflows` — List available workflows

Guidelines:
- Batch operations default to preview mode, ask before executing
- Deletion requires explicit user confirmation
- Default "efficient" mode; use "local" mode for sensitive files
