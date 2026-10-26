"""只读进程与监听端口巡检。

不传目录时查看本机：进程来自 ps（失败则读 /proc），监听端口来自 ss，
ss 不可用时再读 /proc/net/tcp 与 /proc/net/udp。和安全巡检一样，Linux 上不走 Windows 脚本命令。

传入样本目录时只读该目录里的 ps.txt、ss.txt 或 proc，不探测本机。
命令行里的令牌和密码会打码。权限错误会跳过。

不会结束进程，不会停止或重启服务，也不会删除或修改文件。
"""

import errno
import ipaddress
import os
import platform
import re
import stat
import subprocess
import time

from marvis.core.log_summary import redact_log_text
from marvis.utils.fs import format_size

DEFAULT_TOP = 10
DEFAULT_MAX_ENTRIES = 2000
DEFAULT_MAX_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 8.0

_TOP_MAX = 50
_ENTRIES_MAX = 20_000
_BYTES_MIN = 128
_BYTES_MAX = 2 * 1024 * 1024
_TIMEOUT_MIN = 0.2
_TIMEOUT_MAX = 30.0
_NOTE_MAX = 20
_STORED_ERRORS = 8
_COMMAND_MAX = 160
_COMMAND_SCAN_MAX = 2000
_PID_MAX = 99_999_999
_RSS_MAX = 1 << 40
_LIMIT_ORDER = ("条目", "端口", "字节", "时间")
_PS_LINUX = ["ps", "-eo", "user,pid,pcpu,rss,comm"]
_PS_DARWIN = ["ps", "-axo", "user,pid,pcpu,rss,comm"]
_SS_ARGV = ["ss", "-H", "-lntup"]
_ALLOWED_ARGV = (_PS_LINUX, _PS_DARWIN, _SS_ARGV)

_ADMIN_PORTS = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    69: "TFTP",
    445: "SMB",
    1433: "MSSQL",
    2375: "Docker",
    2376: "Docker TLS",
    3306: "MySQL",
    3389: "RDP",
    5432: "PostgreSQL",
    5900: "VNC",
    6379: "Redis",
    6443: "Kubernetes",
    9200: "Elasticsearch",
    10250: "Kubelet",
    11211: "Memcached",
    27017: "MongoDB",
}
_SUSPICIOUS_COMM = frozenset({"nc", "ncat", "netcat", "xmrig", "minerd", "cryptominer"})
_WILDCARDS = frozenset({"0.0.0.0", "::", "*", "::0"})
_KNOWN_STATES = frozenset({
    "LISTEN", "UNCONN", "ESTAB", "ESTABLISHED", "TIME-WAIT", "TIME_WAIT",
    "CLOSE-WAIT", "SYN-SENT", "SYN-RECV", "FIN-WAIT-1", "FIN-WAIT-2",
    "CLOSING", "LAST-ACK", "CLOSE", "CLOSED",
})
_PROTO_PREFIX = {"tcp": "tcp", "tcp6": "tcp", "udp": "udp", "udp6": "udp"}

_USERS = re.compile(r'users:\(\("([^"]+)"(?:,pid=|,)(\d+)')
_USERS_CHUNK = re.compile(r"\s*users:\(.*\)\s*$")
_FLAG = re.compile(
    r"(?i)(--?(?:password|passwd|pwd|secret|token|api[-_]?key|access[-_]?key))\s+\S+"
)


