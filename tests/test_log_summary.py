import json
import os
import subprocess
import sys
import time

import pytest

from marvis.core.log_summary import format_log_report, redact_log_text, summarize_logs
from marvis.core.workflow import create_workflow, run_builtin_template, run_workflow
from marvis.mcp.tools import execute_tool

SAMPLE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "samples", "logs"))
MARKER = "NOT_A_SECRET_MARKER_log_fixture"
FORBIDDEN = (
    MARKER,
    "sk-FAKEKEY1234567890abcd",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "db-secret-pass",
    "super-secret-value",
    "FRAME_ONLY_SECRET",
    "eyJhbGciOi.eyJzdWIiOi.SflKxwRJSMeK",
    "do-not-print-this",
    "BINARY_SECRET_",
    "GZIP_ONLY_SECRET_",
    "NOTES_ONLY_MARKER",
    "app.py",
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
            st = os.lstat(path)
            with open(path, "rb") as handle:
                found[path] = (st.st_mtime_ns, st.st_size, handle.read())
    return found


def _symlink(src, dst):
    try:
        os.symlink(src, dst)
    except OSError:
        pytest.skip("当前环境不能创建符号链接")


def _blob(result) -> str:
    return json.dumps(result, ensure_ascii=False)


def test_redact_log_text_hides_credentials():
    url = redact_log_text("postgres://appuser:db-secret-pass@db.internal:5432/app")
    assert "db-secret-pass" not in url
    assert "db.internal" in url
    assert "[redacted]" in url
    assigned = redact_log_text("api_key=sk-FAKEKEY1234567890abcd and password=super-secret-value")
    assert "sk-FAKEKEY1234567890abcd" not in assigned
    assert "super-secret-value" not in assigned
    assert "api_key=[redacted]" in assigned
    jwt = redact_log_text("session eyJhbGciOi.eyJzdWIiOi.SflKxwRJSMeK expired")
    assert "eyJhbGciOi" not in jwt
    assert redact_log_text("Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789") == "Bearer [redacted]"
    assert redact_log_text("-----BEGIN RSA PRIVATE KEY-----") == "[redacted]"


def test_log_sample_cli_is_read_only_and_redacts():
    before = _snapshot(SAMPLE)
    listed = _run("workflow", "templates")
    assert listed.returncode == 0
    assert "日志错误摘要" in listed.stdout
    assert "可直接运行" in listed.stdout
    assert "--root samples/logs" in listed.stdout
    assert "logs" in listed.stdout

    human = _run("workflow", "run", "--template", "日志错误摘要", "--root", SAMPLE)
    assert human.returncode == 0, human.stderr
    assert "只读预览" in human.stdout
    assert "未删除、未修改、未执行" in human.stdout
    assert "未跟随符号链接" in human.stdout
    assert "未解压" in human.stdout
    assert "×4" in human.stdout
    assert "connection to <ip>:# refused" in human.stdout
    assert "payment declined" in human.stdout
    assert "password=[redacted]" in human.stdout
    assert "api_key=[redacted]" in human.stdout
    assert "[redacted]" in human.stdout
    assert len(human.stdout) < 8000
    for secret in FORBIDDEN:
        assert secret not in human.stdout

    machine = _run(
        "workflow", "run", "--template", "logs", "--root", SAMPLE, "--top", "10", "--json",
    )
    assert machine.returncode == 0, machine.stderr
    payload = json.loads(machine.stdout)
    assert payload["template"] == "日志错误摘要"
    assert payload["preview"] is True
    assert payload["deleted"] is False
    assert payload["modified"] is False
    assert payload["moved"] is False
    assert payload["partial"] is False
    assert payload["files_read"] == 3
    assert payload["lines_read"] == 17
    assert payload["dirs_seen"] == 2
    assert payload["non_log_skipped"] == 2
    assert payload["compressed_skipped"] == 1
    assert payload["binary_skipped"] == 1
    assert payload["tailed_files"] == 0
    assert payload["symlink_count"] == 0
    assert payload["fatal_count"] == 1
    assert payload["error_events"] == 8
    assert payload["warning_events"] == 3
    assert payload["newer_than_days"] is None
    assert payload["top"] == 10
    connection = payload["errors"][0]
    assert connection["count"] == 4
    assert connection["signature"] == "connection to <ip>:# refused"
    assert connection["file"] == os.path.join("nested", "worker.log")
    assert payload["warnings"][0]["count"] == 2
    assert payload["busiest_files"][0]["file"] == "app.log"
    assert payload["busiest_files"][0]["error"] == 4
    rendered = json.dumps(payload, ensure_ascii=False)
    for secret in FORBIDDEN:
        assert secret not in rendered
    assert _snapshot(SAMPLE) == before

    alias = _run("workflow", "run", "--template", "log-errors", "--root", SAMPLE, "--json")
    assert alias.returncode == 0, alias.stderr
    assert json.loads(alias.stdout)["error_events"] == 8


def test_grouping_top_and_empty_directory(tmp_path):
    (tmp_path / "app.log").write_text(
        "INFO all quiet\n"
        "ERROR connection to 10.0.0.1:1 refused\n"
        "ERROR connection to 10.0.0.2:1 refused\n"
        "WARNING disk cache almost full\n",
        encoding="utf-8",
    )
    summary = summarize_logs(str(tmp_path), top=1)
    assert summary["error_events"] == 2
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["count"] == 2
    assert len(summary["warnings"]) == 1
    assert "all quiet" not in _blob(summary)
    assert "前 1 种" in format_log_report(summary)

    empty = tmp_path / "empty"
    empty.mkdir()
    quiet = summarize_logs(str(empty))
    assert quiet["files_read"] == 0
    assert quiet["error_events"] == 0
    report = format_log_report(quiet)
    assert "未发现致命或错误" in report
    assert "未发现警告" in report


def test_days_filter_uses_timestamps_then_mtime(tmp_path):
    now = time.time()
    recent = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 3600))
    old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now - 10 * 86400))
    (tmp_path / "mixed.log").write_text(
        f"{recent} ERROR RECENT_KEEP\n{old} ERROR OLD_DROP\nERROR NO_TIME_KEEP\n",
        encoding="utf-8",
    )
    stale = tmp_path / "stale.log"
    stale.write_text("ERROR STALE_FILE_DROP\n", encoding="utf-8")
    os.utime(stale, (now - 10 * 86400, now - 10 * 86400))

    windowed = summarize_logs(str(tmp_path), newer_than_days=1)
    blob = _blob(windowed)
    assert "RECENT_KEEP" in blob
    assert "NO_TIME_KEEP" in blob
    assert "OLD_DROP" not in blob
    assert "STALE_FILE_DROP" not in blob
    assert windowed["newer_than_days"] == 1
    assert "最近 1 天" in format_log_report(windowed)

    everything = _blob(summarize_logs(str(tmp_path)))
    assert "OLD_DROP" in everything
    assert "STALE_FILE_DROP" in everything


