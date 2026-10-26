import json
import os
import subprocess
import sys

import marvis
from marvis.core.system_manager import net_repair, port_check, process_list
from marvis.core.task_scheduler import create_task, run_task
from marvis.core.web_monitor import extract_text, search_web
from marvis.core.workflow import create_workflow, run_builtin_template, run_workflow
from marvis.mcp.tools import ALL_TOOLS, TOOL_REGISTRY, execute_tool


def _run(*args, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "-m", "marvis", *args],
        capture_output=True,
        text=True,
        env=merged,
        check=False,
    )


def test_version_and_help():
    from importlib.metadata import version

    assert version("marvis") == marvis.__version__ == "2.1.4"
    from marvis import search
    assert callable(search.search)
    version = _run("--version")
    assert version.returncode == 0
    assert "marvis 2.1.4" in version.stdout
    help_proc = _run("--help")
    assert help_proc.returncode == 0
    assert "doctor" in help_proc.stdout
    assert "search" in help_proc.stdout


def test_doctor_and_search_and_security(tmp_path):
    doctor = _run("doctor")
    assert doctor.returncode == 0
    assert "Marvis 2.1.4" in doctor.stdout
    assert "默认预览" in doctor.stdout
    assert "mcp" in doctor.stdout

    (tmp_path / "Hello.txt").write_text("合同", encoding="utf-8")
    found = _run("search", str(tmp_path), "--keyword", "hello", "--json")
    assert found.returncode == 0
    payload = json.loads(found.stdout)
    assert payload["count"] == 1

    secret = "zzzzzzzzzzzzzzzz"
    (tmp_path / "app.py").write_text(f'api_key = "{secret}"\n', encoding="utf-8")
    audit = _run("security", str(tmp_path), "--action", "sensitive-files")
    assert audit.returncode == 0
    assert secret not in audit.stdout
    assert "API 密钥" in audit.stdout