def inspect_processes_and_ports(
    root: str | None = None,
    top: int | None = None,
    max_entries: int | None = None,
    max_bytes: int | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    """巡检进程和监听端口。root 为空时看本机，否则只读该样本目录。"""
    source, requested, root_real = _resolve_root(root)
    top_n = _bounded_int(top, DEFAULT_TOP, 1, _TOP_MAX, "top")
    entry_cap = _bounded_int(max_entries, DEFAULT_MAX_ENTRIES, 1, _ENTRIES_MAX, "max_entries")
    byte_cap = _bounded_int(max_bytes, DEFAULT_MAX_BYTES, _BYTES_MIN, _BYTES_MAX, "max_bytes")
    timeout = _bounded_float(
        timeout_seconds, DEFAULT_TIMEOUT_SECONDS, _TIMEOUT_MIN, _TIMEOUT_MAX, "timeout_seconds"
    )
    state = _new_state(time.monotonic() + timeout, entry_cap, byte_cap)
    processes: list[dict] = []
    listeners: list[dict] = []
    overlay_root = None
    if not _expired(state):
        if source == "host":
            processes, listeners, overlay_root = _inspect_host(state)
        else:
            processes, listeners, overlay_root = _inspect_sample(root_real, state)
    return _finish(
        state,
        processes,
        listeners,
        overlay_root,
        source=source,
        requested=requested,
        root_real=root_real,
        top_n=top_n,
        entry_cap=entry_cap,
        byte_cap=byte_cap,
        timeout=timeout,
    )


def format_proc_report(summary: dict) -> str:
    """人类可读的进程与端口报告。命令行已打码，不含结束进程的操作。"""
    top_n = summary.get("top", DEFAULT_TOP)
    lines = [
        "进程与监听端口巡检报告",
        _scope_line(summary),
        "模式: 只读预览（未结束进程，未停止或重启服务，未删除、未修改文件）",
        "说明: 可疑项只是提示，不会自动结束进程。命令行里的令牌和密码已打码。",
        "数据: " + ("、".join(summary.get("backends") or []) or "无"),
    ]
    if summary.get("source") == "host":
        lines.append("范围说明: 只补充当前用户自己的命令行；其它用户只显示程序名。")
    lines.extend([
        (
            f"进程: 看到 {summary.get('process_count', 0)} 个，"
            f"下面按内存和 CPU 各列前 {top_n} 个"
        ),
        f"监听: 看到 {summary.get('listener_count', 0)} 个",
    ])
    denied = summary.get("cmdline_denied") or 0
    if denied:
        lines.append(f"命令行未读取: {denied} 个（权限不足，已保留程序名）")
    error_count = summary.get("error_count") or 0
    if error_count:
        lines.append(f"读取失败: {error_count} 项（权限或系统错误，已跳过）")
        for item in summary.get("skipped") or []:
            lines.append(f"    {item.get('path', '')}  {item.get('error', '')}")
    if summary.get("partial"):
        labels = "、".join(summary.get("limit_hits") or [])
        lines.append(f"扫描未完成（达到{labels}上限），结果只覆盖已读到的部分。")
    lines.append("")
    lines.append(f"进程（按内存，前 {top_n}）")
    _append_processes(lines, summary.get("processes_by_rss") or [])
    lines.append("")
    cpu_title = f"进程（按 CPU，前 {top_n}）"
    if not _any_cpu(summary.get("processes_by_cpu") or []):
        cpu_title += "（没有 CPU 占用数据时按内存排列）"
    lines.append(cpu_title)
    _append_processes(lines, summary.get("processes_by_cpu") or [])
    lines.append("")
    lines.append(f"监听端口（前 {top_n}，优先列出管理端口暴露在所有网卡上的项）")
    listeners = summary.get("listeners") or []
    if not listeners:
        lines.append("  未看到监听端口。")
    else:
        for index, item in enumerate(listeners, 1):
            who = item.get("process") or "-"
            pid = item.get("pid")
            pid_text = str(pid) if pid is not None else "-"
            lines.append(
                f"  {index}. {item.get('proto', '')} {_fmt_endpoint(item.get('address', ''), item.get('port', ''))}"
                f"  {who}  pid {pid_text}"
            )
    omitted = summary.get("listeners_omitted") or 0
    if omitted:
        lines.append(f"另有 {omitted} 个监听未列入上表。")
    lines.append("")
    lines.append("提示")
    notes = summary.get("notes") or []
    if not notes:
        lines.append("  未发现通配地址上的常见管理端口，也未发现可疑进程名。")
    else:
        for note in notes:
            lines.append(f"  - {note}")
    overflow = summary.get("note_overflow") or 0
    if overflow:
        lines.append(f"另有 {overflow} 条提示未列出。")
    if (
        summary.get("source") == "host"
        and not summary.get("process_count")
        and not summary.get("listener_count")
    ):
        lines.append("未从 ps、ss 或 /proc 读到数据。样本巡检请使用 --root samples/procs。")
    lines.append("")
    lines.append("建议: 本命令只生成报告，不会结束进程，不会停止或重启服务，也不会删除文件。")
    return "\n".join(lines)


def redact_cmdline(text: str) -> str:
    """打码命令行里的令牌、密码和密钥样式，并截断。"""
    if not text:
        return ""
    cleaned = redact_log_text(text[:_COMMAND_SCAN_MAX])
    cleaned = _FLAG.sub(lambda match: match.group(1) + " [redacted]", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > _COMMAND_MAX:
        cleaned = cleaned[:_COMMAND_MAX] + "…"
    return cleaned


def parse_ps_table(text: str, limit: int = _ENTRIES_MAX) -> tuple[list[dict], bool]:
    """解析 ps 表格。返回 (进程, 是否超出 limit)。"""
    rows: list[dict] = []
    seen: set[int] = set()
    overflow = False
    cap = _cap_limit(limit)
    for line in text.splitlines():
        item = _parse_ps_line(line)
        if item is None or item["pid"] in seen:
            continue
        if len(rows) >= cap:
            overflow = True
            break
        seen.add(item["pid"])
        rows.append(item)
    return rows, overflow


def parse_ss_listeners(text: str, limit: int = _ENTRIES_MAX) -> tuple[list[dict], bool]:
    """解析 ss 监听输出。同一协议、地址和端口只保留一条。"""
    rows: list[dict] = []
    seen: set[tuple] = set()
    overflow = False
    cap = _cap_limit(limit)
    for line in text.splitlines():
        item = _parse_ss_line(line)
        if item is None:
            continue
        key = (item["proto"], item["address"], item["port"])
        if key in seen:
            _fill_process(rows, key, item)
            continue
        if len(rows) >= cap:
            overflow = True
            break
        seen.add(key)
        rows.append(item)
    return rows, overflow


def parse_proc_net(text: str, proto: str, limit: int = _ENTRIES_MAX) -> tuple[list[dict], bool]:
    """解析 /proc/net/tcp 或 udp 文本。tcp 只保留 LISTEN（0A），udp 只保留 07。"""
    if proto not in {"tcp", "udp"}:
        raise ValueError("proto 必须是 tcp 或 udp")
    rows: list[dict] = []
    seen: set[tuple] = set()
    overflow = False
    cap = _cap_limit(limit)
    for line in text.splitlines():
        if "local_address" in line or not line.strip():
            continue
        item = _parse_proc_net_line(line, proto)
        if item is None:
            continue
        key = (item["proto"], item["address"], item["port"])
        if key in seen:
            continue
        if len(rows) >= cap:
            overflow = True
            break
        seen.add(key)
        rows.append(item)
    return rows, overflow


def _inspect_host(state: dict) -> tuple[list[dict], list[dict], str | None]:
    processes, _from_proc = _host_processes(state)
    listeners = [] if _expired(state) else _host_listeners(state)
    # 只给即将展示的、属于当前用户的进程补命令行。其它用户保留 ps/status 里的程序名。
    return processes, listeners, _host_proc_root()


def _host_processes(state: dict) -> tuple[list[dict], bool]:
    timeout = _command_timeout(state)
    if timeout is None:
        return [], False
    try:
        stdout, _stderr, rc = _run_readonly(_ps_argv(), timeout)
    except subprocess.TimeoutExpired:
        _remember(state, "ps", "TimeoutExpired")
        stdout, rc = "", 1
    except OSError:
        _remember(state, "ps", "unavailable")
        stdout, rc = "", 1
    if stdout.strip() and rc == 0:
        rows, overflow = parse_ps_table(stdout, state["entry_cap"])
        state["backends"].append("ps")
        if overflow:
            state["hits"].add("条目")
        return rows, False
    if _expired(state):
        return [], False
    rows = _processes_from_proc(_host_proc_root(), state, "proc")
    return rows, True


def _host_listeners(state: dict) -> list[dict]:
    timeout = _command_timeout(state)
    if timeout is None:
        return []
    try:
        stdout, _stderr, rc = _run_readonly(_SS_ARGV, timeout)
    except subprocess.TimeoutExpired:
        _remember(state, "ss", "TimeoutExpired")
        stdout, rc = "", 1
    except OSError:
        _remember(state, "ss", "unavailable")
        stdout, rc = "", 1
    if rc == 0:
        rows, overflow = parse_ss_listeners(stdout, state["entry_cap"])
        state["backends"].append("ss")
        if overflow:
            state["hits"].add("端口")
        return rows
    if _expired(state):
        return []
    return _listeners_from_proc(_host_proc_root(), state)


def _inspect_sample(root_real: str, state: dict) -> tuple[list[dict], list[dict], str | None]:
    ps_path = os.path.join(root_real, "ps.txt")
    ss_path = os.path.join(root_real, "ss.txt")
    proc_root = os.path.join(root_real, "proc")
    has_ps = os.path.lexists(ps_path)
    has_ss = os.path.lexists(ss_path)
    has_proc = os.path.lexists(proc_root)
    if not (has_ps or has_ss or has_proc):
        raise ValueError(
            "目录里没有进程或监听端口样本（需要 ps.txt、ss.txt 或 proc）。"
            "查看本机请省略 --root"
        )
    processes: list[dict] = []
    listeners: list[dict] = []
    overlay = None
    if has_ps:
        processes = _table_file(state, root_real, ps_path, "ps.txt", "process")
    elif has_proc and not _expired(state):
        if os.path.islink(proc_root):
            _remember(state, "proc", "symlink")
        else:
            processes = _processes_from_proc(proc_root, state, "proc")
            overlay = proc_root
    if _expired(state):
        return processes, listeners, overlay
    if has_ss:
        listeners = _table_file(state, root_real, ss_path, "ss.txt", "listen")
    elif has_proc and not os.path.islink(proc_root):
        listeners = _listeners_from_proc(proc_root, state)
    return processes, listeners, overlay


def _table_file(state: dict, root_real: str, path: str, label: str, kind: str) -> list[dict]:
    text, truncated, problem = _read_text_file(path, state["byte_cap"])
    rel = _relative(root_real, path)
    if problem:
        _remember(state, rel or label, problem)
        return []
    state["backends"].append(label)
    if truncated:
        state["hits"].add("字节")
    if kind == "process":
        rows, overflow = parse_ps_table(text or "", state["entry_cap"])
        if overflow:
            state["hits"].add("条目")
        return rows
    rows, overflow = parse_ss_listeners(text or "", state["entry_cap"])
    if overflow:
        state["hits"].add("端口")
    return rows


def _processes_from_proc(proc_root: str, state: dict, label: str) -> list[dict]:
    if not os.path.isdir(proc_root) or os.path.islink(proc_root):
        return []
    try:
        names = os.listdir(proc_root)
    except OSError:
        _remember(state, label, "denied")
        return []
    pids = sorted(int(name) for name in names if name.isdigit())
    rows: list[dict] = []
    for index, pid in enumerate(pids):
        if _expired(state):
            break
        if index >= state["entry_cap"]:
            state["hits"].add("条目")
            break
        item = _one_proc(proc_root, pid, state)
        if item is not None:
            rows.append(item)
    if rows or pids:
        state["backends"].append(label)
    return rows


def _one_proc(proc_root: str, pid: int, state: dict) -> dict | None:
    base = os.path.join(proc_root, str(pid))
    try:
        if os.path.islink(base) or not os.path.isdir(base):
            return None
    except OSError:
        _remember(state, f"proc/{pid}", "os")
        return None
    status_path = os.path.join(base, "status")
    text, _truncated, problem = _read_text_file(status_path, 8192)
    if problem == "missing":
        return None
    if problem:
        _remember(state, f"proc/{pid}/status", problem)
        return None
    parsed = _parse_status(text or "")
    if parsed is None:
        return None
    name, rss, uid = parsed
    cpu = None
    stat_text, _truncated, stat_problem = _read_text_file(os.path.join(base, "stat"), 1024)
    if stat_text and not stat_problem:
        cpu = _cpu_seconds(stat_text)
    return {
        "user": _user_from_uid(uid),
        "pid": pid,
        "cpu_percent": None,
        "cpu_seconds": cpu,
        "rss_kb": rss,
        "command": name,
        "suspicious": _exe_name(name) in _SUSPICIOUS_COMM,
        "uid": uid,
    }


def _listeners_from_proc(proc_root: str, state: dict) -> list[dict]:
    net_link = os.path.join(proc_root, "net")
    net = _contained_dir(proc_root, net_link)
    if net is None:
        # /proc/net 在 Linux 上通常指向 self/net，仍在 /proc 里面。
        # 指向 proc 根以外的链接不跟随。
        if os.path.islink(net_link):
            _remember(state, "proc/net", "symlink")
        return []
    rows: list[dict] = []
    seen: set[tuple] = set()
    used = False
    for name, proto in (("tcp", "tcp"), ("udp", "udp"), ("tcp6", "tcp"), ("udp6", "udp")):
        if _expired(state):
            break
        path = os.path.join(net, name)
        if not os.path.lexists(path):
            continue
        text, truncated, problem = _read_text_file(path, state["byte_cap"])
        if problem == "missing":
            continue
        if problem:
            _remember(state, f"proc/net/{name}", problem)
            continue
        used = True
        if truncated:
            state["hits"].add("字节")
        parsed, overflow = parse_proc_net(text or "", proto, state["entry_cap"])
        if overflow:
            state["hits"].add("端口")
        capped = False
        for item in parsed:
            key = (item["proto"], item["address"], item["port"])
            if key in seen:
                continue
            if len(rows) >= state["entry_cap"]:
                state["hits"].add("端口")
                capped = True
                break
            seen.add(key)
            rows.append(item)
        if capped:
            break
    if used:
        state["backends"].append("proc/net")
    return rows


def _finish(
    state: dict,
    processes: list[dict],
    listeners: list[dict],
    overlay_root: str | None,
    source: str,
    requested: str | None,
    root_real: str | None,
    top_n: int,
    entry_cap: int,
    byte_cap: int,
    timeout: float,
) -> dict:
    by_rss = _sort_rss(processes)[:top_n]
    by_cpu = _sort_cpu(processes)[:top_n]
    if overlay_root and not _expired(state):
        _overlay_cmdline(by_rss + by_cpu, overlay_root, state)
    shown_listeners = _sort_listeners(listeners)[:top_n]
    notes, note_overflow = _build_notes(listeners, processes)
    for item in processes:
        item.pop("uid", None)
    limit_hits = [name for name in _LIMIT_ORDER if name in state["hits"]]
    return {
        "source": source,
        "root": root_real,
        "requested_root": requested,
        "hostname": _hostname() if source == "host" else "",
        "top": top_n,
        "process_count": len(processes),
        "listener_count": len(listeners),
        "listeners_omitted": max(0, len(listeners) - len(shown_listeners)),
        "processes_by_rss": by_rss,
        "processes_by_cpu": by_cpu,
        "listeners": shown_listeners,
        "notes": notes,
        "note_overflow": note_overflow,
        "cmdline_denied": state["cmdline_denied"],
        "error_count": state["error_count"],
        "skipped": state["skipped"],
        "partial": bool(limit_hits),
        "limit_hits": limit_hits,
        "limits": {
            "max_entries": entry_cap,
            "max_bytes": byte_cap,
            "timeout_seconds": timeout,
        },
        "backends": list(state["backends"]),
        "preview": True,
        "deleted": False,
        "modified": False,
        "moved": False,
        "killed": False,
    }


def _overlay_cmdline(items: list[dict], proc_root: str, state: dict) -> None:
    seen: set[int] = set()
    for item in items:
        pid = item.get("pid")
        if pid in seen:
            continue
        seen.add(pid)
        if _expired(state):
            return
        if not _can_read_cmdline(item):
            continue
        path = os.path.join(proc_root, str(pid), "cmdline")
        text, problem = _read_cmdline(path)
        if problem == "denied":
            state["cmdline_denied"] += 1
            continue
        if problem == "symlink":
            _remember(state, f"proc/{pid}/cmdline", "symlink")
            continue
        if problem and problem not in {"missing", "os"}:
            _remember(state, f"proc/{pid}/cmdline", problem)
            continue
        if text:
            item["command"] = redact_cmdline(text)
            item["suspicious"] = _exe_name(item["command"]) in _SUSPICIOUS_COMM


def _build_notes(listeners: list[dict], processes: list[dict]) -> tuple[list[str], int]:
    notes: list[str] = []
    risky = [item for item in listeners if item.get("risky")]
    risky.sort(key=lambda item: (item["port"], item["proto"], item["address"]))
    for item in risky:
        note = _listener_note(item)
        if note:
            notes.append(note)
    seen: set[int] = set()
    suspicious = [item for item in processes if item.get("suspicious")]
    suspicious.sort(key=lambda item: item["pid"])
    for item in suspicious:
        if item["pid"] in seen:
            continue
        seen.add(item["pid"])
        note = _process_note(item)
        if note:
            notes.append(note)
    overflow = max(0, len(notes) - _NOTE_MAX)
    return notes[:_NOTE_MAX], overflow


def _listener_note(item: dict) -> str | None:
    if not item.get("risky"):
        return None
    label = _ADMIN_PORTS.get(item["port"], "管理端口")
    who = item.get("process") or "未知进程"
    return (
        f"{item['proto']} {_fmt_endpoint(item['address'], item['port'])}（{who}）"
        f"监听所有网卡，属于常见管理端口 {label}。仅供查看，不会结束进程。"
    )


def _process_note(item: dict) -> str | None:
    if not item.get("suspicious"):
        return None
    name = _exe_name(item.get("command") or "") or "未知"
    return (
        f"进程 {name}（pid {item['pid']}）名称像网络调试或挖矿工具。"
        "仅供查看，不会结束进程。"
    )


def _parse_ps_line(line: str) -> dict | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    parts = raw.split(None, 4)
    if len(parts) < 4:
        return None
    user, pid_s, cpu_s, rss_s = parts[:4]
    command = parts[4] if len(parts) > 4 else ""
    if not pid_s.isdigit():
        return None
    pid = int(pid_s)
    if pid < 0 or pid > _PID_MAX:
        return None
    try:
        cpu = float(cpu_s)
    except ValueError:
        return None
    if cpu < 0 or cpu > 1_000_000:
        return None
    if not rss_s.isdigit():
        return None
    rss = int(rss_s)
    if rss < 0 or rss > _RSS_MAX:
        return None
    command = redact_cmdline(command)
    return {
        "user": _clean_user(user),
        "pid": pid,
        "cpu_percent": round(cpu, 1),
        "cpu_seconds": None,
        "rss_kb": rss,
        "command": command,
        "suspicious": _exe_name(command) in _SUSPICIOUS_COMM,
    }


def _parse_ss_line(line: str) -> dict | None:
    if not line.strip() or line.lower().startswith("netid"):
        return None
    match = _USERS.search(line)
    process = match.group(1) if match else ""
    pid = int(match.group(2)) if match else None
    if pid is not None and (pid < 0 or pid > _PID_MAX):
        pid = None
    body = _USERS_CHUNK.sub("", line).strip()
    parts = body.split()
    if len(parts) < 3:
        return None
    idx = 0
    proto = _PROTO_PREFIX.get(parts[0].lower())
    if proto:
        idx = 1
    state = ""
    if idx < len(parts) and parts[idx].upper() in _KNOWN_STATES:
        state = parts[idx].upper()
        idx += 1
    if proto is None:
        if state == "LISTEN":
            proto = "tcp"
        elif state == "UNCONN":
            proto = "udp"
        else:
            return None
    if proto == "tcp" and state not in {"", "LISTEN"}:
        return None
    if proto == "udp" and state not in {"", "UNCONN", "LISTEN"}:
        return None
    local = parts[idx + 2] if len(parts) > idx + 2 else ""
    parsed = _split_endpoint(local)
    if parsed is None and idx < len(parts):
        parsed = _split_endpoint(parts[idx])
    if parsed is None:
        return None
    host, port = parsed
    return _mark_listener({
        "proto": proto,
        "address": host,
        "port": port,
        "pid": pid,
        "process": process,
    })


def _parse_proc_net_line(line: str, proto: str) -> dict | None:
    parts = line.split()
    if len(parts) < 4 or ":" not in parts[1]:
        return None
    state = parts[3].upper()
    if proto == "tcp" and state != "0A":
        return None
    if proto == "udp" and state != "07":
        return None
    ip_hex, _, port_hex = parts[1].partition(":")
    try:
        address = _decode_proc_ip(ip_hex)
        port = int(port_hex, 16)
    except ValueError:
        return None
    if address is None or port < 0 or port > 65535:
        return None
    return _mark_listener({
        "proto": proto,
        "address": address,
        "port": port,
        "pid": None,
        "process": "",
    })


def _decode_proc_ip(ip_hex: str) -> str | None:
    if len(ip_hex) == 8:
        raw = bytes.fromhex(ip_hex)
        return ".".join(str(byte) for byte in reversed(raw))
    if len(ip_hex) == 32:
        raw = bytes.fromhex(ip_hex)
        words = [raw[index:index + 4][::-1] for index in range(0, 16, 4)]
        return ipaddress.IPv6Address(b"".join(words)).compressed
    return None


def _mark_listener(item: dict) -> dict:
    item["process"] = _clean_process(item.get("process") or "")
    item["risky"] = _is_wildcard(item["address"]) and item["port"] in _ADMIN_PORTS
    return item


def _split_endpoint(local: str) -> tuple[str, int] | None:
    text = local.strip()
    if not text or text == "*":
        return None
    host, sep, port_s = text.rpartition(":")
    if sep != ":":
        return None
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    host = host.split("%", 1)[0].strip()
    if not port_s.isdigit():
        return None
    port = int(port_s)
    if port < 0 or port > 65535:
        return None
    return host or "*", port


def _is_wildcard(address: str) -> bool:
    host = address.strip().strip("[]").split("%", 1)[0].lower()
    return host in _WILDCARDS


def _fill_process(rows: list[dict], key: tuple, item: dict) -> None:
    if not item.get("process"):
        return
    for row in rows:
        if (row["proto"], row["address"], row["port"]) != key:
            continue
        if not row.get("process"):
            row["process"] = item["process"]
            row["pid"] = item.get("pid")
        return


def _parse_status(text: str) -> tuple[str, int, int | None] | None:
    name = ""
    rss = None
    uid = None
    for line in text.splitlines():
        if line.startswith("Name:"):
            value = line.split(":", 1)[1].strip()
            name = value.split()[0] if value else ""
        elif line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                rss = int(parts[1])
        elif line.startswith("Uid:") and uid is None:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                uid = int(parts[1])
    if not name:
        return None
    if rss is None or rss < 0:
        rss = 0
    if rss > _RSS_MAX:
        rss = _RSS_MAX
    return name, rss, uid


def _cpu_seconds(text: str) -> float | None:
    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 1:].split()
    if len(fields) < 13:
        return None
    try:
        ticks = int(fields[11]) + int(fields[12])
    except ValueError:
        return None
    hz = 100
    try:
        hz = int(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, OSError, TypeError, ValueError):
        hz = 100
    if hz <= 0:
        hz = 100
    if ticks < 0:
        return None
    return round(ticks / hz, 3)


def _read_cmdline(path: str) -> tuple[str | None, str | None]:
    data, kind = _read_bytes_nofollow(path, 4096)
    if kind:
        return None, kind
    if not data:
        return None, "missing"
    text = data.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    if not text:
        return None, "missing"
    return text, None


def _read_text_file(path: str, max_bytes: int) -> tuple[str | None, bool, str | None]:
    data, kind = _read_bytes_nofollow(path, max_bytes + 1)
    if kind:
        return None, False, kind
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]
    if b"\x00" in data:
        return None, truncated, "binary"
    text = data.decode("utf-8", errors="replace")
    if truncated:
        newline = text.rfind("\n")
        text = text[:newline] if newline != -1 else ""
    return text, truncated, None


