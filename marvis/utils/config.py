"""
Marvis 统一配置管理。
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def marvis_home() -> Path:
    """运行时数据目录。测试和多用户可通过 MARVIS_HOME 隔离。"""
    raw = os.environ.get("MARVIS_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".marvis"


def network_allowed() -> tuple[bool, str]:
    """本地模式承诺：不访问外部网络。环境变量优先于配置文件。"""
    mode = os.environ.get("MARVIS_MODE", "").strip().lower()
    if mode in {"local", "offline", "privacy"}:
        return False, "本地模式已启用（MARVIS_MODE），已阻止外部网络访问"
    if mode in {"efficient", "remote"}:
        return True, ""
    cfg = load_config()
    if str(cfg.mode).lower() == "local":
        return False, "本地模式已启用（配置 mode=local），已阻止外部网络访问"
    return True, ""


@dataclass
class MarvisConfig:
    """Marvis 运行时配置"""

    # 运行模式
    mode: str = "efficient"  # "efficient" | "local"

    # 搜索
    search_max_size_mb: int = 10
    search_encoding: str = "utf-8"
    search_limit: int = 50
    skip_dirs: set = field(default_factory=lambda: {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".idea", ".vs", ".BIN", "System Volume Information",
    })

    # 安全
    confirm_before_delete: bool = True
    preview_mode: bool = True

    # 工作流
    workflow_dir: str = ""

    # 超时
    command_timeout: int = 60

    # MCP
    mcp_port: int = 0  # 0 = stdio mode

    def __post_init__(self):
        if not self.workflow_dir:
            self.workflow_dir = str(marvis_home() / "workflows")


def load_config(config_path: Optional[str] = None) -> MarvisConfig:
    """从文件加载配置，不存在则返回默认"""
    config = MarvisConfig()

    if config_path is None:
        config_path = str(marvis_home() / "config.json")

    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return config
        if not isinstance(data, dict):
            return config
        for key, val in data.items():
            if not hasattr(config, key) or str(key).startswith("_"):
                continue
            if key == "skip_dirs":
                if isinstance(val, (list, set, tuple)):
                    config.skip_dirs = {str(item) for item in val}
                continue
            if key == "mode":
                if val in ("efficient", "local"):
                    config.mode = val
                continue
            if key == "workflow_dir":
                if isinstance(val, str) and val.strip():
                    config.workflow_dir = val
                continue
            setattr(config, key, val)

    return config


def save_config(config: MarvisConfig, config_path: Optional[str] = None):
    """保存配置到文件"""
    if config_path is None:
        config_path = str(marvis_home() / "config.json")

    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)

    data = {}
    for key, val in config.__dict__.items():
        if str(key).startswith("_"):
            continue
        data[key] = sorted(val) if isinstance(val, set) else val

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