def test_tail_skips_bytes_beyond_the_window(tmp_path):
    tail = b"ERROR NEW_ERROR_TOKEN happened\n"
    content = b"ERROR OLD_ERROR_TOKEN password=old-secret-value\n" + (b"I" * 500) + b"\n" + tail
    (tmp_path / "huge.log").write_bytes(content)
    result = summarize_logs(str(tmp_path), max_bytes_per_file=80)
    blob = _blob(result)
    assert "NEW_ERROR_TOKEN" in blob
    assert "OLD_ERROR_TOKEN" not in blob
    assert "old-secret-value" not in blob
    assert result["tailed_files"] == 1
    assert result["files_read"] == 1


def test_limits_depth_entries_lines_bytes_and_time(tmp_path, monkeypatch):
    (tmp_path / "a.log").write_text("ERROR ROOT_HIT\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.log").write_text("ERROR MID_HIT\n", encoding="utf-8")
    (tmp_path / "sub" / "deeper").mkdir()
    (tmp_path / "sub" / "deeper" / "c.log").write_text("ERROR DEEP_HIT\n", encoding="utf-8")
    shallow = summarize_logs(str(tmp_path), max_depth=0)
    shallow_blob = _blob(shallow)
    assert "ROOT_HIT" in shallow_blob
    assert "MID_HIT" not in shallow_blob
    assert "DEEP_HIT" not in shallow_blob
    assert shallow["limit_hits"] == ["深度"]

    wide = tmp_path / "wide"
    wide.mkdir()
    for index in range(5):
        (wide / f"f{index}.log").write_text(f"ERROR item-{index}\n", encoding="utf-8")
    capped = summarize_logs(str(wide), max_entries=1)
    assert capped["files_read"] == 1
    assert "条目" in capped["limit_hits"]
    assert "item-0" in _blob(capped)
    assert "item-4" not in _blob(capped)

    lined = tmp_path / "lined"
    lined.mkdir()
    (lined / "many.log").write_text("".join(f"ERROR line-{i}\n" for i in range(5)), encoding="utf-8")
    short = summarize_logs(str(lined), max_lines=2)
    assert short["lines_read"] == 2
    assert short["error_events"] == 2
    assert "行数" in short["limit_hits"]

    heavy = tmp_path / "heavy"
    heavy.mkdir()
    (heavy / "a.log").write_text("ERROR " + ("A" * 200) + "\n", encoding="utf-8")
    (heavy / "b.log").write_text("ERROR SECOND_FILE_TOKEN\n", encoding="utf-8")
    budget = summarize_logs(str(heavy), max_total_bytes=64)
    assert "SECOND_FILE_TOKEN" not in _blob(budget)
    assert "字节" in budget["limit_hits"]

    calls = {"n": 0}

    def fake_monotonic():
        calls["n"] += 1
        return 0.0 if calls["n"] <= 4 else 1000.0

    timed_root = tmp_path / "timed"
    timed_root.mkdir()
    (timed_root / "slow.log").write_text("".join(f"ERROR slow-{i}\n" for i in range(250)), encoding="utf-8")
    monkeypatch.setattr("marvis.core.log_summary.time.monotonic", fake_monotonic)
    timed = summarize_logs(str(timed_root), timeout_seconds=1)
    assert timed["partial"] is True
    assert "时间" in timed["limit_hits"]
    assert timed["lines_read"] == 200