def _read_bytes_nofollow(path: str, max_bytes: int) -> tuple[bytes | None, str | None]:
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None:
        flags |= nofollow
    elif os.path.islink(path):
        return None, "symlink"
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        if exc.errno == errno.ELOOP or (exc.errno == errno.EPERM and os.path.islink(path)):
            return None, "symlink"
        if exc.errno in {errno.ENOENT, errno.ENOTDIR}:
            return None, "missing"
        if exc.errno in {errno.EACCES, errno.EPERM}:
            return None, "denied"
        return None, "os"
    try:
        info = os.fstat(fd)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            return None, "symlink"
        chunks = []
        total = 0
        while total < max_bytes:
            part = os.read(fd, min(65536, max_bytes - total))
            if not part:
                break
            chunks.append(part)
            total += len(part)
        return b"".join(chunks), None
    except OSError:
        return None, "os"
    finally:
        os.close(fd)


def _run_readonly(argv: list[str], timeout: float) -> tuple[str, str, int]:
    """只运行固定的 ps / ss。其它程序直接拒绝，不会启动。"""
    if list(argv) not in _ALLOWED_ARGV:
        raise ValueError("只允许只读的 ps 或 ss")
    proc = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
        check=False,
    )
    return proc.stdout or "", proc.stderr or "", int(proc.returncode)


