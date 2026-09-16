import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPOSITORY_ROOT / "config" / "deployment.json"


def load_deployment_config(path: Path | None = None) -> tuple[dict[str, Any], Path]:
    config_path = (path or DEFAULT_CONFIG_PATH).resolve()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Deployment config not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Deployment config is not valid JSON: {config_path}") from exc
    return config, config_path


def get_config_value(config: dict[str, Any], *path: str) -> Any:
    value: Any = config
    dotted_path = ".".join(path)
    for segment in path:
        if not isinstance(value, dict) or segment not in value:
            raise ValueError(f"Deployment config is missing '{dotted_path}'")
        value = value[segment]
    if value is None or value == "":
        raise ValueError(f"Deployment config value '{dotted_path}' is empty")
    return value


def resolve_deployment_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def foundry_project_endpoint(account_name: str, project_name: str) -> str:
    return (
        f"https://{account_name}.services.ai.azure.com/api/projects/{project_name}"
    )