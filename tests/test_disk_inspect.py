import json
import os
import subprocess
import sys
import time

import pytest

from marvis.core.disk_inspect import _same_tree, format_disk_report, inspect_large_files
from marvis.core.workflow import create_workflow, run_builtin_template, run_workflow
from marvis.mcp.tools import execute_tool

SAMPLE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "samples", "disk"))
MARKER = "NOT_A_SECRET_MARKER_disk_fixture"


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


def test_disk_sample_cli_is_read_only_and_hides_file_contents():
    before = _snapshot(SAMPLE)
    listed = _run("workflow", "templates")
    assert listed.returncode == 0
    assert "磁盘与大文件巡检" in listed.stdout
    assert "可直接运行" in listed.stdout
    assert "--root samples/disk" in listed.stdout
    assert "disk" in listed.stdout

    human = _run("workflow", "run", "--template", "磁盘与大文件巡检", "--root", SAMPLE)
    assert human.returncode == 0, human.stderr
    assert "只读预览" in human.stdout
    assert "未删除、未移动、未修改" in human.stdout
    assert "未跟随符号链接" in human.stdout
    assert "文件系统" in human.stdout
    assert "普通文件" in human.stdout
    assert os.path.join("cache", "blob.txt") in human.stdout
    assert "未发现" in human.stdout
    assert MARKER not in human.stdout
    assert "0000000000" not in human.stdout
    assert len(human.stdout) < 8000

    machine = _run(
        "workflow", "run", "--template", "disk", "--root", SAMPLE,
        "--top", "10", "--days", "90", "--json",
    )
    assert machine.returncode == 0, machine.stderr
    payload = json.loads(machine.stdout)
    assert payload["template"] == "磁盘与大文件巡检"
    assert payload["preview"] is True
    assert payload["deleted"] is False
    assert payload["modified"] is False
    assert payload["moved"] is False
    assert payload["partial"] is False
    assert payload["files_seen"] == 4
    assert payload["dirs_seen"] == 5
    assert payload["top"] == 10
    assert payload["older_than_days"] == 90
    assert payload["min_old_bytes"] == 1024 * 1024
    assert payload["old_large_count"] == 0
    assert payload["symlink_count"] == 0
    blob = payload["largest_files"][0]
    assert blob["rel"] == os.path.join("cache", "blob.txt")
    assert blob["size_bytes"] == 8192
    assert payload["largest_dirs"][0]["rel"] == "cache"
    fs = payload["filesystem"]
    assert fs["total_bytes"] >= fs["used_bytes"] >= 0
    assert fs["free_bytes"] >= 0
    assert 0 <= fs["percent"] <= 100
    rendered = json.dumps(payload, ensure_ascii=False)
    assert MARKER not in rendered
    assert _snapshot(SAMPLE) == before

    alias = _run("workflow", "run", "--template", "large-files", "--root", SAMPLE, "--json")
    assert alias.returncode == 0, alias.stderr
    assert json.loads(alias.stdout)["files_seen"] == 4


def test_top_age_and_directory_ranking(tmp_path):
    for index in range(12):
        (tmp_path / f"f{index:02d}.bin").write_bytes(b"x" * (1000 + index))
    fresh = inspect_large_files(str(tmp_path))
    assert fresh["top"] == 10
    assert len(fresh["largest_files"]) == 10
    assert fresh["largest_files"][0]["rel"] == "f11.bin"
    assert fresh["old_large_count"] == 0
    assert fresh["min_old_bytes"] == 1024 * 1024
    assert "未发现" in format_disk_report(fresh)

    old_stamp = time.time() - 120 * 86400
    for name, size in (("old-big.bin", 5000), ("old-small.txt", 20), ("newer.bin", 8000)):
        path = tmp_path / "ranked" / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"z" * size)
    os.utime(tmp_path / "ranked" / "old-big.bin", (old_stamp, old_stamp))
    os.utime(tmp_path / "ranked" / "old-small.txt", (old_stamp, old_stamp))
    for extra in range(4):
        path = tmp_path / "ranked" / f"old-{extra}.bin"
        path.write_bytes(b"y" * (2000 + extra))
        os.utime(path, (old_stamp, old_stamp))

    ranked = inspect_large_files(
        str(tmp_path / "ranked"), top=2, older_than_days=90, min_old_bytes=1024,
    )
    assert [item["rel"] for item in ranked["largest_files"]] == ["newer.bin", "old-big.bin"]
    assert ranked["old_large_count"] == 5
    assert len(ranked["old_large_files"]) == 2
    assert ranked["old_large_files"][0]["rel"] == "old-big.bin"
    assert "old-small.txt" not in {item["rel"] for item in ranked["old_large_files"]}
    assert "另有 3 个" in format_disk_report(ranked)
    assert ranked["largest_dirs"] == []