def _ps_argv() -> list[str]:
    if platform.system() == "Darwin":
        return list(_PS_DARWIN)
    return list(_PS_LINUX)


def _host_proc_root() -> str:
    return "/proc"


def _command_timeout(state: dict) -> float | None:
    remaining = state["deadline"] - time.monotonic()
    if remaining < 0.2:
        state["hits"].add("时间")
        return None
    return min(3.0, remaining)


def _sort_rss(processes: list[dict]) -> list[dict]:
    return sorted(processes, key=lambda item: (-item["rss_kb"], -_cpu_rank(item), item["pid"]))


def _sort_cpu(processes: list[dict]) -> list[dict]:
    return sorted(processes, key=lambda item: (-_cpu_rank(item), -item["rss_kb"], item["pid"]))


def _sort_listeners(listeners: list[dict]) -> list[dict]:
    return sorted(
        listeners,
        key=lambda item: (
            0 if item.get("risky") else 1,
            item["port"],
            item["proto"],
            item["address"],
        ),
    )


def _cpu_rank(item: dict) -> float:
    if item.get("cpu_percent") is not None:
        return float(item["cpu_percent"])
    if item.get("cpu_seconds") is not None:
        return float(item["cpu_seconds"])
    return -1.0


def _any_cpu(processes: list[dict]) -> bool:
    return any(item.get("cpu_percent") is not None or item.get("cpu_seconds") is not None for item in processes)


