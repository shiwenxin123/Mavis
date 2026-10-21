"""只读磁盘与大文件巡检。

给定一个目录，报告它所在文件系统的用量、目录里最大的文件和子目录，
以及久未修改的大文件。只使用 stat / 列目录，不打开文件内容。

不会删除、移动或修改任何文件，也不会跟随符号链接。
指向目录外的链接只根据链接文本判断，不读取目标。
权限错误会跳过。深度、条目数和时间有上限，避免在大目录上停不住。
"""

import heapq
import os
import shutil
import time
from collections import deque

from marvis.utils.fs import format_size

DEFAULT_TOP = 10
DEFAULT_DAYS = 90
DEFAULT_MIN_OLD_BYTES = 1024 * 1024
DEFAULT_MAX_DEPTH = 16
DEFAULT_MAX_ENTRIES = 50000
DEFAULT_TIMEOUT_SECONDS = 8.0

_TOP_MAX = 50
_DAYS_MAX = 3650
_MIN_BYTES_MAX = 1_000_000_000
_DEPTH_MAX = 32
_ENTRIES_MAX = 100_000
_TIMEOUT_MIN = 0.2
_TIMEOUT_MAX = 30.0
_STORED_ERRORS = 8
_LIMIT_ORDER = ("深度", "条目", "时间")