def test_symlinks_are_not_followed_outside_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret-outside.bin"
    secret.write_bytes(b"z" * 100_000)
    old = 1_000_000_000
    os.utime(secret, (old, old))
    root = tmp_path / "root"
    root.mkdir()
    (root / "inside.bin").write_bytes(b"q" * 100)
    _symlink(secret, root / "escape.bin")
    _symlink(outside, root / "escape_dir")
    _symlink(root / "inside.bin", root / "inner-link.bin")

    result = inspect_large_files(str(root), top=10, min_old_bytes=1)
    assert [item["rel"] for item in result["largest_files"]] == ["inside.bin"]
    assert result["scanned_bytes"] == 100
    assert result["symlink_count"] == 3
    assert result["outside_symlink_count"] == 2
    blob = json.dumps(result, ensure_ascii=False)
    assert "secret-outside.bin" not in blob
    assert secret.read_bytes() == b"z" * 100_000
    assert os.lstat(secret).st_mtime == old

    via = tmp_path / "via-link"
    _symlink(root, via)
    linked = inspect_large_files(str(via), min_old_bytes=1)
    assert linked["files_seen"] == 1
    assert os.path.realpath(linked["root"]) == os.path.realpath(str(root))


def test_permission_errors_are_skipped(tmp_path, monkeypatch):
    (tmp_path / "ok.txt").write_bytes(b"ok")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    hidden = blocked / "hidden.txt"
    hidden.write_bytes(b"h" * 50)
    real_scandir = os.scandir

    def wrapped(path):
        if os.path.basename(os.path.normpath(path)) == "blocked":
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr("marvis.core.disk_inspect.os.scandir", wrapped)
    result = inspect_large_files(str(tmp_path), min_old_bytes=1)
    rels = [item["rel"] for item in result["largest_files"]]
    assert rels == ["ok.txt"]
    assert result["error_count"] >= 1
    assert any(item["error"] == "PermissionError" for item in result["skipped"])
    assert "hidden.txt" not in json.dumps(result["largest_files"])
    assert hidden.read_bytes() == b"h" * 50
    assert "跳过" in format_disk_report(result)


def test_depth_entry_and_time_caps(tmp_path, monkeypatch):
    (tmp_path / "top.txt").write_bytes(b"t" * 10)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "mid.txt").write_bytes(b"m" * 20)
    (tmp_path / "sub" / "deeper").mkdir()
    (tmp_path / "sub" / "deeper" / "bottom.txt").write_bytes(b"b" * 30)

    depth = inspect_large_files(str(tmp_path), max_depth=1, min_old_bytes=1)
    rels = {item["rel"] for item in depth["largest_files"]}
    assert "top.txt" in rels
    assert os.path.join("sub", "mid.txt") in rels
    assert "bottom.txt" not in json.dumps(depth["largest_files"])
    assert depth["partial"] is True
    assert depth["limit_hits"] == ["深度"]

    wide = tmp_path / "wide"
    wide.mkdir()
    for index in range(5):
        (wide / f"f{index}.txt").write_bytes(b"x")
    capped = inspect_large_files(str(wide), max_entries=2, min_old_bytes=1)
    assert capped["files_seen"] == 2
    assert "条目" in capped["limit_hits"]

    calls = {"n": 0}

    def fake_monotonic():
        calls["n"] += 1
        if calls["n"] < 6:
            return 0.0
        return 1000.0

    monkeypatch.setattr("marvis.core.disk_inspect.time.monotonic", fake_monotonic)
    timed = inspect_large_files(str(wide), timeout_seconds=1, min_old_bytes=1)
    assert timed["partial"] is True
    assert "时间" in timed["limit_hits"]
    assert 0 < timed["files_seen"] < 5


def test_disk_usage_error_still_lists_files(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"abc")

    def boom(path):
        raise OSError("denied")

    monkeypatch.setattr("marvis.core.disk_inspect.shutil.disk_usage", boom)
    result = inspect_large_files(str(tmp_path), min_old_bytes=1)
    assert "无法读取磁盘用量" in result["filesystem"]["error"]
    assert result["files_seen"] == 1
    assert "无法读取磁盘用量" in format_disk_report(result)