def _append_processes(lines: list[str], rows: list[dict]) -> None:
    if not rows:
        lines.append("  未看到进程。")
        return
    for index, item in enumerate(rows, 1):
        pid = item.get("pid")
        user = item.get("user") or "-"
        command = item.get("command") or ""
        lines.append(
            f"  {index}. RSS {_fmt_rss(item)}  CPU {_fmt_cpu(item)}  pid {pid}  {user}  {command}"
        )


def _fmt_rss(item: dict) -> str:
    kb = int(item.get("rss_kb") or 0)
    if kb < 0:
        kb = 0
    return format_size(kb * 1024)


def _fmt_endpoint(address: str, port) -> str:
    text = str(address or "")
    if ":" in text:
        return f"[{text}]:{port}"
    return f"{text}:{port}"


def _fmt_cpu(item: dict) -> str:
    if item.get("cpu_percent") is not None:
        return f"{float(item['cpu_percent']):.1f}%"
    if item.get("cpu_seconds") is not None:
        return f"{float(item['cpu_seconds']):.1f}s"
    return "未知"


def _scope_line(summary: dict) -> str:
    if summary.get("source") == "sample":
        return f"范围: 样本 {summary.get('root', '')}"
    host = summary.get("hostname") or ""
    return f"范围: 本机（{host}）" if host else "范围: 本机"


