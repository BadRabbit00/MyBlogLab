#!/usr/bin/env bash
set -euo pipefail

# No external services or credentials are used by this test.
docker run --rm --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /data:rw,uid=10001,gid=10001,mode=0700 \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  blog-agent:latest python3 -c '
import os
from pathlib import Path
from src import bot, plan
from src.image import generate_card
from src.paths import DATA_DIR
from src.validation import require_plain_text
assert os.getuid() == 10001
assert DATA_DIR == Path("/data")
post = plan.next_for("draft")
assert post is not None
plan.advance(post.id, status="drafted")
assert plan.get_post(post.id).status == "drafted"
assert generate_card(post.id).stat().st_size > 1000
require_plain_text("Linux: флаг --help и условие x < y.")
print("Container smoke test passed")
'
