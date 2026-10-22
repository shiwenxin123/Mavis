"""只读日志错误摘要。

给定一个目录，只读取日志文件末尾的一段，汇总致命、错误和警告。
相同的错误会合并计数。令牌、密码、私钥和连接串会打码。

不会删除、修改或执行日志，也不会解压、跟随符号链接。
权限错误会跳过。文件数、行数、字节和时间都有上限。
"""

import errno
import json
import os
import re
import stat
import time
from collections import deque
from datetime import datetime, timedelta, timezone

DEFAULT_TOP = 10
DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_FILES = 200
DEFAULT_MAX_ENTRIES = 20000
DEFAULT_MAX_LINES = 20000
DEFAULT_MAX_BYTES_PER_FILE = 512 * 1024
DEFAULT_MAX_TOTAL_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 8.0

_TOP_MAX = 50
_DEPTH_MAX = 32
_FILES_MAX = 2000
_ENTRIES_MAX = 100_000
_LINES_MAX = 100_000
_BYTES_PER_FILE_MIN = 64
_BYTES_PER_FILE_MAX = 2 * 1024 * 1024
_TOTAL_BYTES_MIN = 64
_TOTAL_BYTES_MAX = 32 * 1024 * 1024
_TIMEOUT_MIN = 0.2
_TIMEOUT_MAX = 30.0
_SIGNATURE_CAP = 400
_EXAMPLE_MAX = 180
_LINE_SCAN_MAX = 2000
_STORED_ERRORS = 8
_BUSY_FILES = 5
_TRACEBACK_MAX = 40
_SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv"}
_LIMIT_ORDER = ("深度", "条目", "文件", "行数", "字节", "时间", "种类")
_LEVEL_RANK = {"致命": 0, "错误": 1, "警告": 2}
_COMPRESSED = (".gz", ".bz2", ".xz", ".zip", ".zst", ".lz4")
_LOG_EXT = {".out", ".err", ".trace"}

_TS = re.compile(
    r"(?P<y>\d{4})[-/](?P<m>\d{2})[-/](?P<d>\d{2})"
    r"[T ](?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})"
    r"(?:[.,]\d+)?(?P<tz>Z|[+-]\d{2}:?\d{2})?"
)
_LEAD = re.compile(
    r"(?i)^(?:\[[^\]]{0,40}\]\s*)*"
    r"\[?(emergency|emerg|alert|critical|crit|fatal|panic|error|err|warning|warn)\]?"
    r"(?:\s*[:\-]\s*|\s+|$)"
)
_QUIET_LEAD = re.compile(
    r"(?i)^(?:\[[^\]]{0,40}\]\s*)*"
    r"\[?(debug|trace|info|notice|notset)\]?"
    r"(?:\s*[:\-]\s*|\s+|$)"
)
_KV_LEVEL = re.compile(
    r"(?i)[\"']?(?:level|severity|lvl)[\"']?\s*[:=]\s*[\"']?"
    r"(emergency|emerg|alert|critical|crit|fatal|panic|error|err|warning|warn)\b"
)
_EXC_LINE = re.compile(r"^[A-Za-z_][\w.]*(?:Error|Exception):\s+\S")
_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_NUM = re.compile(r"\d+")

_ASSIGN = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|"
    r"access[_-]?key|authorization)[A-Za-z0-9_.-]*)\s*[=:]\s*\S+"
)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
_AWS = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GITHUB = re.compile(r"\bghp_[0-9A-Za-z]{20,}\b")
_OPENAI = re.compile(r"\bsk-[0-9A-Za-z]{16,}\b")
_URL_PASS = re.compile(r"(?i)(://[^:/\s]+:)([^@\s/]+)(@)")
_PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_LEFTOVER = re.compile(
    r"(?i)(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{8,}|"
    r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.|-----BEGIN |"
    r"://[^/\s]+:(?!\[redacted\])[^/\s@]+@)"
)

_CANON = {
    "emergency": "致命",
    "emerg": "致命",
    "alert": "致命",
    "critical": "致命",
    "crit": "致命",
    "fatal": "致命",
    "panic": "致命",
    "error": "错误",
    "err": "错误",
    "warning": "警告",
    "warn": "警告",
}