def _exe_name(command: str) -> str:
    if not command:
        return ""
    first = command.split(None, 1)[0].strip("\"'")
    first = first.replace("\\", "/").rsplit("/", 1)[-1]
    if first.endswith(":"):
        first = first[:-1]
    return first.lower()


def _clean_user(text: str) -> str:
    cleaned = "".join(ch for ch in text if ch.isprintable())[:32]
    return cleaned or "-"


def _clean_process(text: str) -> str:
    cleaned = redact_cmdline(text)
    return cleaned[:64]


def _can_read_cmdline(item: dict) -> bool:
    """只读当前用户自己的命令行。其它用户停在 ps / status 已经给出的程序名。"""
    uid = item.get("uid")
    try:
        current = os.geteuid()
    except AttributeError:
        return False
    if isinstance(uid, int):
        return uid == current
    owner = _current_user()
    return bool(owner) and item.get("user") == owner


def _current_user() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.geteuid()).pw_name
    except (AttributeError, ImportError, KeyError, OSError, OverflowError):
        return ""


def _user_from_uid(uid: int | None) -> str:
    if uid is None:
        return "-"
    try:
        import pwd
        return _clean_user(pwd.getpwuid(uid).pw_name)
    except (ImportError, KeyError, OSError, OverflowError):
        return str(uid)