def test_repair_preview_does_not_run_commands(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return "", "", 0

    monkeypatch.setattr("marvis.core.system_manager.run", fake_run)
    preview = net_repair(execute=False)
    assert calls == []
    assert preview
    blob = json.dumps(preview, ensure_ascii=False)
    assert "未执行" in blob or "不自动改网络" in blob

    cli = _run("system", "repair")
    assert cli.returncode == 0
    assert "未执行" in cli.stdout or "不自动改网络" in cli.stdout


def test_local_mode_blocks_web_and_rejects_bad_url(monkeypatch):
    def fail_open(*args, **kwargs):
        raise AssertionError("本地模式不应发起网络请求")

    monkeypatch.setattr("urllib.request.urlopen", fail_open)
    monkeypatch.setenv("MARVIS_MODE", "local")
    blocked = search_web("marvis")
    assert "本地模式" in blocked["error"]

    monkeypatch.delenv("MARVIS_MODE", raising=False)
    from marvis.core.web_monitor import http_get
    body, err, status = http_get("file:///etc/passwd")
    assert status == 0
    assert "http/https" in err
    assert body == ""

    cli = _run("--local", "web", "search", "--query", "marvis")
    assert cli.returncode == 1
    assert "本地模式" in cli.stderr


def test_extract_text_strips_markup():
    text = extract_text("<html><script>bad()</script><p>你好 Marvis</p></html>")
    assert "你好 Marvis" in text
    assert "bad()" not in text


def test_workflow_rejects_shell_metacharacters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    create_workflow("demo", [{"type": "command", "name": "echo", "command": "echo {{name}}"}])
    blocked = run_workflow("demo", {"name": "a; touch pwned"})
    assert blocked["results"][0]["status"] == "error"
    assert "不允许" in blocked["results"][0]["error"]
    assert not (tmp_path / "pwned").exists()

    ok = run_workflow("demo", {"name": "项目A"})
    assert ok["results"][0]["status"] == "success"
    assert "项目A" in ok["results"][0]["output"]


def test_cli_workflow_templates_and_create(tmp_path):
    templates = _run("workflow", "templates")
    assert templates.returncode == 0
    assert "安全检查" in templates.stdout
    assert "敏感文件卫生" in templates.stdout
    assert "可直接运行" in templates.stdout
    assert "--root samples/hygiene" in templates.stdout
    created = _run(
        "workflow", "create", "--name", "cli-demo",
        "--params", json.dumps({"description": "demo", "steps": [{"type": "notify", "message": "ok"}]}),
    )
    assert created.returncode == 0
    listed = _run("workflow", "list")
    assert "cli-demo" in listed.stdout


def test_task_create_does_not_register_or_fetch(monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError("不应注册系统计划任务")

    monkeypatch.setattr("marvis.core.task_scheduler.subprocess.run", fake_run)
    task = create_task("ping", "url-ping", url="https://example.com", schedule="daily:09:00")
    assert "未注册" in task["scheduler"]
    assert calls == []

    monkeypatch.setenv("MARVIS_MODE", "local")
    result = run_task("ping")
    assert result["status"] == "failed"
    assert "本地模式" in result["error"]


def test_process_and_port_inputs_are_rejected():
    assert process_list(sort_by="cpu;id")[0]["error"]
    assert "主机名无效" in port_check(80, "127.0.0.1;id")["error"]
    closed = port_check(1, "127.0.0.1")
    assert closed["IsOpen"] is False


def test_process_list_hides_command_secrets(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert "aux" not in cmd
        assert "comm" in " ".join(cmd)

        class Proc:
            stdout = (
                "USER PID %CPU %MEM COMMAND\n"
                "ubuntu 1 0.0 0.1 app --auth-token supersecretvalue "
                "eyJaaaaaaa.eyJbbbbbbb.cccccccc\n"
            )
            stderr = ""
            returncode = 0

        return Proc()

    monkeypatch.setattr("marvis.core.system_manager.subprocess.run", fake_run)
    blob = json.dumps(process_list(limit=5), ensure_ascii=False)
    assert "supersecretvalue" not in blob
    assert "eyJaaaaaaa" not in blob
    assert "[redacted]" in blob


def test_mcp_tools_return_real_payloads(tmp_path):
    names = {tool["name"] for tool in ALL_TOOLS}
    assert names == set(TOOL_REGISTRY)
    assert "net_repair" in names
    assert "doctor" in names

    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    found = json.loads(execute_tool("search_files", {"root": str(tmp_path), "keyword": "pyproject"}))
    assert found["count"] == 1
    assert isinstance(found["files"], list)
    assert "path" in found["files"][0]

    info = json.loads(execute_tool("system_info", {}))
    assert "system" in info
    assert "error" not in info or isinstance(info["system"], dict)

    repair = json.loads(execute_tool("net_repair", {}))
    assert repair["preview"] is True

    doctor = json.loads(execute_tool("doctor", {}))
    assert doctor["version"] == "2.1.4"
    assert doctor["destructive_ops"] == "preview"

    note = tmp_path / "plain.txt"
    note.write_text("hello", encoding="utf-8")
    converted = json.loads(execute_tool("convert_format", {"path": str(note), "format": "text"}))
    assert "hello" in json.dumps(converted, ensure_ascii=False)

    unknown = json.loads(execute_tool("nope", {}))
    assert "未知工具" in unknown["error"]
    missing = json.loads(execute_tool("read_document", {}))
    assert "缺少参数" in missing["error"]

    listed = json.loads(execute_tool("list_workflows", {}))
    assert listed["templates"]["敏感文件卫生"]["runnable"] is True


def test_hygiene_workflow_scans_sample_without_deleting_or_leaking():
    sample = os.path.join(os.path.dirname(__file__), "..", "samples", "hygiene")
    sample = os.path.abspath(sample)
    before = {}
    for dirpath, dirnames, filenames in os.walk(sample):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        for name in filenames:
            path = os.path.join(dirpath, name)
            with open(path, "rb") as handle:
                before[path] = handle.read()

    listed = _run("workflow", "templates", "--json")
    assert listed.returncode == 0
    templates = json.loads(listed.stdout)
    assert templates["敏感文件卫生"]["runnable"] is True
    assert "hygiene" in templates["敏感文件卫生"]["aliases"]

    human = _run("workflow", "run", "--template", "敏感文件卫生", "--root", sample)
    assert human.returncode == 0, human.stderr
    assert "只读预览" in human.stdout
    assert "未删除、未修改" in human.stdout
    assert ".env.development" in human.stdout
    assert "credentials.json" in human.stdout
    assert "扫描文件: 5" in human.stdout
    assert "发现: 2" in human.stdout
    assert "APP_ENV" not in human.stdout
    assert "filename fixture only" not in human.stdout
    assert "plain" not in human.stdout

    machine = _run("workflow", "run", "--template", "hygiene", "--root", sample, "--json")
    assert machine.returncode == 0, machine.stderr
    payload = json.loads(machine.stdout)
    assert payload["template"] == "敏感文件卫生"
    assert payload["preview"] is True
    assert payload["deleted"] is False
    assert payload["files_scanned"] == 5
    assert payload["finding_count"] == 2
    assert payload["by_severity"]["高"] == 2
    blob = json.dumps(payload, ensure_ascii=False)
    assert "APP_ENV" not in blob
    assert "filename fixture only" not in blob

    for path, content in before.items():
        with open(path, "rb") as handle:
            assert handle.read() == content


def test_hygiene_workflow_redacts_generated_secret_and_refuses_unsafe_paths(tmp_path, monkeypatch):
    secret = "abcdefghijklmnop"
    (tmp_path / "notes.txt").write_text("hello\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(f'api_key = "{secret}"\n', encoding="utf-8")
    keep = tmp_path / "credentials.json"
    keep.write_text('{"note":"keep"}\n', encoding="utf-8")

    calls = []
    real_run = subprocess.run

    def track_run(*args, **kwargs):
        calls.append(args)
        raise AssertionError("卫生扫描不应启动 shell")

    # workflow.subprocess 就是 subprocess 模块，补丁结束后要还原，后面的 CLI 才能启动。
    monkeypatch.setattr(subprocess, "run", track_run)
    blocked = run_builtin_template("环境清理")
    assert "不能直接运行" in blocked["error"]
    assert calls == []

    report = run_builtin_template("hygiene", {"root": str(tmp_path)})
    assert "error" not in report
    assert report["deleted"] is False
    rendered = json.dumps(report, ensure_ascii=False)
    assert secret not in rendered
    assert "API 密钥" in rendered
    assert keep.read_text(encoding="utf-8") == '{"note":"keep"}\n'
    assert calls == []
    monkeypatch.setattr(subprocess, "run", real_run)

    missing = _run("workflow", "run", "--template", "hygiene", "--root", str(tmp_path / "missing"))
    assert missing.returncode == 1
    assert "目录不存在" in missing.stderr

    injected = _run("workflow", "run", "--template", "hygiene", "--root", str(tmp_path) + "; touch pwned")
    assert injected.returncode == 1
    assert not (tmp_path / "pwned").exists()
    assert not os.path.exists("pwned")

    output = tmp_path / "hygiene-report.txt"
    written = _run(
        "workflow", "run", "--template", "hygiene",
        "--root", str(tmp_path), "--output", str(output),
    )
    assert written.returncode == 0, written.stderr
    text = output.read_text(encoding="utf-8")
    assert "只读预览" in text
    assert secret not in text
    assert "报告已写入" in text
    again = _run(
        "workflow", "run", "--template", "hygiene",
        "--root", str(tmp_path), "--output", str(output),
    )
    assert again.returncode == 1
    assert "未覆盖" in again.stderr
    assert secret not in output.read_text(encoding="utf-8")

    nested = _run(
        "workflow", "run", "--template", "hygiene",
        "--root", str(tmp_path), "--output", str(tmp_path / "no-such-dir" / "report.txt"),
    )
    assert nested.returncode == 1
    assert "报告目录不存在" in nested.stderr
    assert not (tmp_path / "no-such-dir").exists()

    clobber = _run(
        "workflow", "run", "--template", "hygiene",
        "--root", str(tmp_path), "--output", str(keep),
    )
    assert clobber.returncode == 1
    assert keep.read_text(encoding="utf-8") == '{"note":"keep"}\n'


def test_hygiene_workflow_mcp_and_saved_step(tmp_path, monkeypatch):
    store = tmp_path / "workflows"
    monkeypatch.setattr("marvis.core.workflow._workflow_dir", lambda: str(store))
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "readme.txt").write_text("ok\n", encoding="utf-8")

    fresh = json.loads(execute_tool("run_workflow", {
        "template": "hygiene",
        "root": str(tmp_path / "empty"),
    }))
    assert fresh["finding_count"] == 0
    assert fresh["preview"] is True
    assert fresh["deleted"] is False
    assert "未发现" in fresh["report"]
    assert not store.exists()

    both = json.loads(execute_tool("run_workflow", {"name": "x", "template": "hygiene"}))
    assert "之一" in both["error"]
    absent = json.loads(execute_tool("run_workflow", {}))
    assert "name 或 template" in absent["error"]

    saved = run_workflow("local-hygiene", None)
    assert "不存在" in saved["error"]
    create_workflow("local-hygiene", [{"type": "hygiene", "name": "scan"}])
    done = run_workflow("local-hygiene", {"root": str(tmp_path / "empty")})
    assert done["finding_count"] == 0
    assert done["deleted"] is False
    assert (store / "local-hygiene.json").is_file()


def test_mcp_server_without_sdk_explains_install():
    import importlib.util
    if importlib.util.find_spec("mcp") is not None:
        return
    proc = _run("mcp-server")
    assert proc.returncode != 0
    assert "marvis[mcp]" in proc.stderr
