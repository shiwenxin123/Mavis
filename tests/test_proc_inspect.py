import json
import os
import platform
import subprocess
import sys

import pytest

from marvis.core.proc_inspect import (
    _run_readonly,
    format_proc_report,
    inspect_processes_and_ports,
    parse_proc_net,
    parse_ps_table,
    parse_ss_listeners,
    redact_cmdline,
)
from marvis.core.workflow import create_workflow, run_builtin_template, run_workflow
from marvis.mcp.tools import execute_tool

SAMPLE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "samples", "procs"))
FIXTURES = os.path.join(SAMPLE, "fixtures")
FORBIDDEN = (
    "super-secret-value",
    "sk-FAKEKEY1234567890abcd",
    "hunter2-fixture",
    "do-not-print-this",
    "ABOUT_ONLY_SECRET",
    "SECOND-SECRET-VALUE",
    "OTHER-USER-SECRET",
    "eyJhbGciOi",
)


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "marvis", *args],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )


def _snapshot(root):
    found = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in filenames:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            st = os.lstat(path)
            with open(path, "rb") as handle:
                found[path] = (st.st_mtime_ns, st.st_size, handle.read())
    return found


def _blob(result) -> str:
    return json.dumps(result, ensure_ascii=False)


def _write_status(directory, name, rss_kb, uid):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "status").write_text(
        f"Name:\t{name}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\nVmRSS:\t {rss_kb} kB\n",
        encoding="utf-8",
    )
    (directory / "stat").write_text(
        f"{directory.name} ({name}) S 0 1 1 0 -1 0 0 0 0 0 10 20 0 0 20 0 1 0 1 1 1\n",
        encoding="utf-8",
    )


def test_redact_cmdline_hides_token_like_fragments():
    assigned = redact_cmdline("python worker --token=super-secret-value")
    assert assigned == "python worker --token=[redacted]"
    spaced = redact_cmdline("python -m app --password hunter2-fixture --api-key sk-FAKEKEY1234567890abcd")
    assert "hunter2-fixture" not in spaced
    assert "sk-FAKEKEY1234567890abcd" not in spaced
    assert "--password [redacted]" in spaced
    jwt = redact_cmdline("session eyJhbGciOi.eyJzdWIiOi.SflKxwRJSMeK")
    assert "eyJhbGciOi" not in jwt
    bearer = redact_cmdline("curl -H Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789")
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in bearer


def _read_fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def test_parsers_cover_ss_and_proc_net_fixtures():
    ss_rows, overflow = parse_ss_listeners(_read_fixture("ss_noproto.txt"))
    assert overflow is False
    assert [(item["proto"], item["address"], item["port"]) for item in ss_rows] == [
        ("tcp", "0.0.0.0", 22),
        ("tcp", "10.1.2.3", 443),
        ("udp", "0.0.0.0", 69),
        ("tcp", "0.0.0.0", 8080),
    ]
    assert ss_rows[0]["risky"] is True
    assert ss_rows[1]["risky"] is False
    assert ss_rows[2]["risky"] is True
    assert ss_rows[3]["risky"] is False

    tcp_text = _read_fixture("proc_net_tcp.txt")
    tcp_rows, tcp_overflow = parse_proc_net(tcp_text, "tcp")
    assert tcp_overflow is False
    assert [(item["address"], item["port"], item["risky"]) for item in tcp_rows] == [
        ("0.0.0.0", 22, True),
        ("127.0.0.1", 6379, False),
    ]
    from marvis.core.security_audit import _parse_proc_net_tcp

    tcp_path = os.path.join(FIXTURES, "proc_net_tcp.txt")
    theirs = {(item["address"], item["port"]) for item in _parse_proc_net_tcp(tcp_path)}
    assert {(item["address"], item["port"]) for item in tcp_rows} == theirs

    udp_rows, _ = parse_proc_net(_read_fixture("proc_net_udp.txt"), "udp")
    assert [(item["address"], item["port"], item["risky"]) for item in udp_rows] == [
        ("0.0.0.0", 69, True),
        ("127.0.0.1", 53, False),
    ]
    tcp6_rows, _ = parse_proc_net(_read_fixture("proc_net_tcp6.txt"), "tcp")
    assert [(item["address"], item["risky"]) for item in tcp6_rows] == [("::", True), ("::1", False)]
    assert tcp6_rows[0]["port"] == 22
    assert tcp6_rows[1]["port"] == 22


