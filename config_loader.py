import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config" / "config.json"
ENV_FILE = BASE_DIR / "config" / ".env"


def load_env_file(path=ENV_FILE):
    env = {}
    if not path.exists():
        return env

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        key, value = m.groups()
        env[key] = value.strip().strip('"').strip("'")
    return env


def load_runtime_config():
    cfg = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)

    env = load_env_file()
    merged = dict(cfg)
    merged.update({
        "email": env.get("GMAIL_EMAIL", cfg.get("email", "")),
        "app_password": env.get("GMAIL_APP_PASSWORD", cfg.get("app_password", "")),
        "imap_server": env.get("IMAP_SERVER", cfg.get("imap_server", "imap.gmail.com")),
        "imap_port": int(env.get("IMAP_PORT", cfg.get("imap_port", 993))),
    })

    if merged.get("csv_path"):
        merged["csv_path"] = str(BASE_DIR / merged["csv_path"])

    return merged