def summarize_logs(
    root: str,
    top: int | None = None,
    newer_than_days: int | None = None,
    max_depth: int | None = None,
    max_files: int | None = None,
    max_entries: int | None = None,
    max_lines: int | None = None,
    max_bytes_per_file: int | None = None,
    max_total_bytes: int | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    """摘要 root 里的日志。返回可序列化结果，不改动文件系统。"""
    _reset_counters()
    requested = _existing_directory(root)
    root_real = os.path.realpath(requested)
    if not os.path.isdir(root_real):
        raise ValueError(f"不是目录: {root}")

    top_n = _bounded_int(top, DEFAULT_TOP, 1, _TOP_MAX, "top")
    days = _optional_days(newer_than_days)
    depth_cap = _bounded_int(max_depth, DEFAULT_MAX_DEPTH, 0, _DEPTH_MAX, "max_depth")
    file_cap = _bounded_int(max_files, DEFAULT_MAX_FILES, 1, _FILES_MAX, "max_files")
    entry_cap = _bounded_int(max_entries, DEFAULT_MAX_ENTRIES, 1, _ENTRIES_MAX, "max_entries")
    line_cap = _bounded_int(max_lines, DEFAULT_MAX_LINES, 1, _LINES_MAX, "max_lines")
    per_file = _bounded_int(
        max_bytes_per_file,
        DEFAULT_MAX_BYTES_PER_FILE,
        _BYTES_PER_FILE_MIN,
        _BYTES_PER_FILE_MAX,
        "max_bytes_per_file",
    )
    total_cap = _bounded_int(
        max_total_bytes,
        DEFAULT_MAX_TOTAL_BYTES,
        _TOTAL_BYTES_MIN,
        _TOTAL_BYTES_MAX,
        "max_total_bytes",
    )
    timeout = _bounded_float(
        timeout_seconds, DEFAULT_TIMEOUT_SECONDS, _TIMEOUT_MIN, _TIMEOUT_MAX, "timeout_seconds"
    )

    now = datetime.now().astimezone()
    cutoff = now - timedelta(days=days) if days is not None else None
    deadline = time.monotonic() + timeout
    groups: dict[str, dict] = {}
    levels = {"致命": 0, "错误": 0, "警告": 0}
    file_counts: dict[str, dict] = {}
    files_read = 0
    log_files_seen = 0
    dirs_seen = 0
    lines_read = 0
    bytes_read = 0
    entries_seen = 0
    non_log_skipped = 0
    compressed_skipped = 0
    binary_skipped = 0
    tailed_files = 0
    symlink_count = 0
    outside_symlink_count = 0
    error_count = 0
    skipped: list[dict] = []
    hits: set[str] = set()
    stop = False
    visited = {os.path.normcase(root_real)}
    queue: deque[tuple[str, int]] = deque([(root_real, 0)])

    while queue and not stop:
        current, depth = queue.popleft()
        if time.monotonic() >= deadline:
            hits.add("时间")
            break
        dirs_seen += 1
        try:
            listed = sorted(os.scandir(current), key=lambda item: item.name)
        except (PermissionError, OSError) as exc:
            error_count, skipped = _remember_error(error_count, skipped, root_real, current, exc)
            continue
        for entry in listed:
            if entries_seen >= entry_cap:
                hits.add("条目")
                stop = True
                break
            if time.monotonic() >= deadline:
                hits.add("时间")
                stop = True
                break
            entries_seen += 1
            try:
                is_link = entry.is_symlink()
            except OSError as exc:
                error_count, skipped = _remember_error(
                    error_count, skipped, root_real, entry.path, exc
                )
                continue
            if is_link:
                escaped, failed = _classify_symlink(root_real, entry.path)
                if failed is not None:
                    error_count, skipped = _remember_error(
                        error_count, skipped, root_real, entry.path, failed
                    )
                    continue
                symlink_count += 1
                if escaped:
                    outside_symlink_count += 1
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError as exc:
                error_count, skipped = _remember_error(
                    error_count, skipped, root_real, entry.path, exc
                )
                continue
            if is_dir:
                if entry.name in _SKIP_DIRS or _is_junction(entry.path):
                    if _is_junction(entry.path):
                        outside_symlink_count += 1
                    continue
                resolved = _safe_realpath(entry.path)
                if not resolved or not _same_tree(root_real, resolved):
                    outside_symlink_count += 1
                    continue
                if depth + 1 > depth_cap:
                    hits.add("深度")
                    continue
                child = os.path.normpath(resolved)
                child_key = os.path.normcase(child)
                if child_key in visited:
                    continue
                visited.add(child_key)
                queue.append((child, depth + 1))
                continue
            try:
                is_file = entry.is_file(follow_symlinks=False)
            except OSError as exc:
                error_count, skipped = _remember_error(
                    error_count, skipped, root_real, entry.path, exc
                )
                continue
            if not is_file:
                continue
            kind = _log_kind(entry.name)
            if kind == "other":
                non_log_skipped += 1
                continue
            log_files_seen += 1
            if kind == "compressed":
                compressed_skipped += 1
                continue
            if files_read + binary_skipped >= file_cap:
                hits.add("文件")
                stop = True
                break
            if bytes_read >= total_cap:
                hits.add("字节")
                stop = True
                break
            text, truncated, problem = _read_regular_tail(entry.path, per_file)
            if problem == "binary":
                binary_skipped += 1
                continue
            if isinstance(problem, OSError):
                error_count, skipped = _remember_error(
                    error_count, skipped, root_real, entry.path, problem
                )
                continue
            if text is None:
                continue
            files_read += 1
            if truncated:
                tailed_files += 1
            nbytes = min(len(text.encode("utf-8", errors="ignore")), per_file)
            bytes_read += nbytes
            rel = _relative(root_real, entry.path)
            try:
                file_mtime = datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime, timezone.utc).astimezone()
            except OSError:
                file_mtime = None
            _consume_file(
                text,
                rel,
                file_mtime,
                cutoff,
                now,
                groups,
                levels,
                file_counts,
                deadline,
                line_cap,
                hits,
            )
            lines_read = _lines_consumed()
            if "行数" in hits or "时间" in hits:
                stop = True
                break
            if bytes_read >= total_cap:
                hits.add("字节")
                stop = True
                break

    if _overflow_count():
        hits.add("种类")
    limit_hits = [name for name in _LIMIT_ORDER if name in hits]
    errors, warnings = _take_groups(groups, top_n)
    return {
        "root": root_real,
        "requested_root": requested,
        "top": top_n,
        "newer_than_days": days,
        "files_read": files_read,
        "log_files_seen": log_files_seen,
        "dirs_seen": dirs_seen,
        "lines_read": lines_read,
        "bytes_read": bytes_read,
        "non_log_skipped": non_log_skipped,
        "compressed_skipped": compressed_skipped,
        "binary_skipped": binary_skipped,
        "tailed_files": tailed_files,
        "symlink_count": symlink_count,
        "outside_symlink_count": outside_symlink_count,
        "error_count": error_count,
        "skipped": skipped,
        "overflow": _overflow_count(),
        "partial": bool(limit_hits),
        "limit_hits": limit_hits,
        "limits": {
            "max_depth": depth_cap,
            "max_files": file_cap,
            "max_entries": entry_cap,
            "max_lines": line_cap,
            "max_bytes_per_file": per_file,
            "max_total_bytes": total_cap,
            "timeout_seconds": timeout,
        },
        "levels": levels,
        "fatal_count": levels["致命"],
        "error_events": levels["错误"],
        "warning_events": levels["警告"],
        "errors": errors,
        "warnings": warnings,
        "busiest_files": _busiest(file_counts),
        "preview": True,
        "deleted": False,
        "modified": False,
        "moved": False,
    }


