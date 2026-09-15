"""Separate immutable application resources from persistent runtime data."""

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("BLOG_DATA_DIR", str(APP_DIR))).expanduser().resolve()
