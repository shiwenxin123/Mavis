"""
Marvis 统一配置管理。
"""

import os
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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
            self.workflow_dir = str(Path.home() / ".marvis" / "workflows")


def load_config(config_path: Optional[str] = None) -> MarvisConfig:
    """从文件加载配置，不存在则返回默认"""
    config = MarvisConfig()

    if config_path is None:
        config_path = Path.home() / ".marvis" / "config.json"

    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, val in data.items():
                if hasattr(config, key):
                    setattr(config, key, val)
        except (json.JSONDecodeError, OSError):
            pass

    return config


def save_config(config: MarvisConfig, config_path: Optional[str] = None):
    """保存配置到文件"""
    if config_path is None:
        config_path = Path.home() / ".marvis" / "config.json"

    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    data = {k: v for k, v in config.__dict__.items() if not k.startswith("_")}
    # 将 set 转为 list 以便 JSON 序列化
    for k, v in data.items():
        if isinstance(v, set):
            data[k] = list(v)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