def format_log_report(summary: dict) -> str:
    """人类可读的日志摘要。示例行已打码，不含堆栈帧和文件正文。"""
    days = summary.get("newer_than_days")
    top_n = summary.get("top", DEFAULT_TOP)
    levels = summary.get("levels") or {}
    lines = [
        "日志错误摘要报告",
        f"目录: {summary.get('root', '')}",
        "模式: 只读预览（未删除、未修改、未执行日志，未跟随符号链接，未解压）",
        "说明: 每个日志只读末尾一段；示例行里的令牌、密码、私钥和连接串已打码。",
    ]
    if days:
        lines.append(f"时间窗: 最近 {days} 天（无时间戳的行按文件修改时间判断）")
    else:
        lines.append("时间窗: 不按时间过滤")
    lines.append(
        f"扫描: 读了 {summary.get('files_read', 0)} 个日志，"
        f"{summary.get('lines_read', 0)} 行；"
        f"目录 {summary.get('dirs_seen', 0)}"
    )
    lines.append(
        f"级别: 致命 {levels.get('致命', 0)}，"
        f"错误 {levels.get('错误', 0)}，"
        f"警告 {levels.get('警告', 0)}"
    )
    skipped_bits = []
    if summary.get("non_log_skipped"):
        skipped_bits.append(f"非日志 {summary['non_log_skipped']}")
    if summary.get("compressed_skipped"):
        skipped_bits.append(f"压缩包 {summary['compressed_skipped']}（未解压）")
    if summary.get("binary_skipped"):
        skipped_bits.append(f"二进制 {summary['binary_skipped']}")
    if summary.get("tailed_files"):
        skipped_bits.append(f"只读了末尾 {summary['tailed_files']} 个")
    if skipped_bits:
        lines.append("跳过/截断: " + "，".join(skipped_bits))
    outside = summary.get("outside_symlink_count") or 0
    if summary.get("symlink_count"):
        lines.append(
            f"符号链接: {summary.get('symlink_count', 0)}（未跟随"
            + (f"，其中 {outside} 个指向目录外" if outside else "")
            + "）"
        )
    error_count = summary.get("error_count") or 0
    if error_count:
        lines.append(f"读取失败: {error_count} 项（权限或系统错误）")
        for item in summary.get("skipped") or []:
            lines.append(f"    {item.get('path', '')}  {item.get('error', '')}")
    if summary.get("partial"):
        labels = "、".join(summary.get("limit_hits") or [])
        lines.append(f"扫描未完成（达到{labels}上限），结果只覆盖已读到的部分。")
    overflow = summary.get("overflow") or 0
    if overflow:
        lines.append(f"另有 {overflow} 种不同的消息未单独列出。")
    lines.append("")
    _append_group(lines, f"致命与错误（前 {top_n} 种）", summary.get("errors") or [], "未发现致命或错误。")
    lines.append("")
    _append_group(lines, f"警告（前 {top_n} 种）", summary.get("warnings") or [], "未发现警告。")
    busiest = summary.get("busiest_files") or []
    if busiest:
        lines.append("")
        lines.append("出错较多的文件")
        for index, item in enumerate(busiest, 1):
            lines.append(
                f"  {index}. 致命 {item.get('fatal', 0)}，错误 {item.get('error', 0)}，"
                f"警告 {item.get('warning', 0)}  {item.get('file', '')}"
            )
    lines.append("")
    lines.append("建议: 本命令只生成报告，不会删除、修改或执行日志。排查前请自行打开原始文件。")
    return "\n".join(lines)