def _hostname() -> str:
    try:
        name = platform.node()
    except Exception:
        return ""
    return "".join(ch for ch in name if ch.isprintable())[:80]


def _resolve_root(root: str | None) -> tuple[str, str | None, str | None]:
    if root is None or (isinstance(root, str) and not root.strip()):
        return "host", None, None
    if not isinstance(root, str):
        raise ValueError("目录路径无效")
    requested = _existing_directory(root)
    root_real = os.path.realpath(requested)
    if not os.path.isdir(root_real):
        raise ValueError(f"不是目录: {root}")
    return "sample", requested, root_real


def _existing_directory(root: str) -> str:
    if not isinstance(root, str) or not root.strip() or "\x00" in root or "\n" in root or "\r" in root:
        raise ValueError("目录路径无效")
    requested = os.path.abspath(os.path.expanduser(root.strip()))
    if not os.path.exists(requested):
        raise ValueError(f"目录不存在: {root}")
    if os.path.islink(requested):
        # realpath 只解析用户点名的样本目录本身，不跟随其中的 ps.txt / cmdline。
        pass
    if not os.path.isdir(requested):
        raise ValueError(f"不是目录: {root}")
    return requested


def _contained_dir(proc_root: str, path: str) -> str | None:
    """返回可读取的目录。符号链接仅在目标仍位于 proc_root 内时才接受。"""
    if os.path.islink(path):
        try:
            raw = os.readlink(path)
        except OSError:
            return None
        if not raw or "\x00" in raw:
            return None
        joined = raw if os.path.isabs(raw) else os.path.join(os.path.dirname(path), raw)
        try:
            target = os.path.realpath(joined)
        except OSError:
            return None
        root_real = os.path.realpath(proc_root)
        if not _same_tree(root_real, target) or not os.path.isdir(target):
            return None
        return target
    if os.path.isdir(path):
        return path
    return None


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


def _new_state(deadline: float, entry_cap: int, byte_cap: int) -> dict:
    return {
        "deadline": deadline,
        "entry_cap": entry_cap,
        "byte_cap": byte_cap,
        "hits": set(),
        "skipped": [],
        "error_count": 0,
        "cmdline_denied": 0,
        "backends": [],
    }


def _expired(state: dict) -> bool:
    if time.monotonic() >= state["deadline"]:
        state["hits"].add("时间")
        return True
    return False


def _remember(state: dict, path: str, kind: str) -> None:
    state["error_count"] += 1
    if len(state["skipped"]) < _STORED_ERRORS:
        state["skipped"].append({"path": path, "error": kind})


def _cap_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return _ENTRIES_MAX
    if value < 1:
        return 1
    return min(value, _ENTRIES_MAX)


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