def test_same_tree_rejects_siblings_and_different_drives(tmp_path, monkeypatch):
    root = tmp_path / "root"
    assert _same_tree(str(root), str(root / "child")) is True
    assert _same_tree(str(root), str(tmp_path / "root-other")) is False

    def different_drive(paths):
        raise ValueError("different drive")

    monkeypatch.setattr("marvis.core.disk_inspect.os.path.commonpath", different_drive)
    assert _same_tree(r"C:\root", r"D:\other") is False


def test_unsafe_paths_output_and_cli_flags(tmp_path):
    with pytest.raises(ValueError, match="无效"):
        inspect_large_files("bad\x00path")
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="目录不存在"):
        inspect_large_files(str(missing))
    a_file = tmp_path / "file.txt"
    a_file.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="不是目录"):
        inspect_large_files(str(a_file))
    with pytest.raises(ValueError, match="top 需在"):
        inspect_large_files(str(tmp_path), top=0)
    with pytest.raises(ValueError, match="必须是整数"):
        inspect_large_files(str(tmp_path), top=1.5)

    (tmp_path / "keep.bin").write_bytes(b"k" * 3000)
    (tmp_path / "other.bin").write_bytes(b"o" * 1000)
    cli = _run(
        "workflow", "run", "--template", "disk", "--root", str(tmp_path),
        "--top", "1", "--days", "30", "--min-bytes", "1", "--json",
    )
    assert cli.returncode == 0, cli.stderr
    payload = json.loads(cli.stdout)
    assert len(payload["largest_files"]) == 1
    assert payload["largest_files"][0]["rel"] == "keep.bin"
    assert payload["min_old_bytes"] == 1

    absent = _run("workflow", "run", "--template", "disk", "--root", str(missing))
    assert absent.returncode == 1
    assert "目录不存在" in absent.stderr

    injected = _run(
        "workflow", "run", "--template", "disk",
        "--root", str(tmp_path) + "; touch pwned",
    )
    assert injected.returncode == 1
    assert not (tmp_path / "pwned").exists()
    assert not os.path.exists("pwned")

    bad_top = _run("workflow", "run", "--template", "disk", "--root", str(tmp_path), "--top", "0")
    assert bad_top.returncode == 1
    assert "top 需在" in bad_top.stderr

    output = tmp_path / "disk-report.txt"
    written = _run(
        "workflow", "run", "--template", "disk",
        "--root", str(tmp_path), "--output", str(output),
    )
    assert written.returncode == 0, written.stderr
    text = output.read_text(encoding="utf-8")
    assert "只读预览" in text
    assert "报告已写入" in text
    assert (tmp_path / "keep.bin").read_bytes() == b"k" * 3000
    again = _run(
        "workflow", "run", "--template", "disk",
        "--root", str(tmp_path), "--output", str(output),
    )
    assert again.returncode == 1
    assert "未覆盖" in again.stderr


def test_disk_workflow_mcp_saved_step_and_no_shell(tmp_path, monkeypatch):
    calls = []
    real_run = subprocess.run

    def track(*args, **kwargs):
        calls.append(args)
        raise AssertionError("磁盘巡检不应启动 shell")

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "plain.txt").write_bytes(b"plain")
    monkeypatch.setattr(subprocess, "run", track)
    report = run_builtin_template("large-files", {"root": str(tree), "min_bytes": 1})
    assert "error" not in report
    assert report["deleted"] is False
    assert report["files_seen"] == 1
    assert calls == []
    monkeypatch.setattr(subprocess, "run", real_run)

    store = tmp_path / "workflows"
    monkeypatch.setattr("marvis.core.workflow._workflow_dir", lambda: str(store))
    fresh = json.loads(execute_tool("run_workflow", {
        "template": "disk",
        "root": str(tree),
        "top": 3,
        "min_bytes": 1,
    }))
    assert fresh["files_seen"] == 1
    assert fresh["top"] == 3
    assert fresh["preview"] is True
    assert "只读预览" in fresh["report"]
    assert not store.exists()

    saved = run_workflow("local-disk", None)
    assert "不存在" in saved["error"]
    create_workflow("local-disk", [{"type": "disk", "name": "scan"}])
    done = run_workflow("local-disk", {"root": str(tree), "min_bytes": 1})
    assert done["files_seen"] == 1
    assert done["moved"] is False
    assert (store / "local-disk.json").is_file()
    assert (tree / "plain.txt").read_bytes() == b"plain"