def redact_log_text(text: str) -> str:
    """打码日志里的凭据样式。短文本，不回传原文。"""
    if not text:
        return ""
    cleaned = _PRIVATE.sub("[redacted]", text)
    cleaned = _URL_PASS.sub(r"\1[redacted]\3", cleaned)
    cleaned = _JWT.sub("[redacted]", cleaned)
    cleaned = _AWS.sub("[redacted]", cleaned)
    cleaned = _GITHUB.sub("[redacted]", cleaned)
    cleaned = _OPENAI.sub("[redacted]", cleaned)
    cleaned = _BEARER.sub("Bearer [redacted]", cleaned)
    cleaned = _ASSIGN.sub(lambda match: match.group(1) + "=[redacted]", cleaned)
    if _LEFTOVER.search(cleaned):
        return "[redacted]"
    return cleaned


# 每次 summarize_logs 开头清零。行数和时间上限要从逐行循环里停下来。
_consumed = 0
_overflow = 0


def _lines_consumed() -> int:
    return _consumed


def _overflow_count() -> int:
    return _overflow


def _reset_counters() -> None:
    global _consumed, _overflow
    _consumed = 0
    _overflow = 0


def _consume_file(
    text: str,
    rel: str,
    file_mtime: datetime | None,
    cutoff: datetime | None,
    now: datetime,
    groups: dict,
    levels: dict,
    file_counts: dict,
    deadline: float,
    line_cap: int,
    hits: set[str],
) -> None:
    global _consumed
    in_tb = False
    tb_lines = 0
    for raw_line in text.splitlines():
        if _consumed >= line_cap:
            hits.add("行数")
            return
        if _consumed % 200 == 0 and time.monotonic() >= deadline:
            hits.add("时间")
            return
        if not raw_line.strip():
            if in_tb:
                in_tb = False
            continue
        _consumed += 1
        clipped = raw_line[:_LINE_SCAN_MAX]
        stripped = clipped.strip()
        if in_tb:
            tb_lines += 1
            if tb_lines > _TRACEBACK_MAX:
                in_tb = False
                continue
            if clipped[:1] in {" ", "\t"} or stripped.startswith("File ") or stripped.startswith("..."):
                continue
            if _EXC_LINE.match(stripped):
                in_tb = False
                _record(rel, "错误", stripped, None, cutoff, file_mtime, groups, levels, file_counts)
                continue
            in_tb = False
        if stripped.startswith("Traceback (most recent call last)"):
            in_tb = True
            tb_lines = 0
            continue
        if stripped.startswith("{") and stripped.endswith("}"):
            recorded = _record_json(rel, stripped, cutoff, file_mtime, groups, levels, file_counts)
            if recorded:
                continue
        when = _parse_ts(stripped, now)
        body = _TS.sub("", stripped, count=1).strip(" -")
        if _QUIET_LEAD.match(body):
            continue
        lead = _LEAD.match(body)
        if lead:
            if not _within_window(when, file_mtime, cutoff):
                continue
            level = _CANON[lead.group(1).lower()]
            message = body[lead.end():].strip() or body
            _record(rel, level, message, when, None, None, groups, levels, file_counts, already_windowed=True)
            continue
        kv = _KV_LEVEL.search(stripped)
        if kv:
            if not _within_window(when, file_mtime, cutoff):
                continue
            level = _CANON[kv.group(1).lower()]
            _record(rel, level, body or stripped, when, None, None, groups, levels, file_counts, already_windowed=True)