def test_ps_table_redacts_and_marks_suspicious_names():
    with open(os.path.join(SAMPLE, "ps.txt"), encoding="utf-8") as handle:
        rows, overflow = parse_ps_table(handle.read())
    assert overflow is False
    by_pid = {item["pid"]: item for item in rows}
    assert by_pid[42]["command"] == "python worker --token=[redacted]"
    assert by_pid[42]["rss_kb"] == 81920
    assert by_pid[42]["cpu_percent"] == 25.0
    assert "sk-FAKEKEY" not in by_pid[99]["command"]
    assert "hunter2-fixture" not in by_pid[99]["command"]
    assert by_pid[99]["suspicious"] is False
    assert by_pid[3]["suspicious"] is True
    assert by_pid[1]["suspicious"] is False


def test_sample_cli_is_read_only_and_redacts():
    before = _snapshot(SAMPLE)
    listed = _run("workflow", "templates")
    assert listed.returncode == 0
    assert "进程与监听端口巡检" in listed.stdout
    assert "可直接运行" in listed.stdout
    assert "samples/procs" in listed.stdout
    assert "procs" in listed.stdout
    assert "listeners" in listed.stdout

    human = _run("workflow", "run", "--template", "进程与监听端口巡检", "--root", SAMPLE)
    assert human.returncode == 0, human.stderr
    assert "只读预览" in human.stdout
    assert "未结束进程" in human.stdout
    assert "范围: 样本" in human.stdout
    assert "80.0 MB" in human.stdout
    assert "25.0%" in human.stdout
    assert "tcp 0.0.0.0:22" in human.stdout
    assert "tcp [::]:22" in human.stdout
    assert ":::22" not in human.stdout
    assert "udp 0.0.0.0:69" in human.stdout
    assert "127.0.0.1:5432" in human.stdout
    assert "--token=[redacted]" in human.stdout
    assert "不会结束进程" in human.stdout
    notes = human.stdout.split("\n提示\n", 1)[1].split("\n建议:", 1)[0]
    assert "0.0.0.0:22" in notes
    assert "SSH" in notes
    assert "::" in notes
    assert "69" in notes
    assert "进程 nc" in notes
    assert "5432" not in notes
    assert "8080" not in notes
    assert len(human.stdout) < 8000
    for secret in FORBIDDEN:
        assert secret not in human.stdout
    assert _snapshot(SAMPLE) == before

    machine = _run(
        "workflow", "run", "--template", "procs", "--root", SAMPLE, "--top", "10", "--json",
    )
    assert machine.returncode == 0, machine.stderr
    payload = json.loads(machine.stdout)
    assert payload["template"] == "进程与监听端口巡检"
    assert payload["source"] == "sample"
    assert payload["preview"] is True
    assert payload["deleted"] is False
    assert payload["modified"] is False
    assert payload["moved"] is False
    assert payload["killed"] is False
    assert payload["partial"] is False
    assert payload["top"] == 10
    assert payload["process_count"] == 5
    assert payload["listener_count"] == 5
    assert payload["listeners_omitted"] == 0
    assert payload["backends"] == ["ps.txt", "ss.txt"]
    assert [item["pid"] for item in payload["processes_by_rss"]] == [42, 7, 1, 99, 3]
    assert [item["pid"] for item in payload["processes_by_cpu"]] == [42, 7, 99, 1, 3]
    listeners = {(item["proto"], item["address"], item["port"], item["risky"]) for item in payload["listeners"]}
    assert ("tcp", "0.0.0.0", 22, True) in listeners
    assert ("tcp", "::", 22, True) in listeners
    assert ("udp", "0.0.0.0", 69, True) in listeners
    assert ("tcp", "127.0.0.1", 5432, False) in listeners
    assert ("tcp", "127.0.0.1", 8080, False) in listeners
    rendered = json.dumps(payload, ensure_ascii=False)
    for secret in FORBIDDEN:
        assert secret not in rendered

    for alias in ("ports", "listeners"):
        alias_run = _run("workflow", "run", "--template", alias, "--root", SAMPLE, "--json")
        assert alias_run.returncode == 0, alias_run.stderr
        assert json.loads(alias_run.stdout)["listener_count"] == 5


