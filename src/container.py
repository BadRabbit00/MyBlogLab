"""Initialize a persistent data directory, then replace PID 1 with the command."""

import os
import shutil
import sys

from src.paths import APP_DIR, DATA_DIR


def initialize_data() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for directory in ("out/drafts", "out/images", "logs", "docs"):
        (DATA_DIR / directory).mkdir(parents=True, exist_ok=True)
    plan = DATA_DIR / "content-plan.yaml"
    if not plan.exists():
        shutil.copyfile(APP_DIR / "examples/content-plan.yaml", plan)
    for source in (APP_DIR / "docs").glob("*.md"):
        target = DATA_DIR / "docs" / source.name
        if not target.exists():
            shutil.copyfile(source, target)


def main() -> None:
    initialize_data()
    command = sys.argv[1:] or ["python3", "-m", "src.bot"]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
