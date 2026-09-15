"""Plan management module for blog-agent.

Handles atomic read and write operations on content-plan.yaml while preserving
comments, ordering, and structure via ruamel.yaml round-trip mode.
"""

from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile
from typing import Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from src.logger import get_logger

logger = get_logger("plan")

PLAN_PATH: Path = Path(__file__).resolve().parent.parent / "content-plan.yaml"


@dataclass
class Post:
    """Represents a scheduled post in the content plan."""

    id: str
    date: str
    slot: str
    rubric: str
    title: str
    thesis: str
    keywords: list[str]
    image_hint: str
    status: str
    draft_path: Optional[str] = None
    published_at: Optional[str] = None
    tg_message_id: Optional[int] = None
    needs_review: bool = False
    kill_reason: Optional[str] = None
    verify: bool = False
    doc_prefix: Optional[str] = None
    extra: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: CommentedMap | dict[str, object]) -> "Post":
        """Construct Post instance from YAML dictionary."""
        known_keys = {
            "id", "date", "slot", "rubric", "title", "thesis",
            "keywords", "image_hint", "status", "draft_path",
            "published_at", "tg_message_id", "needs_review",
            "kill_reason", "verify", "doc_prefix"
        }
        raw_keywords = data.get("keywords", [])
        keywords: list[str] = [str(k) for k in raw_keywords] if isinstance(raw_keywords, (list, CommentedSeq)) else []
        extra: dict[str, object] = {k: v for k, v in data.items() if k not in known_keys}

        return cls(
            id=str(data.get("id", "")),
            date=str(data.get("date", "")),
            slot=str(data.get("slot", "")),
            rubric=str(data.get("rubric", "")),
            title=str(data.get("title", "")).strip(),
            thesis=str(data.get("thesis", "")).strip(),
            keywords=keywords,
            image_hint=str(data.get("image_hint", "")).strip(),
            status=str(data.get("status", "pending")),
            draft_path=str(data["draft_path"]) if data.get("draft_path") else None,
            published_at=str(data["published_at"]) if data.get("published_at") else None,
            tg_message_id=int(data["tg_message_id"]) if data.get("tg_message_id") is not None else None,
            needs_review=bool(data.get("needs_review", False)),
            kill_reason=str(data["kill_reason"]) if data.get("kill_reason") else None,
            verify=bool(data.get("verify", False)),
            doc_prefix=str(data["doc_prefix"]) if data.get("doc_prefix") else None,
            extra=extra,
        )


@dataclass
class Plan:
    """Represents the complete content plan document."""

    meta: dict[str, object]
    posts: list[Post]
    raw_yaml: CommentedMap


def _get_yaml_parser() -> YAML:
    """Configure ruamel.yaml for strict round-trip preservation."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    return yaml


def load(path: Path = PLAN_PATH) -> Plan:
    """Load content plan from YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"Content plan not found at {path}")

    logger.debug(f"Loading content plan from {path}")
    yaml = _get_yaml_parser()
    with open(path, "r", encoding="utf-8") as f:
        raw_data: CommentedMap = yaml.load(f)

    meta_data = dict(raw_data.get("meta", {}))
    raw_posts = raw_data.get("posts", [])

    posts: list[Post] = [
        Post.from_dict(raw_post)
        for raw_post in raw_posts
        if isinstance(raw_post, (dict, CommentedMap))
    ]
    logger.debug(f"Loaded {len(posts)} posts from plan")
    return Plan(meta=meta_data, posts=posts, raw_yaml=raw_data)


def save_atomic(data: CommentedMap, target_path: Path = PLAN_PATH) -> None:
    """Atomically write YAML data to disk using a temporary file and os.replace."""
    yaml = _get_yaml_parser()
    target_dir = target_path.parent
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile("w", dir=target_dir, encoding="utf-8", delete=False) as tmp_file:
        tmp_name = tmp_file.name
        yaml.dump(data, tmp_file)
        tmp_file.flush()
        os.fsync(tmp_file.fileno())

    os.replace(tmp_name, target_path)
    logger.debug(f"Atomically saved plan to {target_path}")


def get_post(post_id: str, plan_path: Path = PLAN_PATH) -> Optional[Post]:
    """Find a post by its identifier."""
    plan = load(plan_path)
    for post in plan.posts:
        if post.id == post_id:
            return post
    return None


def next_for(step: str, plan_path: Path = PLAN_PATH) -> Optional[Post]:
    """Return the nearest upcoming post waiting for the given pipeline step.

    Step mapping:
      'draft': status 'pending', excluding manual 'dnevnik' rubric
      'critique': status 'drafted'
      'image': status 'drafted' or 'queued'
      'publish': status 'queued'
    """
    plan = load(plan_path)

    step_status_map: dict[str, str] = {
        "draft": "pending",
        "critique": "drafted",
        "publish": "queued",
    }
    target_status = step_status_map.get(step, step)

    for post in plan.posts:
        if post.status == target_status:
            if target_status == "pending" and post.rubric == "dnevnik":
                continue  # дневник пишется вручную человеком
            return post
    return None


def all_for(step: str, plan_path: Path = PLAN_PATH) -> list[Post]:
    """Return all posts matching the target step."""
    plan = load(plan_path)
    step_status_map: dict[str, str] = {
        "draft": "pending",
        "critique": "drafted",
        "publish": "queued",
    }
    target_status = step_status_map.get(step, step)

    result: list[Post] = []
    for post in plan.posts:
        if post.status == target_status:
            if target_status == "pending" and post.rubric == "dnevnik":
                continue
            result.append(post)
    return result


def advance(post_id: str, status: str, plan_path: Path = PLAN_PATH, **fields: object) -> None:
    """Update post status and auxiliary fields atomically in content-plan.yaml."""
    yaml = _get_yaml_parser()
    with open(plan_path, "r", encoding="utf-8") as f:
        data: CommentedMap = yaml.load(f)

    posts_list: CommentedSeq = data.get("posts", [])
    found = False

    for item in posts_list:
        if isinstance(item, (dict, CommentedMap)) and item.get("id") == post_id:
            item["status"] = status
            for key, value in fields.items():
                item[key] = value
            found = True
            break

    if not found:
        logger.error(f"Post with id '{post_id}' not found in content plan.")
        raise KeyError(f"Post with id '{post_id}' not found in content plan.")

    save_atomic(data, plan_path)
    logger.info(f"Post #{post_id} status updated -> '{status}' (fields: {list(fields.keys())})")


def kill(post_id: str, reason: str, plan_path: Path = PLAN_PATH) -> None:
    """Mark post as killed with an explicit diagnostic reason."""
    logger.warning(f"Killing post #{post_id}. Reason: {reason}")
    advance(post_id, status="killed", plan_path=plan_path, kill_reason=reason)


def recent_published(n: int = 10, plan_path: Path = PLAN_PATH) -> list[Post]:
    """Return the last n published posts in chronological order."""
    plan = load(plan_path)
    published = [p for p in plan.posts if p.status == "published"]
    return published[-n:]


def get_stats(plan_path: Path = PLAN_PATH) -> dict[str, int]:
    """Calculate aggregate status counts across all posts."""
    plan = load(plan_path)
    stats: dict[str, int] = {
        "total": len(plan.posts),
        "pending": 0,
        "drafted": 0,
        "queued": 0,
        "published": 0,
        "killed": 0,
        "needs_review": 0,
    }
    for post in plan.posts:
        stats[post.status] = stats.get(post.status, 0) + 1
        if post.needs_review:
            stats["needs_review"] += 1
    return stats