def test_top_limits_lists_but_keeps_risk_notes():
    summary = inspect_processes_and_ports(SAMPLE, top=1)
    assert summary["processes_by_rss"][0]["pid"] == 42
    assert summary["processes_by_cpu"][0]["pid"] == 42
    assert len(summary["processes_by_rss"]) == 1
    assert len(summary["listeners"]) == 1
    assert summary["listeners"][0]["address"] == "0.0.0.0"
    assert summary["listeners"][0]["port"] == 22
    assert summary["listeners_omitted"] == 4
    notes = "\n".join(summary["notes"])
    assert "0.0.0.0:22" in notes
    assert "69" in notes
    assert "进程 nc" in notes
    assert "5432" not in notes
    report = format_proc_report(summary)
    assert "另有 4 个监听未列入上表" in report
    assert "前 1" in report


def test_proc_tree_skips_other_users_secrets_and_honors_caps(tmp_path):
    proc = tmp_path / "proc"
    uid = os.geteuid()
    other = 1 if uid != 1 else 2
    mine = proc / "4"
    _write_status(mine, "python", 4096, uid)
    (mine / "cmdline").write_bytes(b"python\0--token=super-secret-value\0")
    (mine / "environ").write_bytes(b"PASSWORD=OTHER-USER-SECRET\0")
    theirs = proc / "8"
    _write_status(theirs, "hidden", 8192, other)
    (theirs / "cmdline").write_bytes(b"hidden\0--token=OTHER-USER-SECRET\0")
    secret_link = tmp_path / "outside-secret.txt"
    secret_link.write_text("SECOND-SECRET-VALUE\n", encoding="utf-8")
    linked = proc / "9"
    _write_status(linked, "linked", 1024, uid)
    os.symlink(secret_link, linked / "cmdline")

    summary = inspect_processes_and_ports(str(tmp_path), top=10)
    blob = _blob(summary)
    assert summary["source"] == "sample"
    assert summary["process_count"] == 3
    assert "super-secret-value" not in blob
    assert "--token=[redacted]" in blob
    assert "OTHER-USER-SECRET" not in blob
    assert "SECOND-SECRET-VALUE" not in blob
    assert "PASSWORD" not in blob
    by_pid = {item["pid"]: item for item in summary["processes_by_rss"]}
    assert by_pid[4]["command"].startswith("python")
    assert by_pid[8]["command"] == "hidden"
    assert by_pid[9]["command"] == "linked"
    assert any(item.get("error") == "symlink" for item in summary["skipped"])
    assert summary["backends"] == ["proc"]
    assert "proc/net" not in summary["backends"]

    capped = inspect_processes_and_ports(str(tmp_path), max_entries=1)
    assert capped["partial"] is True
    assert "条目" in capped["limit_hits"]
    assert capped["process_count"] == 1
    assert capped["processes_by_rss"][0]["pid"] == 4
    assert "OTHER-USER-SECRET" not in _blob(capped)
    assert "SECOND-SECRET-VALUE" not in _blob(capped)


