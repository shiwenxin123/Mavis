import json
import os
import zipfile

from marvis.core.batch_processor import batch_extract, batch_rename
from marvis.core.doc_analyzer import contract_review, polish_text, read_file
from marvis.core.file_organizer import find_duplicates, find_empty_dirs, scan_files
from marvis.core.format_converter import convert
from marvis.core.project_scanner import scan_project
from marvis.core.search import search
from marvis.core.security_audit import check_sensitive_files
from marvis.utils.config import MarvisConfig, load_config, save_config
from marvis.utils.fs import find_files, format_size, safe_read


def test_format_size_and_safe_read(tmp_path):
    assert format_size(0) == "0.0 B"
    assert format_size(1536).endswith("KB")
    target = tmp_path / "note.txt"
    target.write_text("hello marvis", encoding="utf-8")
    assert safe_read(str(target)) == "hello marvis"
    assert safe_read(str(tmp_path / "missing.txt")) is None
    found = find_files(str(tmp_path), pattern="note")
    assert found and found[0].endswith("note.txt")


def test_config_roundtrip_keeps_skip_dirs_as_set(tmp_path):
    path = tmp_path / "config.json"
    cfg = MarvisConfig(mode="local", skip_dirs={".git", "venv"})
    save_config(cfg, str(path))
    loaded = load_config(str(path))
    assert loaded.mode == "local"
    assert isinstance(loaded.skip_dirs, set)
    assert ".git" in loaded.skip_dirs
    assert loaded.workflow_dir


def test_search_by_name_and_content(tmp_path):
    (tmp_path / "Hello.txt").write_text("合同草案\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("nothing", encoding="utf-8")
    named = search(str(tmp_path), mode="name", keyword="hello")
    assert named["count"] == 1
    assert named["results"][0]["name"] == "Hello.txt"
    content = search(str(tmp_path), mode="content", keyword="合同")
    assert content["count"] == 1
    missing = search(str(tmp_path / "nope"), mode="name", keyword="x")
    assert "目录不存在" in missing["error"]


def test_duplicates_and_empty_dirs(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("same", encoding="utf-8")
    b.write_text("same", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    files = scan_files(str(tmp_path))
    groups = find_duplicates(files)
    assert groups and sorted(os.path.basename(p) for p in groups[0]["files"]) == ["a.txt", "b.txt"]
    assert any(path.endswith("empty") for path in find_empty_dirs(str(tmp_path)))


def test_sensitive_scan_redacts_secret_text(tmp_path):
    secret = "abcdefghijklmnop"
    (tmp_path / ".env").write_text("placeholder\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(f'api_key = "{secret}"\n', encoding="utf-8")
    findings = check_sensitive_files(str(tmp_path))
    blob = json.dumps(findings, ensure_ascii=False)
    assert secret not in blob
    assert any(item["type"] == "敏感文件名" for item in findings)
    assert any(item["detail"] == "API 密钥" for item in findings)


def test_zip_slip_is_rejected_and_safe_zip_extracts(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../escaped.txt", "pwned")
    bad_dest = tmp_path / "bad-out"
    bad_result = batch_extract(str(tmp_path), str(bad_dest))
    assert bad_result and "拒绝" in bad_result[0]["status"]
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path.parent / "escaped.txt").exists()

    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    with zipfile.ZipFile(safe_root / "ok.zip", "w") as archive:
        archive.writestr("hello.txt", "hi")
    dest = tmp_path / "safe-out"
    good = batch_extract(str(safe_root), str(dest))
    assert good[0]["status"] == "success"
    assert (dest / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_batch_rename_dry_run_does_not_touch_files(tmp_path):
    original = tmp_path / "Report.TXT"
    original.write_text("x", encoding="utf-8")
    planned = batch_rename(str(tmp_path), pattern="lowercase", dry_run=True)
    assert planned and planned[0]["new_name"] == "report.txt"
    assert original.exists()
    assert not (tmp_path / "report.txt").exists()


def test_contract_polish_and_convert(tmp_path):
    text = "甲方支付 10000 元。违约金为合同金额的 50%。最终解释权归甲方。"
    review = contract_review(text)
    assert review["risks"]
    assert "金额" in review["extracted"]
    polished = polish_text("这是一个很短的句子。")
    assert polished["score"] <= 100

    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("name,n\nalpha,1\n", encoding="utf-8")
    converted = convert(str(csv_path), "json")
    assert converted[0]["name"] == "alpha"

    missing = read_file(str(tmp_path / "gone.txt"))
    assert missing is None


def test_project_scan_finds_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    report = scan_project(str(tmp_path))
    langs = [item["lang"] for item in report["tech_stack"]]
    assert "Python" in langs
    assert any(ep.endswith("main.py") for ep in report["entry_points"])