def _record_json(rel, clipped, cutoff, file_mtime, groups, levels, file_counts) -> bool:
    if len(clipped) > _LINE_SCAN_MAX:
        return False
    try:
        payload = json.loads(clipped)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    raw_level = payload.get("level") or payload.get("severity") or payload.get("lvl") or ""
    level = _CANON.get(str(raw_level).strip().lower())
    if level is None:
        return True
    when = None
    for key in ("time", "ts", "timestamp", "@timestamp"):
        if key in payload:
            when = _parse_ts(str(payload.get(key)), datetime.now().astimezone())
            if when is not None:
                break
    if not _within_window(when, file_mtime, cutoff):
        return True
    message = payload.get("msg") or payload.get("message") or payload.get("error")
    if not isinstance(message, str) or not message.strip():
        message = level
    _record(rel, level, message, when, None, None, groups, levels, file_counts, already_windowed=True)
    return True


def _record(
    rel: str,
    level: str,
    message: str,
    when: datetime | None,
    cutoff: datetime | None,
    file_mtime: datetime | None,
    groups: dict,
    levels: dict,
    file_counts: dict,
    already_windowed: bool = False,
) -> None:
    global _overflow
    if not already_windowed and not _within_window(when, file_mtime, cutoff):
        return
    safe = redact_log_text(message.strip())[:_EXAMPLE_MAX]
    if not safe:
        safe = level
    signature = _signature(safe)
    key = level + "\0" + signature
    levels[level] = levels.get(level, 0) + 1
    bucket = file_counts.setdefault(rel, {"fatal": 0, "error": 0, "warning": 0})
    if level == "致命":
        bucket["fatal"] += 1
    elif level == "错误":
        bucket["error"] += 1
    else:
        bucket["warning"] += 1
    existing = groups.get(key)
    if existing is not None:
        existing["count"] += 1
        existing["example"] = safe
        existing["file"] = rel
        return
    if len(groups) >= _SIGNATURE_CAP:
        _overflow += 1
        return
    groups[key] = {
        "level": level,
        "count": 1,
        "signature": signature,
        "example": safe,
        "file": rel,
    }