def test_ps_file_wins_and_symlink_is_not_followed(tmp_path):
    root = tmp_path / "sample"
    root.mkdir()
    secret = tmp_path / "secret-ps.txt"
    secret.write_text(
        "USER PID %CPU RSS COMMAND\nroot 1 1 10 python --token=super-secret-value\n",
        encoding="utf-8",
    )
    os.symlink(secret, root / "ps.txt")
    (root / "ss.txt").write_text(
        "tcp LISTEN 0 128 127.0.0.1:8080 0.0.0.0:*\n",
        encoding="utf-8",
    )
    proc = root / "proc" / "3"
    _write_status(proc, "xmrig", 99999, os.geteuid())
    (proc / "cmdline").write_bytes(b"xmrig\0--token=OTHER-USER-SECRET\0")

    summary = inspect_processes_and_ports(str(root))
    blob = _blob(summary)
    assert summary["process_count"] == 0
    assert summary["listener_count"] == 1
    assert summary["listeners"][0]["port"] == 8080
    assert summary["listeners"][0]["risky"] is False
    assert "super-secret-value" not in blob
    assert "OTHER-USER-SECRET" not in blob
    assert "xmrig" not in blob
    assert any(item.get("path") == "ps.txt" and item.get("error") == "symlink" for item in summary["skipped"])


def test_ss_file_wins_over_proc_net(tmp_path):
    (tmp_path / "ss.txt").write_text(
        "tcp LISTEN 0 128 127.0.0.1:9 0.0.0.0:*\n",
        encoding="utf-8",
    )
    net = tmp_path / "proc" / "net"
    net.mkdir(parents=True)
    (net / "tcp").write_text(
        "  sl  local_address rem_address st\n"
        "   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 1\n",
        encoding="utf-8",
    )
    summary = inspect_processes_and_ports(str(tmp_path))
    assert summary["listener_count"] == 1
    assert summary["listeners"][0]["port"] == 9
    assert summary["backends"] == ["ss.txt"]
    assert all(item["port"] != 22 for item in summary["listeners"])


def test_limits_timeout_and_invalid_paths(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    (work / "ps.txt").write_text(
        "USER PID %CPU RSS COMMAND\nroot 1 1.0 1024 init\n" + ("x" * 5000),
        encoding="utf-8",
    )
    truncated = inspect_processes_and_ports(str(work), max_bytes=128)
    assert truncated["partial"] is True
    assert "字节" in truncated["limit_hits"]
    assert truncated["process_count"] == 1
    assert truncated["killed"] is False

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="没有进程或监听端口样本"):
        inspect_processes_and_ports(str(empty))
    with pytest.raises(ValueError, match="无效"):
        inspect_processes_and_ports("bad\x00path")
    with pytest.raises(ValueError, match="目录不存在"):
        inspect_processes_and_ports(str(tmp_path / "missing"))
    a_file = tmp_path / "file.txt"
    a_file.write_text("x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不是目录"):
        inspect_processes_and_ports(str(a_file))
    with pytest.raises(ValueError, match="top 需在"):
        inspect_processes_and_ports(SAMPLE, top=0)
    with pytest.raises(ValueError, match="必须是整数"):
        inspect_processes_and_ports(SAMPLE, top=True)
    with pytest.raises(ValueError, match="proto 必须是"):
        parse_proc_net("x", "icmp")

    calls = {"n": 0}

    def fake_clock():
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 10**9

    monkeypatch.setattr("marvis.core.proc_inspect.time.monotonic", fake_clock)
    timed = inspect_processes_and_ports(str(work))
    assert timed["partial"] is True
    assert "时间" in timed["limit_hits"]
    assert timed["process_count"] == 0


