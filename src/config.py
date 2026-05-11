"""Configuration loading for InfoHub.

Loads the global config from data/config.json and per-domain
configs from data/domains/*.json.  All paths use pathlib.Path.
"""

import json
from pathlib import Path
from typing import List, Optional

from .models import (
    AIConfig,
    DomainConfig,
    FilteringConfig,
    GlobalConfig,
    SchedulerConfig,
    ServerConfig,
    SourcesConfig,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path("D:/InfoHub")
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = DATA_DIR / "config.json"
DOMAINS_DIR = DATA_DIR / "domains"


# ---------------------------------------------------------------------------
# Global config
# ---------------------------------------------------------------------------

def load_global_config(path: Path = CONFIG_PATH) -> GlobalConfig:
    """Load the global InfoHub configuration from *path*.

    Raises ``FileNotFoundError`` if the file does not exist and
    ``json.JSONDecodeError`` / ``pydantic.ValidationError`` on bad data.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    return GlobalConfig(**raw)


# ---------------------------------------------------------------------------
# Domain configs
# ---------------------------------------------------------------------------

def load_domain_configs(directory: Path = DOMAINS_DIR) -> List[DomainConfig]:
    """Scan *directory* for ``*.json`` files and return a list of
    :class:`DomainConfig` instances, sorted by ``sort_order``.

    Files that fail to parse are silently skipped (a warning is printed
    to stderr).
    """
    configs: List[DomainConfig] = []

    if not directory.is_dir():
        return configs

    for json_file in sorted(directory.glob("*.json")):
        try:
            raw = json.loads(json_file.read_text(encoding="utf-8"))
            configs.append(DomainConfig(**raw))
        except Exception as exc:  # noqa: BLE001
            import sys
            print(
                f"[config] Warning: failed to load domain config "
                f"{json_file.name}: {exc}",
                file=sys.stderr,
            )

    configs.sort(key=lambda c: (c.sort_order, c.slug))
    return configs


def load_domain_config(
    slug: str, directory: Path = DOMAINS_DIR
) -> Optional[DomainConfig]:
    """Load a single domain configuration by its *slug*.

    Returns ``None`` if the file does not exist or cannot be parsed.
    """
    json_file = directory / f"{slug}.json"
    if not json_file.is_file():
        return None
    try:
        raw = json.loads(json_file.read_text(encoding="utf-8"))
        return DomainConfig(**raw)
    except Exception:  # noqa: BLE001
        return None