def _signature(text: str) -> str:
    collapsed = _UUID.sub("<id>", text)
    collapsed = _IP.sub("<ip>", collapsed)
    collapsed = _NUM.sub("#", collapsed)
    collapsed = re.sub(r"\s+", " ", collapsed).strip().lower()
    return collapsed[:_EXAMPLE_MAX] or "empty"


def _within_window(when: datetime | None, file_mtime: datetime | None, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    if when is not None:
        return when >= cutoff
    if file_mtime is None:
        return False
    return file_mtime >= cutoff


def _parse_ts(text: str, now: datetime) -> datetime | None:
    match = _TS.search(text)
    if match is None:
        return None
    try:
        parsed = datetime(
            int(match.group("y")),
            int(match.group("m")),
            int(match.group("d")),
            int(match.group("H")),
            int(match.group("M")),
            int(match.group("S")),
        )
    except ValueError:
        return None
    tz = match.group("tz")
    if tz:
        if tz == "Z":
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            sign = 1 if tz[0] == "+" else -1
            digits = tz[1:].replace(":", "")
            hours = int(digits[:2])
            minutes = int(digits[2:4] or "0")
            parsed = parsed.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
        return parsed.astimezone(now.tzinfo)
    return parsed.replace(tzinfo=now.tzinfo)


def _take_groups(groups: dict, top_n: int) -> tuple[list[dict], list[dict]]:
    rows = list(groups.values())
    rows.sort(key=lambda item: (-item["count"], _LEVEL_RANK.get(item["level"], 9), item["signature"]))
    errors = [item for item in rows if item["level"] in {"致命", "错误"}][:top_n]
    warnings = [item for item in rows if item["level"] == "警告"][:top_n]
    return errors, warnings


def _busiest(file_counts: dict) -> list[dict]:
    rows = []
    for path, counts in file_counts.items():
        score = counts["fatal"] + counts["error"]
        if score <= 0 and counts["warning"] <= 0:
            continue
        rows.append({
            "file": path,
            "fatal": counts["fatal"],
            "error": counts["error"],
            "warning": counts["warning"],
            "score": score,
        })
    rows.sort(key=lambda item: (-item["score"], -item["warning"], item["file"]))
    cleaned = []
    for item in rows[:_BUSY_FILES]:
        cleaned.append({
            "file": item["file"],
            "fatal": item["fatal"],
            "error": item["error"],
            "warning": item["warning"],
        })
    return cleaned


def _append_group(lines: list[str], title: str, rows: list[dict], empty: str) -> None:
    lines.append(title)
    if not rows:
        lines.append(f"  {empty}")
        return
    for index, item in enumerate(rows, 1):
        lines.append(
            f"  {index}. ×{item.get('count', 0)}  [{item.get('level', '')}]  {item.get('signature', '')}"
        )
        example = item.get("example") or ""
        if example:
            lines.append(f"       示例: {example}")
        if item.get("file"):
            lines.append(f"       文件: {item['file']}")


def _log_kind(name: str) -> str:
    lower = name.lower()
    compressed = False
    for suffix in _COMPRESSED:
        if lower.endswith(suffix):
            lower = lower[: -len(suffix)]
            compressed = True
            break
    if not _is_plain_log_name(lower):
        return "other"
    return "compressed" if compressed else "text"


def _is_plain_log_name(lower: str) -> bool:
    if lower in {"syslog", "messages", "debug"} or lower.startswith("syslog"):
        return True
    if re.search(r"\.log(\.\d+)?$", lower):
        return True
    _, ext = os.path.splitext(lower)
    return ext in _LOG_EXT


def _read_regular_tail(path: str, max_bytes: int):
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None:
        flags |= nofollow
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.EPERM}:
            return None, False, "symlink"
        return None, False, exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None, False, OSError("不是普通文件")
        size = info.st_size
        truncated = size > max_bytes
        if truncated:
            os.lseek(fd, size - max_bytes, os.SEEK_SET)
        raw = os.read(fd, max_bytes)
    except OSError as exc:
        return None, False, exc
    finally:
        os.close(fd)
    if b"\x00" in raw:
        return None, truncated, "binary"
    if truncated:
        newline = raw.find(b"\n")
        if newline != -1:
            raw = raw[newline + 1:]
    return raw.decode("utf-8", errors="replace"), truncated, None