def test_readonly_runner_rejects_anything_but_ps_or_ss(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError(args)

    monkeypatch.setattr(subprocess, "run", boom)
    for argv in (
        ["powershell", "-Command", "Get-Process"],
        ["kill", "-TERM", "1"],
        ["systemctl", "stop", "ssh"],
        ["ss", "-K", "-lnt"],
        ["ps", "-eo", "args"],
    ):
        with pytest.raises(ValueError, match="只允许只读"):
            _run_readonly(argv, 1.0)

    source = open(
        os.path.join(os.path.dirname(__file__), "..", "marvis", "core", "proc_inspect.py"),
        encoding="utf-8",
    ).read().lower()
    assert "powershell" not in source
    assert "systemctl" not in source
    assert "os.kill" not in source
    assert "shell=true" not in source


def test_sample_workflow_does_not_spawn_or_touch_host_proc(monkeypatch):
    calls = []

    def track(*args, **kwargs):
        calls.append(args)
        raise AssertionError("样本巡检不应启动进程")

    def no_host_proc():
        raise AssertionError("样本巡检不应读取本机 /proc")

    monkeypatch.setattr(subprocess, "run", track)
    monkeypatch.setattr("marvis.core.proc_inspect._host_proc_root", no_host_proc)
    report = run_builtin_template("procs", {"root": SAMPLE, "top": 10})
    assert "error" not in report
    assert report["killed"] is False
    assert report["process_count"] == 5
    assert calls == []
    monkeypatch.undo()


def test_host_mode_uses_only_ps_and_ss_then_proc(monkeypatch, tmp_path):
    proc = tmp_path / "proc"
    net = proc / "net"
    net.mkdir(parents=True)
    (net / "tcp").write_text(
        "  sl  local_address rem_address st\n"
        "   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 1\n",
        encoding="utf-8",
    )
    uid = os.geteuid()
    mine = proc / "6"
    _write_status(mine, "python", 2048, uid)
    (mine / "cmdline").write_bytes(b"python\0--password\0hunter2-fixture\0")
    calls = []

    def fake_run(argv, timeout):
        calls.append(list(argv))
        assert timeout > 0
        if argv[0] == "ps":
            return "", "missing", 1
        if argv[0] == "ss":
            return "", "missing", 1
        raise AssertionError(argv)

    monkeypatch.setattr("marvis.core.proc_inspect._run_readonly", fake_run)
    monkeypatch.setattr("marvis.core.proc_inspect._host_proc_root", lambda: str(proc))
    summary = inspect_processes_and_ports(None, top=5)
    assert summary["source"] == "host"
    assert summary["root"] is None
    assert summary["killed"] is False
    assert calls[0][0] == "ps"
    assert calls[1] == ["ss", "-H", "-lntup"]
    if platform.system() == "Darwin":
        assert calls[0] == ["ps", "-axo", "user,pid,pcpu,rss,comm"]
    else:
        assert calls[0] == ["ps", "-eo", "user,pid,pcpu,rss,comm"]
    assert summary["process_count"] == 1
    assert summary["listener_count"] == 1
    assert summary["listeners"][0]["port"] == 22
    assert summary["listeners"][0]["risky"] is True
    assert "hunter2-fixture" not in _blob(summary)
    assert "--password [redacted]" in summary["processes_by_rss"][0]["command"]
    assert summary["backends"] == ["proc", "proc/net"]
    report = format_proc_report(summary)
    assert "范围: 本机" in report
    assert "不会结束进程" in report


def test_cli_flags_output_and_mcp(tmp_path, monkeypatch):
    missing = tmp_path / "missing"
    absent = _run("workflow", "run", "--template", "procs", "--root", str(missing))
    assert absent.returncode == 1
    assert "目录不存在" in absent.stderr

    injected = _run(
        "workflow", "run", "--template", "listeners",
        "--root", str(tmp_path) + "; touch pwned",
    )
    assert injected.returncode == 1
    assert not (tmp_path / "pwned").exists()
    assert not os.path.exists("pwned")

    bad_top = _run("workflow", "run", "--template", "ports", "--root", SAMPLE, "--top", "0")
    assert bad_top.returncode == 1
    assert "top 需在" in bad_top.stderr

    output = tmp_path / "proc-report.txt"
    written = _run(
        "workflow", "run", "--template", "进程与监听端口巡检",
        "--root", SAMPLE, "--output", str(output),
    )
    assert written.returncode == 0, written.stderr
    text = output.read_text(encoding="utf-8")
    assert "只读预览" in text
    assert "报告已写入" in text
    assert "super-secret-value" not in text
    again = _run(
        "workflow", "run", "--template", "procs",
        "--root", SAMPLE, "--output", str(output),
    )
    assert again.returncode == 1
    assert "未覆盖" in again.stderr

    fresh = json.loads(execute_tool("run_workflow", {
        "template": "listeners",
        "root": SAMPLE,
        "top": 2,
    }))
    assert fresh["template"] == "进程与监听端口巡检"
    assert fresh["top"] == 2
    assert fresh["killed"] is False
    assert fresh["preview"] is True
    assert len(fresh["listeners"]) == 2
    assert "只读预览" in fresh["report"]
    assert "super-secret-value" not in json.dumps(fresh, ensure_ascii=False)

    captured = {}

    def fake_inspect(root=None, top=None, max_entries=None, max_bytes=None, timeout_seconds=None):
        captured["root"] = root
        captured["top"] = top
        return {
            "source": "host",
            "root": None,
            "requested_root": None,
            "hostname": "unit",
            "top": 3,
            "process_count": 0,
            "listener_count": 0,
            "listeners_omitted": 0,
            "processes_by_rss": [],
            "processes_by_cpu": [],
            "listeners": [],
            "notes": [],
            "note_overflow": 0,
            "cmdline_denied": 0,
            "error_count": 0,
            "skipped": [],
            "partial": False,
            "limit_hits": [],
            "limits": {},
            "backends": [],
            "preview": True,
            "deleted": False,
            "modified": False,
            "moved": False,
            "killed": False,
        }

    monkeypatch.setattr("marvis.core.proc_inspect.inspect_processes_and_ports", fake_inspect)
    host_report = run_builtin_template("ports", {"top": 3})
    assert captured["root"] is None
    assert captured["top"] == 3
    assert host_report["source"] == "host"
    assert host_report["killed"] is False
    assert "范围: 本机" in host_report["report"]
    monkeypatch.undo()

    store = tmp_path / "workflows"
    monkeypatch.setattr("marvis.core.workflow._workflow_dir", lambda: str(store))
    saved = run_workflow("local-procs", None)
    assert "不存在" in saved["error"]
    create_workflow("local-procs", [{"type": "procs", "name": "scan"}])
    done = run_workflow("local-procs", {"root": SAMPLE, "top": 4})
    assert done["process_count"] == 5
    assert done["top"] == 4
    assert done["killed"] is False
    assert (store / "local-procs.json").is_file()


def test_proc_net_symlink_stays_inside_the_proc_root(tmp_path):
    proc = tmp_path / "proc"
    inside = proc / "self" / "net"
    inside.mkdir(parents=True)
    (inside / "tcp").write_text(
        "  sl  local_address rem_address st\n"
        "   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 1\n",
        encoding="utf-8",
    )
    os.symlink("self/net", proc / "net")
    summary = inspect_processes_and_ports(str(tmp_path))
    assert summary["listener_count"] == 1
    assert summary["listeners"][0]["port"] == 22
    assert "proc/net" in summary["backends"]

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "tcp").write_text(
        "  sl  local_address rem_address st\n"
        "   0: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 1\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad"
    (bad / "proc").mkdir(parents=True)
    os.symlink(outside, bad / "proc" / "net")
    skipped = inspect_processes_and_ports(str(bad))
    assert skipped["listener_count"] == 0
    assert all(item["port"] != 80 for item in skipped["listeners"])
    assert any(item.get("error") == "symlink" for item in skipped["skipped"])


def test_live_host_stays_read_only():
    summary = inspect_processes_and_ports(top=5, max_entries=400, timeout_seconds=8)
    assert summary["source"] == "host"
    assert summary["killed"] is False
    assert summary["deleted"] is False
    assert summary["modified"] is False
    assert summary["preview"] is True
    assert len(summary["processes_by_rss"]) <= 5
    assert len(summary["listeners"]) <= 5
    assert set(summary["backends"]) <= {"ps", "ss", "proc", "proc/net"}
    report = format_proc_report(summary)
    assert "只读预览" in report
    assert "不会结束进程" in report
    if os.path.exists("/usr/bin/ps") or os.path.isdir("/proc"):
        assert summary["process_count"] > 0 or summary["partial"]
    if os.path.exists("/proc/net/tcp"):
        assert "ss" in summary["backends"] or "proc/net" in summary["backends"]
