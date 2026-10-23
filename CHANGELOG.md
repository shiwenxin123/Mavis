# 更新日志

## 2.1.3 — 2026-10-22

- 新增可直接运行的只读工作流模板「日志错误摘要」。`marvis workflow run --template 日志错误摘要 --root samples/logs`（别名 `logs`、`log-errors`）汇总目录中日志的致命、错误和警告，把重复消息合并计数，并打码令牌、密码、私钥和连接串。默认每种级别列出前 10 种，不按时间过滤；`--top` 调整条数，`--days` 只统计最近若干天。每个文件只读末尾一段，不删除、不修改、不执行日志，不跟随符号链接，也不解压。权限错误会跳过，并用文件数、行数、字节和时间上限避免扫过大目录。

## 2.1.2 — 2026-10-21

- 新增可直接运行的只读工作流模板「磁盘与大文件巡检」。`marvis workflow run --template 磁盘与大文件巡检 --root samples/disk`（别名 `disk`、`large-files`）报告 root 所在文件系统的用量、目录内最大的文件和子目录，以及超过指定天数的大文件。默认列出前 10 项、天数为 90、大文件阈值为 1MB，可用 `--top`、`--days`、`--min-bytes` 调整。不删除、不移动、不修改文件，不跟随符号链接；权限错误会跳过，并用深度、条目和时间上限避免扫过大目录。

## 2.1.1 — 2026-10-20

- 新增可直接运行的工作流模板「敏感文件卫生」。`marvis workflow templates` 会列出它；`marvis workflow run --template 敏感文件卫生 --root samples/hygiene`（别名 `hygiene`）只读扫描并打印报告，不删除文件，也不输出密钥正文。`--output` 把报告写到新文件，已存在则拒绝覆盖。
- MCP `run_workflow` 增加 `template`、`root`、`output`。原来的 `name` 调用不变。带删除或系统改动的内置模板不能用 `--template` 直接跑。

## 2.1.0 — 2026-10-19

对应 [PR #1](https://github.com/shiwenxin123/Mavis/pull/1)。本仓库没有 PyPI 发布流程，这一版只从 GitHub Release / 标签安装。

- CLI 与 MCP 可以跑起来：`marvis`、`python -m marvis`、`marvis-mcp`。版本从 `marvis.__version__` 读取。
- `marvis doctor` 显示版本、运行模式、可选依赖，以及下一步可以敲的命令。
- 本地模式（`marvis --local`、`MARVIS_MODE=local` 或配置 `mode=local`）下，搜索、读取、监控和 URL 探活都会拒绝外网。
- 破坏性操作默认先预览。`marvis system repair` 与 MCP `net_repair` 确认后才加 `--execute` / `execute=true`。
- Linux 安全巡检不再调用 PowerShell，用 `ss` 或 `/proc/net/tcp` 查看监听端口。
- 进程列表只显示程序名，token / JWT 样式文本会打码；巡检结果不写密钥正文。
- pytest，以及 GitHub Actions 在 Python 3.10–3.13 上的入口检查和测试。
