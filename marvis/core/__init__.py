"""Marvis 核心能力模块 — 全部 13 个能力"""

from marvis.core.search import (
    search, search_by_name, search_by_content, search_by_size,
    search_by_time, search_by_regex,
)
from marvis.core.doc_analyzer import (
    read_file, contract_review, data_analysis, generate_chart, polish_text,
)
from marvis.core.file_organizer import (
    scan_files, analyze_structure, generate_organize_plan,
    find_duplicates, find_temp_files, find_empty_dirs, organize_summary, get_category,
)
from marvis.core.knowledge_base import (
    build_image_gallery, build_doc_library,
    search_gallery, search_library,
    gallery_stats, library_stats,
)
from marvis.core.system_manager import (
    sys_info, net_info, process_list, service_list,
    startup_list, env_vars, disk_usage, firewall_rules,
    port_check, system_clean, net_repair,
)
from marvis.core.ocr import (
    check_tesseract, ocr_image, scan_and_ocr, search_by_text, ocr_batch,
)
from marvis.core.format_converter import (
    pdf_to_text, docx_to_text, xlsx_to_json, csv_to_json,
    json_to_csv, xlsx_to_markdown, convert,
)
from marvis.core.task_scheduler import (
    create_task, list_tasks, get_task, delete_task, run_task,
)
from marvis.core.web_monitor import (
    fetch_page, extract_text, extract_links, extract_meta,
    search_web, read_page, monitor_page,
)
from marvis.core.project_scanner import (
    scan_project, generate_readme, parse_dependencies, generate_suggestions,
)
from marvis.core.security_audit import (
    check_sensitive_files, check_open_ports, check_user_accounts,
    check_firewall, check_windows_update, full_audit,
)
from marvis.core.batch_processor import (
    batch_rename, compress_images, merge_pdfs, convert_encoding, batch_extract,
)
from marvis.core.workflow import (
    create_workflow, list_workflows, get_workflow, delete_workflow,
    run_workflow, builtin_templates,
)
