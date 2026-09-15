"""Tests for src/plan.py - Content plan management and state machine."""

import pytest
from pathlib import Path
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from src.plan import (
    Post,
    Plan,
    load,
    save_atomic,
    get_post,
    next_for,
    all_for,
    advance,
    kill,
    recent_published,
    get_stats,
    _get_yaml_parser,
)

SAMPLE_YAML_CONTENT = """meta:
  channel: "@test_channel"
  description: "Test channel"
  total_weeks: 1

posts:
  - id: "w1-01"
    week: 1
    day: "Пн"
    rubric: "razbor"
    title: "Тестовый пост 1"
    thesis: "Тезис 1"
    keywords: ["тест", "архитектура"]
    status: "pending"
    doc_prefix: "POST1"

  - id: "w1-02"
    week: 1
    day: "Вт"
    rubric: "dnevnik"
    title: "Тестовый дневник"
    thesis: "Личный тезис"
    keywords: ["дневник"]
    status: "pending"
    doc_prefix: "POST2"

  - id: "w1-03"
    week: 1
    day: "Ср"
    rubric: "keys"
    title: "Тестовый кейс"
    thesis: "Кейс тезис"
    keywords: ["кейс"]
    status: "drafted"
    doc_prefix: "POST3"
    draft_path: "out/drafts/w1-03.md"

  - id: "w1-04"
    week: 1
    day: "Чт"
    rubric: "instrument"
    title: "Тестовый инструмент"
    thesis: "Инструмент тезис"
    keywords: ["инструмент"]
    status: "published"
    doc_prefix: "POST4"
    published_at: "2026-09-01T12:00:00Z"
"""


@pytest.fixture
def temp_plan(tmp_path: Path) -> Path:
    plan_file = tmp_path / "content-plan.yaml"
    plan_file.write_text(SAMPLE_YAML_CONTENT, encoding="utf-8")
    return plan_file


def test_load_plan(temp_plan: Path):
    plan = load(temp_plan)
    assert plan.meta.get("channel") == "@test_channel"
    assert len(plan.posts) == 4

    p1 = plan.posts[0]
    assert p1.id == "w1-01"
    assert p1.rubric == "razbor"
    assert p1.title == "Тестовый пост 1"
    assert p1.status == "pending"
    assert p1.doc_prefix == "POST1"
    assert "тест" in p1.keywords


def test_load_nonexistent_file(tmp_path: Path):
    missing_file = tmp_path / "does_not_exist.yaml"
    with pytest.raises(FileNotFoundError):
        load(missing_file)


def test_get_post(temp_plan: Path):
    p = get_post("w1-01", plan_path=temp_plan)
    assert p is not None
    assert p.id == "w1-01"
    assert p.rubric == "razbor"

    missing = get_post("non-existent-id", plan_path=temp_plan)
    assert missing is None


def test_next_for_draft(temp_plan: Path):
    # Should find w1-01 (pending), skipping w1-02 (dnevnik is manual)
    p = next_for("draft", plan_path=temp_plan)
    assert p is not None
    assert p.id == "w1-01"


def test_next_for_critique(temp_plan: Path):
    # Should find w1-03 (drafted)
    p = next_for("critique", plan_path=temp_plan)
    assert p is not None
    assert p.id == "w1-03"


def test_all_for(temp_plan: Path):
    pending = all_for("draft", plan_path=temp_plan)
    assert len(pending) == 1
    assert pending[0].id == "w1-01"

    drafted = all_for("critique", plan_path=temp_plan)
    assert len(drafted) == 1
    assert drafted[0].id == "w1-03"


def test_advance_status(temp_plan: Path):
    advance(
        "w1-01",
        status="drafted",
        plan_path=temp_plan,
        draft_path="out/drafts/w1-01.md",
        custom_note="test note",
    )
    updated = get_post("w1-01", plan_path=temp_plan)
    assert updated is not None
    assert updated.status == "drafted"
    assert updated.draft_path == "out/drafts/w1-01.md"


def test_advance_unknown_post_raises(temp_plan: Path):
    with pytest.raises(KeyError):
        advance("w99-99", status="drafted", plan_path=temp_plan)


def test_kill_post(temp_plan: Path):
    kill("w1-01", reason="Topic no longer relevant", plan_path=temp_plan)
    p = get_post("w1-01", plan_path=temp_plan)
    assert p is not None
    assert p.status == "killed"


def test_recent_published(temp_plan: Path):
    published = recent_published(plan_path=temp_plan, n=5)
    assert len(published) == 1
    assert published[0].id == "w1-04"


def test_get_stats(temp_plan: Path):
    stats = get_stats(plan_path=temp_plan)
    assert stats["total"] == 4
    assert stats["pending"] == 2
    assert stats["drafted"] == 1
    assert stats["published"] == 1
    assert stats["queued"] == 0
    assert stats["killed"] == 0
