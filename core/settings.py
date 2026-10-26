"""Shared paths: local defaults, environment overrides for hosted deployment."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get('CONFIG_DIR', PROJECT_ROOT / 'Config-filer'))


def load_env_file():
    path = CONFIG_DIR / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())


load_env_file()
DATA_DIR = Path(os.environ.get('DATA_DIR', PROJECT_ROOT / 'Fælles-data')).resolve()
