# Marvis 能力映射参考

本文档描述 Marvis 马维斯 AI 助手的核心功能到 Codex 环境的完整映射关系。

## 原始功能 → Codex 映射

| Marvis 功能 | Codex 实现 | 脚本 |
|-------------|-----------|------|
| 本地文档智能搜索 | 全文搜索 + 文件名搜索 + 元数据筛选 | `smart_search.py` |
| 图片内容搜索 | OCR 文字提取 + 关键词匹配 | `ocr_search.py` |
| 文件深度理解与生成 | 文件格式解析 + 内容分析 + 格式转换 + 润色 + 图表 | `format_converter.py` + `doc_analyzer.py` + LLM |
| 合同信息审查 | 关键条款提取 + 风险规则引擎 + 审查清单 | `doc_analyzer.py --action contract` |
| 运营数据分析 | 数据统计 + 异常检测 + 趋势分析 | `doc_analyzer.py --action analysis` |
| 文案润色/内容优化 | 文本质量评估 + 润色建议 | `doc_analyzer.py --action polish` |
| 图表生成 | 从 Excel/CSV 生成折线/柱状/饼图等 | `doc_analyzer.py --action chart` |
| 文件智能整理 | 按类型/时间归档 + 去重 + 清理 | `file_organizer.py` |
| AI 图库 | 按人像/主题/时间/地点维度管理图片 | `knowledge_base.py --mode image-gallery` |
| AI 文档库/知识库 | 文档索引 + 标签 + 检索 + 笔记提炼 | `knowledge_base.py --mode doc-library` |
| 一句话完成电脑设置 | PowerShell 系统命令封装 | `system_manager.py` |
| 系统清理 | 临时文件/缓存/缩略图/更新缓存扫描 | `system_manager.py --action system-clean` |
| 网络修复 | 刷新 DNS + 重置 Winsock + 重置 IP | `system_manager.py --action net-repair` |
| 定时任务/自动签到 | Windows 任务计划程序 + 定时脚本 | `task_scheduler.py` |
| 网页搜索/监控 | 网页抓取 + 变化检测 + 关键词监控 | `web_monitor.py` |
| 效率/本地双模式 | 模式判断逻辑（SKILL.md 中定义） | 无脚本，由 LLM 按规则切换 |
| 手机远程操控 | Codex 环境不适用 | 不实现 |

## 搜索意图映射

| 用户意图 | 搜索模式 | 参数 |
|---------|---------|------|
| "找所有 PDF 文件" | name | --ext .pdf |
| "包含'合同'的文档" | content | --keyword 合同 |
| "大于 50MB 的文件" | size | --min-size 50 |
| "最近一周修改的文件" | time | --days 7 |
| "包含手机号的文件" | regex | --pattern "1[3-9]\d{9}" |

## 系统管理意图映射

| 用户意图 | 操作 | 参数 |
|---------|------|------|
| "电脑配置怎么样" | sys-info | - |
| "网络什么情况" | net-info | - |
| "哪些进程占 CPU" | processes | --sort cpu |
| "哪些服务在运行" | services | --status Running |
| "开机启动项有哪些" | startup | - |
| "磁盘空间够不够" | disk | - |
| "80 端口开没开" | port-check | --port 80 |
| "清理系统垃圾" | system-clean | - |
| "修复网络" | net-repair | - |

## 运行模式规则

| 触发条件 | 模式 | 行为 |
|---------|------|------|
| 默认 | 效率模式 | 可调用外部 API |
| 用户说"本地模式" | 本地模式 | 不调用外部 API |
| 处理身份证/银行卡/合同等敏感文件 | 本地模式 | 不调用外部 API |
| 用户明确要求隐私保护 | 本地模式 | 不调用外部 API |

## 安全限制

- 文件整理：默认预览模式，不自动移动/删除
- 系统修改：需用户确认，不执行高危操作
- 网络修复：需要管理员权限
- OCR：需要 Tesseract OCR 引擎
- 文件格式转换：依赖 Python 库，按需安装
- 图表生成：需要 matplotlib + pandas