def _existing_directory(root: str) -> str:
    if not isinstance(root, str) or not root.strip() or "\x00" in root or "\n" in root or "\r" in root:
        raise ValueError("目录路径无效")
    requested = os.path.abspath(os.path.expanduser(root.strip()))
    if not os.path.exists(requested):
        raise ValueError(f"目录不存在: {root}")
    if not os.path.isdir(requested):
        raise ValueError(f"不是目录: {root}")
    return requested


def _optional_days(value) -> int | None:
    if value is None or value == "":
        return None
    return _bounded_int(value, 7, 1, 3650, "days")


def _bounded_int(value, default: int, low: int, high: int, label: str) -> int:
    number = _bounded_float(value, default, low, high, label, integer=True)
    return int(number)


def _bounded_float(value, default, low, high, label: str, integer: bool = False) -> float:
    if value is None:
        return float(default)
    kind = "整数" if integer else "数字"
    if isinstance(value, bool):
        raise ValueError(f"{label} 必须是{kind}")
    if isinstance(value, str):
        text = value.strip()
        try:
            value = int(text) if integer else float(text)
        except ValueError:
            raise ValueError(f"{label} 必须是{kind}") from None
    if integer and (isinstance(value, float) or not isinstance(value, int)):
        raise ValueError(f"{label} 必须是整数")
    if not integer and not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必须是数字")
    number = float(value)
    if number < low or number > high:
        low_text = str(int(low)) if integer else f"{low:g}"
        high_text = str(int(high)) if integer else f"{high:g}"
        raise ValueError(f"{label} 需在 {low_text} 到 {high_text} 之间")
    return number


def _classify_symlink(root_real: str, link_path: str) -> tuple[bool, OSError | None]:
    try:
        raw = os.readlink(link_path)
    except OSError as exc:
        return False, exc
    if not raw or "\x00" in raw:
        return True, None
    if os.path.isabs(raw):
        target = os.path.normpath(raw)
    else:
        target = os.path.normpath(os.path.join(os.path.dirname(link_path), raw))
    return not _same_tree(root_real, target), None


def _is_junction(path: str) -> bool:
    checker = getattr(os.path, "isjunction", None)
    if checker is None:
        return False
    try:
        return bool(checker(path))
    except OSError:
        return True


def _safe_realpath(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return ""


def _same_tree(root_real: str, candidate: str) -> bool:
    if not candidate:
        return False
    root_n = os.path.normcase(os.path.normpath(root_real))
    cand_n = os.path.normcase(os.path.normpath(candidate))
    try:
        return os.path.commonpath([root_n, cand_n]) == root_n
    except ValueError:
        return False


def _relative(root_real: str, path: str) -> str:
    try:
        rel = os.path.relpath(path, root_real)
    except ValueError:
        return os.path.basename(path)
    if rel == ".." or rel.startswith(".." + os.sep):
        return os.path.basename(path)
    return rel


def _remember_error(count: int, skipped: list[dict], root_real: str, path: str, exc: BaseException):
    count += 1
    if len(skipped) < _STORED_ERRORS:
        skipped.append({
            "path": _relative(root_real, path),
            "error": exc.__class__.__name__,
        })
    return count, skipped


