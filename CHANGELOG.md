# 更新日志

## 2.1.0 — 2026-10-19

对应 [PR #1](https://github.com/shiwenxin123/Mavis/pull/1)。本仓库没有 PyPI 发布流程，这一版只从 GitHub Release / 标签安装。

- CLI 与 MCP 可以跑起来：`marvis`、`python -m marvis`、`marvis-mcp`。版本从 `marvis.__version__` 读取。
- `marvis doctor` 显示版本、运行模式、可选依赖，以及下一步可以敲的命令。
- 本地模式（`marvis --local`、`MARVIS_MODE=local` 或配置 `mode=local`）下，搜索、读取、监控和 URL 探活都会拒绝外网。
- 破坏性操作默认先预览。`marvis system repair` 与 MCP `net_repair` 确认后才加 `--execute` / `execute=true`。
- Linux 安全巡检不再调用 PowerShell，用 `ss` 或 `/proc/net/tcp` 查看监听端口。
- 进程列表只显示程序名，token / JWT 样式文本会打码；巡检结果不写密钥正文。
- pytest，以及 GitHub Actions 在 Python 3.10–3.13 上的入口检查和测试。