def inspect_large_files(
    root: str,
    top: int | None = None,
    older_than_days: int | None = None,
    min_old_bytes: int | None = None,
    max_depth: int | None = None,
    max_entries: int | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    """巡检 root。返回可序列化的汇总，不改动文件系统。"""
    requested = _existing_directory(root)
    root_real = os.path.realpath(requested)
    if not os.path.isdir(root_real):
        raise ValueError(f"不是目录: {root}")

    top_n = _bounded_int(top, DEFAULT_TOP, 1, _TOP_MAX, "top")
    days = _bounded_int(older_than_days, DEFAULT_DAYS, 1, _DAYS_MAX, "days")
    min_bytes = _bounded_int(min_old_bytes, DEFAULT_MIN_OLD_BYTES, 0, _MIN_BYTES_MAX, "min_bytes")
    depth_cap = _bounded_int(max_depth, DEFAULT_MAX_DEPTH, 1, _DEPTH_MAX, "max_depth")
    entry_cap = _bounded_int(max_entries, DEFAULT_MAX_ENTRIES, 1, _ENTRIES_MAX, "max_entries")
    timeout = _bounded_float(
        timeout_seconds, DEFAULT_TIMEOUT_SECONDS, _TIMEOUT_MIN, _TIMEOUT_MAX, "timeout_seconds"
    )

    now = time.time()
    deadline = time.monotonic() + timeout
    age_cutoff = days * 86400
    file_heap: list = []
    old_heap: list = []
    seq = 0
    dir_bytes = {root_real: 0}
    dir_files = {root_real: 0}
    files_seen = 0
    dirs_seen = 0
    scanned_bytes = 0
    entries_seen = 0
    symlink_count = 0
    outside_symlink_count = 0
    error_count = 0
    old_large_count = 0
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
            iterator = os.scandir(current)
        except (PermissionError, OSError) as exc:
            error_count, skipped = _remember_error(
                error_count, skipped, root_real, current, exc
            )
            continue
        with iterator:
            for entry in iterator:
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
                    if _is_junction(entry.path):
                        outside_symlink_count += 1
                        continue
                    resolved = _safe_realpath(entry.path)
                    if not resolved:
                        error_count, skipped = _remember_error(
                            error_count, skipped, root_real, entry.path, OSError("无法解析目录")
                        )
                        continue
                    if not _same_tree(root_real, resolved):
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
                    dir_bytes.setdefault(child, 0)
                    dir_files.setdefault(child, 0)
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
                try:
                    st = entry.stat(follow_symlinks=False)
                except (PermissionError, OSError) as exc:
                    error_count, skipped = _remember_error(
                        error_count, skipped, root_real, entry.path, exc
                    )
                    continue
                size = int(st.st_size)
                rel = _relative(root_real, entry.path)
                record = {
                    "path": os.path.abspath(entry.path),
                    "rel": rel,
                    "size_bytes": size,
                    "size_readable": format_size(size),
                    "modified": _format_mtime(st.st_mtime),
                }
                files_seen += 1
                scanned_bytes += size
                seq = _push_top(file_heap, record, top_n, seq)
                _add_to_ancestors(dir_bytes, dir_files, root_real, current, size)
                if size >= min_bytes and (now - st.st_mtime) >= age_cutoff:
                    old_large_count += 1
                    seq = _push_top(old_heap, record, top_n, seq)

    limit_hits = [name for name in _LIMIT_ORDER if name in hits]
    largest_dirs = _largest_directories(dir_bytes, dir_files, root_real, top_n)
    return {
        "root": root_real,
        "requested_root": requested,
        "filesystem": _filesystem_usage(root_real),
        "top": top_n,
        "older_than_days": days,
        "min_old_bytes": min_bytes,
        "files_seen": files_seen,
        "dirs_seen": dirs_seen,
        "scanned_bytes": scanned_bytes,
        "scanned_readable": format_size(scanned_bytes),
        "symlink_count": symlink_count,
        "outside_symlink_count": outside_symlink_count,
        "error_count": error_count,
        "skipped": skipped,
        "partial": bool(limit_hits),
        "limit_hits": limit_hits,
        "limits": {
            "max_depth": depth_cap,
            "max_entries": entry_cap,
            "timeout_seconds": timeout,
        },
        "largest_files": _take(file_heap),
        "largest_dirs": largest_dirs,
        "old_large_files": _take(old_heap),
        "old_large_count": old_large_count,
        "preview": True,
        "deleted": False,
        "modified": False,
        "moved": False,
    }


def format_disk_report(summary: dict) -> str:
    """人类可读的巡检报告。只包含路径和大小，不包含文件内容。"""
    fs = summary.get("filesystem") or {}
    days = summary.get("older_than_days", DEFAULT_DAYS)
    min_bytes = summary.get("min_old_bytes", DEFAULT_MIN_OLD_BYTES)
    min_label = format_size(int(min_bytes or 0))
    top_n = summary.get("top", DEFAULT_TOP)
    lines = [
        "磁盘与大文件巡检报告",
        f"目录: {summary.get('root', '')}",
        "模式: 只读预览（未删除、未移动、未修改任何文件，未跟随符号链接）",
    ]
    if fs.get("error"):
        lines.append(f"文件系统: {fs['error']}")
    else:
        lines.append(
            "文件系统: "
            f"已用 {fs.get('used_readable')} / 共 {fs.get('total_readable')}"
            f"（{fs.get('percent')}%），可用 {fs.get('free_readable')}"
        )
    lines.append("说明: 上面是 root 所在文件系统的用量；下面的大小只统计这次读到的普通文件。")
    lines.append(f"目录内普通文件合计: {summary.get('scanned_readable', format_size(0))}")
    lines.append(
        f"扫描: 文件 {summary.get('files_seen', 0)}，"
        f"目录 {summary.get('dirs_seen', 0)}，"
        f"符号链接 {summary.get('symlink_count', 0)}（未跟随，未读取链接目标）"
    )
    outside = summary.get("outside_symlink_count") or 0
    if outside:
        lines.append(f"指向目录外或未进入的链接: {outside}（已跳过）")
    error_count = summary.get("error_count") or 0
    if error_count:
        lines.append(f"跳过: {error_count} 项（权限或读取错误）")
        for item in summary.get("skipped") or []:
            lines.append(f"    {item.get('path', '')}  {item.get('error', '')}")
    if summary.get("partial"):
        labels = "、".join(summary.get("limit_hits") or [])
        lines.append(f"扫描未完成（达到{labels}上限），结果只覆盖已读到的部分。")
    lines.append(
        f"参数: 列出前 {top_n} 项；超过 {days} 天且不小于 {min_label} 记为久未修改的大文件"
    )
    lines.append("")
    lines.append(f"最大的文件（前 {top_n}）")
    files = summary.get("largest_files") or []
    if not files:
        lines.append("  （没有可读的普通文件）")
    else:
        for index, item in enumerate(files, 1):
            lines.append(
                f"  {index}. {item.get('size_readable', '')}  {item.get('rel', '')}"
                f"  修改于 {item.get('modified', '')}"
            )
    lines.append("")
    lines.append(f"最大的目录（前 {top_n}）")
    directories = summary.get("largest_dirs") or []
    if not directories:
        lines.append("  （没有占用空间的子目录）")
    else:
        for index, item in enumerate(directories, 1):
            lines.append(
                f"  {index}. {item.get('size_readable', '')}  {item.get('rel', '')}"
                f"  （{item.get('file_count', 0)} 个文件）"
            )
    lines.append("")
    lines.append(f"久未修改的大文件（超过 {days} 天，不小于 {min_label}）")
    old_files = summary.get("old_large_files") or []
    if not old_files:
        lines.append(f"  未发现超过 {days} 天未修改、且不小于 {min_label} 的文件。")
    else:
        for index, item in enumerate(old_files, 1):
            lines.append(
                f"  {index}. {item.get('size_readable', '')}  {item.get('rel', '')}"
                f"  修改于 {item.get('modified', '')}"
            )
        extra = int(summary.get("old_large_count") or 0) - len(old_files)
        if extra > 0:
            lines.append(f"  另有 {extra} 个符合条件的文件未列出。")
    lines.append("")
    lines.append("建议: 本命令只生成报告，不会删除、移动或修改文件。清理前请自行确认。")
    return "\n".join(lines)


def _existing_directory(root: str) -> str:
    if not isinstance(root, str) or not root.strip() or "\x00" in root or "\n" in root or "\r" in root:
        raise ValueError("目录路径无效")
    requested = os.path.abspath(os.path.expanduser(root.strip()))
    if not os.path.exists(requested):
        raise ValueError(f"目录不存在: {root}")
    if not os.path.isdir(requested):
        raise ValueError(f"不是目录: {root}")
    return requested


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


def _filesystem_usage(path: str) -> dict:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return {"error": f"无法读取磁盘用量: {exc.__class__.__name__}"}
    total = int(usage.total)
    used = int(usage.used)
    free = int(usage.free)
    percent = round((used / total) * 100, 1) if total else 0.0
    return {
        "path": path,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent": percent,
        "total_readable": format_size(total),
        "used_readable": format_size(used),
        "free_readable": format_size(free),
    }


def _push_top(heap: list, record: dict, limit: int, seq: int) -> int:
    seq += 1
    item = (record["size_bytes"], record["rel"], seq, record)
    if len(heap) < limit:
        heapq.heappush(heap, item)
    elif item[:3] > heap[0][:3]:
        heapq.heapreplace(heap, item)
    return seq


def _take(heap: list) -> list[dict]:
    rows = [item[3] for item in heap]
    rows.sort(key=lambda rec: (-rec["size_bytes"], rec["rel"]))
    return rows


def _largest_directories(dir_bytes: dict, dir_files: dict, root_real: str, top_n: int) -> list[dict]:
    rows = []
    root_key = os.path.normcase(root_real)
    for path, size in dir_bytes.items():
        if os.path.normcase(path) == root_key or size <= 0:
            continue
        rows.append({
            "path": path,
            "rel": _relative(root_real, path),
            "size_bytes": size,
            "size_readable": format_size(size),
            "file_count": dir_files.get(path, 0),
        })
    rows.sort(key=lambda rec: (-rec["size_bytes"], rec["rel"]))
    return rows[:top_n]


def _add_to_ancestors(dir_bytes: dict, dir_files: dict, root_real: str, directory: str, size: int) -> None:
    current = directory
    root_key = os.path.normcase(root_real)
    while True:
        dir_bytes[current] = dir_bytes.get(current, 0) + size
        dir_files[current] = dir_files.get(current, 0) + 1
        if os.path.normcase(current) == root_key:
            break
        parent = os.path.dirname(current)
        if not parent or parent == current or not _same_tree(root_real, parent):
            break
        current = parent


def _classify_symlink(root_real: str, link_path: str) -> tuple[bool, OSError | None]:
    """只读链接文本。返回 (是否指向目录外, 读取链接时的错误)。"""
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


def _format_mtime(timestamp: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
    except (OverflowError, OSError, ValueError):
        return "未知"

