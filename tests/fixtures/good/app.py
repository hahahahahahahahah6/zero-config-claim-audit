from pathlib import Path
if Path("settings.toml").exists():
    text = Path("settings.toml").read_text()