def _word(index: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    chars = []
    value = index + 1
    while value:
        value, rem = divmod(value - 1, 26)
        chars.append(alphabet[rem])
    return "".join(reversed(chars))


def test_signature_cap_counts_events_without_storing_every_message(tmp_path):
    lines = [f"ERROR unique failure {_word(index)}\n" for index in range(401)]
    (tmp_path / "many.log").write_text("".join(lines), encoding="utf-8")
    result = summarize_logs(str(tmp_path), top=10)
    assert result["error_events"] == 401
    assert result["overflow"] == 1
    assert len(result["errors"]) == 10
    assert "种类" in result["limit_hits"]
    assert "另有 1 种" in format_log_report(result)


def test_skips_symlinks_compressed_non_logs_and_unreadable(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.log"
    secret.write_text("ERROR OUTSIDE_SECRET_VALUE\n", encoding="utf-8")
    old = 1_000_000_000
    os.utime(secret, (old, old))
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside.log").write_text("ERROR inside-only\n", encoding="utf-8")
    _symlink(secret, root / "escape.log")
    _symlink(outside, root / "escape_dir")
    _symlink(root / "inside.log", root / "inner-link.log")
    (root / "notes.txt").write_text("SECRET_IN_TXT\n", encoding="utf-8")
    (root / "packed.log.gz").write_text("SECRET_IN_GZ\n", encoding="utf-8")
    (root / "blob.log").write_bytes(b"ERROR visible\x00SECRET_BIN\n")

    opened = []
    real_open = os.open

    def wrapped(path, flags, *args, **kwargs):
        opened.append(os.path.basename(path))
        if os.path.basename(path) == "blocked.log":
            raise PermissionError("denied")
        return real_open(path, flags, *args, **kwargs)

    (root / "blocked.log").write_text("ERROR BLOCKED_SECRET\n", encoding="utf-8")
    monkeypatch.setattr("marvis.core.log_summary.os.open", wrapped)
    result = summarize_logs(str(root))
    blob = _blob(result)
    assert "inside-only" in blob
    assert "OUTSIDE_SECRET_VALUE" not in blob
    assert "SECRET_IN_TXT" not in blob
    assert "SECRET_IN_GZ" not in blob
    assert "SECRET_BIN" not in blob
    assert "BLOCKED_SECRET" not in blob
    assert result["symlink_count"] == 3
    assert result["outside_symlink_count"] == 2
    assert result["compressed_skipped"] == 1
    assert result["binary_skipped"] == 1
    assert result["non_log_skipped"] == 1
    assert result["error_count"] >= 1
    assert any(item["error"] == "PermissionError" for item in result["skipped"])
    assert "escape.log" not in opened
    assert "packed.log.gz" not in opened
    assert "notes.txt" not in opened
    assert secret.read_text(encoding="utf-8") == "ERROR OUTSIDE_SECRET_VALUE\n"
    assert os.lstat(secret).st_mtime == old
    assert "跳过" in format_log_report(result) or "读取失败" in format_log_report(result)

    via = tmp_path / "via-link"
    _symlink(root, via)
    linked = summarize_logs(str(via))
    assert linked["files_read"] >= 1
    assert os.path.realpath(linked["root"]) == os.path.realpath(str(root))


def test_permission_errors_on_directories_are_skipped(tmp_path, monkeypatch):
    (tmp_path / "ok.log").write_text("ERROR ok-hit\n", encoding="utf-8")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "hidden.log").write_text("ERROR hidden-hit\n", encoding="utf-8")
    real_scandir = os.scandir

    def wrapped(path):
        if os.path.basename(os.path.normpath(path)) == "blocked":
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr("marvis.core.log_summary.os.scandir", wrapped)
    result = summarize_logs(str(tmp_path))
    blob = _blob(result)
    assert "ok-hit" in blob
    assert "hidden-hit" not in blob
    assert result["error_count"] >= 1
    assert "读取失败" in format_log_report(result)


def test_unsafe_paths_output_and_cli_flags(tmp_path):
    with pytest.raises(ValueError, match="无效"):
        summarize_logs("bad\x00path")
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="目录不存在"):
        summarize_logs(str(missing))
    a_file = tmp_path / "file.log"
    a_file.write_text("ERROR x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="不是目录"):
        summarize_logs(str(a_file))
    with pytest.raises(ValueError, match="top 需在"):
        summarize_logs(str(tmp_path), top=0)
    with pytest.raises(ValueError, match="必须是整数"):
        summarize_logs(str(tmp_path), top=True)
    with pytest.raises(ValueError, match="days 需在"):
        summarize_logs(str(tmp_path), newer_than_days=0)

    work = tmp_path / "scan"
    work.mkdir()
    (work / "keep.log").write_text("ERROR keep-me password=keep-secret\n", encoding="utf-8")
    (work / "other.log").write_text("WARNING other-me\n", encoding="utf-8")
    cli = _run(
        "workflow", "run", "--template", "logs", "--root", str(work),
        "--top", "1", "--days", "30", "--json",
    )
    assert cli.returncode == 0, cli.stderr
    payload = json.loads(cli.stdout)
    assert len(payload["errors"]) == 1
    assert payload["error_events"] == 1
    assert payload["newer_than_days"] == 30
    assert "keep-secret" not in cli.stdout
    assert "password=[redacted]" in cli.stdout

    absent = _run("workflow", "run", "--template", "logs", "--root", str(missing))
    assert absent.returncode == 1
    assert "目录不存在" in absent.stderr

    injected = _run(
        "workflow", "run", "--template", "logs",
        "--root", str(tmp_path) + "; touch pwned",
    )
    assert injected.returncode == 1
    assert not (tmp_path / "pwned").exists()
    assert not os.path.exists("pwned")

    bad_top = _run("workflow", "run", "--template", "logs", "--root", str(work), "--top", "0")
    assert bad_top.returncode == 1
    assert "top 需在" in bad_top.stderr

    output = tmp_path / "log-report.txt"
    written = _run(
        "workflow", "run", "--template", "logs",
        "--root", str(work), "--output", str(output),
    )
    assert written.returncode == 0, written.stderr
    text = output.read_text(encoding="utf-8")
    assert "只读预览" in text
    assert "报告已写入" in text
    assert "keep-secret" not in text
    assert (work / "keep.log").read_text(encoding="utf-8").startswith("ERROR keep-me")
    again = _run(
        "workflow", "run", "--template", "logs",
        "--root", str(work), "--output", str(output),
    )
    assert again.returncode == 1
    assert "未覆盖" in again.stderr


def test_log_workflow_mcp_saved_step_and_no_shell(tmp_path, monkeypatch):
    calls = []
    real_run = subprocess.run

    def track(*args, **kwargs):
        calls.append(args)
        raise AssertionError("日志摘要不应启动 shell")

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "plain.log").write_text("ERROR plain-hit\n", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", track)
    report = run_builtin_template("log-errors", {"root": str(tree), "top": 3})
    assert "error" not in report
    assert report["deleted"] is False
    assert report["modified"] is False
    assert report["files_read"] == 1
    assert report["error_events"] == 1
    assert calls == []
    monkeypatch.setattr(subprocess, "run", real_run)

    store = tmp_path / "workflows"
    monkeypatch.setattr("marvis.core.workflow._workflow_dir", lambda: str(store))
    fresh = json.loads(execute_tool("run_workflow", {
        "template": "logs",
        "root": str(tree),
        "top": 3,
    }))
    assert fresh["files_read"] == 1
    assert fresh["top"] == 3
    assert fresh["preview"] is True
    assert "只读预览" in fresh["report"]
    assert "plain-hit" in fresh["report"]
    assert not store.exists()

    saved = run_workflow("local-logs", None)
    assert "不存在" in saved["error"]
    create_workflow("local-logs", [{"type": "logs", "name": "scan"}])
    done = run_workflow("local-logs", {"root": str(tree)})
    assert done["error_events"] == 1
    assert done["moved"] is False
    assert (store / "local-logs.json").is_file()
    assert (tree / "plain.log").read_text(encoding="utf-8") == "ERROR plain-hit\n"
