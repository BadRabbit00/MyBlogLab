"""Command-line interface (CLI) for blog-agent.

Provides commands for managing the autonomous content pipeline:
draft, critique, image, review, kill, publish, status, stats, and full pipeline execution.
"""

import argparse
from datetime import datetime, date
from pathlib import Path
import sys
from typing import Optional

from src.critique import run_all_drafted, run_critique
from src.draft import run_all_pending, run_draft
from src.image import generate_all_cards, generate_card
import src.plan as plan
from src.publish import run_publish

BASE_DIR: Path = Path(__file__).resolve().parent.parent


def cmd_status(args: argparse.Namespace) -> None:
    """Display comprehensive status of the pipeline and upcoming posts."""
    stats = plan.get_stats()
    content_plan = plan.load()

    print("\n" + "=" * 50)
    print(" 📡 BLOG-AGENT :: PIPELINE STATUS")
    print("=" * 50)
    print(f" Target Channel : {content_plan.meta.get('channel', 'N/A')}")
    print(f" Schedule Period: {content_plan.meta.get('start', '')} → {content_plan.meta.get('end', '')}")
    print("-" * 50)
    print(f" Total Posts    : {stats.get('total', 0)}")
    print(f"  ├─ Pending    : {stats.get('pending', 0)}")
    print(f"  ├─ Drafted    : {stats.get('drafted', 0)}")
    print(f"  ├─ Queued     : {stats.get('queued', 0)} (⚠️ needs review: {stats.get('needs_review', 0)})")
    print(f"  ├─ Published  : {stats.get('published', 0)}")
    print(f"  └─ Killed     : {stats.get('killed', 0)}")
    print("-" * 50)

    # Next slots
    next_draft = plan.next_for("draft")
    next_critique = plan.next_for("critique")
    next_publish = plan.next_for("publish")

    print(" 🎯 NEXT ACTIONS:")
    if next_draft:
        print(f"  Drafting : [{next_draft.id}] ({next_draft.date} {next_draft.slot}) «{next_draft.title}»")
    else:
        print("  Drafting : No pending posts.")

    if next_critique:
        print(f"  Critique : [{next_critique.id}] «{next_critique.title}»")
    else:
        print("  Critique : No drafted posts waiting for critique.")

    if next_publish:
        flag = " [NEEDS REVIEW!]" if next_publish.needs_review else ""
        print(f"  Publish  : [{next_publish.id}] ({next_publish.date} {next_publish.slot}) «{next_publish.title}»{flag}")
    else:
        print("  Publish  : Queue is empty.")

    print("=" * 50 + "\n")


def cmd_stats(args: argparse.Namespace) -> None:
    """Display in-depth analytics for project diaries and reports."""
    content_plan = plan.load()
    total = len(content_plan.posts)
    rubric_counts: dict[str, int] = {}
    rubric_published: dict[str, int] = {}

    for p in content_plan.posts:
        rubric_counts[p.rubric] = rubric_counts.get(p.rubric, 0) + 1
        if p.status == "published":
            rubric_published[p.rubric] = rubric_published.get(p.rubric, 0) + 1

    stats = plan.get_stats()
    published_total = stats.get("published", 0)
    pct = (published_total / total * 100) if total else 0.0

    print("\n" + "=" * 55)
    print(f" 📊 BLOG-AGENT METRICS (Progress: {published_total}/{total} — {pct:.1f}%)")
    print("=" * 55)
    print(f" {'RUBRIC':<14} | {'PLANNED':<8} | {'PUBLISHED':<10} | {'COMPLETION':<10}")
    print("-" * 55)
    for rubric, count in rubric_counts.items():
        pub = rubric_published.get(rubric, 0)
        rubric_pct = (pub / count * 100) if count else 0.0
        print(f" {rubric:<14} | {count:<8} | {pub:<10} | {rubric_pct:>6.1f}%")
    print("=" * 55 + "\n")


def cmd_draft(args: argparse.Namespace) -> None:
    """Generate drafts for pending posts."""
    if args.all_pending:
        count = run_all_pending()
        print(f"[+] Drafted {count} pending posts.")
    else:
        target_id = args.id
        ok = run_draft(post_id=target_id)
        if ok:
            print(f"[+] Post {target_id or 'next'} successfully drafted.")
        else:
            print(f"[-] Failed to draft post {target_id or 'next'} (check logs or kill reason).")
            sys.exit(1)


def cmd_critique(args: argparse.Namespace) -> None:
    """Refine drafted posts using critique prompt with Gemma 4 thinking mode."""
    if args.all_drafted:
        count = run_all_drafted()
        print(f"[+] Critiqued {count} drafted posts.")
    else:
        target_id = args.id
        ok = run_critique(post_id=target_id)
        if ok:
            print(f"[+] Post {target_id or 'next'} successfully critiqued and queued.")
        else:
            print(f"[-] Critique failed for post {target_id or 'next'}.")
            sys.exit(1)


def cmd_image(args: argparse.Namespace) -> None:
    """Generate social card PNG images."""
    if args.all:
        count = generate_all_cards()
        print(f"[+] Generated {count} social cards in out/images/.")
    else:
        target_id = args.id
        if not target_id:
            # Pick next queued or drafted post
            post = plan.next_for("publish") or plan.next_for("critique")
            if not post:
                print("[-] No post specified or found in active pipeline.")
                sys.exit(1)
            target_id = post.id
        path = generate_card(target_id)
        print(f"[+] Generated card: {path}")


def cmd_review(args: argparse.Namespace) -> None:
    """Inspect queued posts awaiting publication."""
    queued_posts = plan.all_for("publish")
    if not queued_posts:
        print("\n[i] Queue is empty. No posts currently in 'queued' status.\n")
        return

    print("\n" + "=" * 60)
    print(f" 🔍 REVIEW QUEUE ({len(queued_posts)} posts waiting)")
    print("=" * 60)

    for post in queued_posts:
        review_badge = " [⚠️ NEEDS REVIEW]" if post.needs_review else " [✅ READY]"
        print(f"\n--- Post #{post.id.upper()} | {post.date} ({post.slot}) | {post.rubric.upper()}{review_badge} ---")
        print(f"Title: {post.title}")
        print(f"Thesis: {post.thesis}")

        draft_file = BASE_DIR / (post.draft_path or f"out/drafts/{post.id}.md")
        if draft_file.exists():
            with open(draft_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            print(f"Length: {len(content)} chars")
            print("Content:\n" + content)
        else:
            print("[!] Draft file missing!")

    print("\n" + "=" * 60 + "\n")


def cmd_kill(args: argparse.Namespace) -> None:
    """Mark a post as killed with an explicit reason."""
    post_id = args.id
    reason = args.reason
    plan.kill(post_id, reason=reason)
    print(f"[+] Post {post_id} marked as killed. Reason: {reason}")


def cmd_publish(args: argparse.Namespace) -> None:
    """Publish queued post to Telegram."""
    target_id = args.id
    dry_run = args.dry_run
    try:
        ok = run_publish(post_id=target_id, dry_run=dry_run)
        if ok:
            status_text = "DRY-RUN simulation finished" if dry_run else "published to Telegram"
            print(f"[+] Post {target_id or 'next'} successfully {status_text}.")
        else:
            print(f"[-] No post found to publish.")
            sys.exit(1)
    except Exception as exc:
        print(f"[!] Publication error: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_pipeline(args: argparse.Namespace) -> None:
    """Run full automated pipeline for one post: draft -> critique -> card."""
    post_id = args.id
    post = plan.get_post(post_id) if post_id else plan.next_for("draft")
    if not post:
        print("[-] No pending post found to process.")
        sys.exit(1)

    print(f"[*] Starting end-to-end pipeline for post {post.id}: «{post.title}»")

    # 1. Draft
    print("  [1/3] Drafting post with Gemma 4...")
    if not run_draft(post.id):
        print(f"[-] Step 1 (Draft) failed for {post.id}.")
        sys.exit(1)
    print("  [+] Draft created.")

    # 2. Critique
    print("  [2/3] Running critique with deep thinking mode...")
    if not run_critique(post.id):
        print(f"[-] Step 2 (Critique) failed for {post.id}.")
        sys.exit(1)
    print("  [+] Critique complete. Post transitioned to 'queued'.")

    # 3. Image
    print("  [3/3] Rendering card PNG...")
    img_path = generate_card(post.id)
    print(f"  [+] Card rendered: {img_path}")

    print(f"[✨] Post {post.id} successfully processed and queued for review/publishing!\n")


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(prog="blog", description="Autonomous Telegram blog agent pipeline")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Show pipeline status and upcoming slots")
    p_status.set_defaults(func=cmd_status)

    # stats
    p_stats = subparsers.add_parser("stats", help="Show progress statistics and metrics")
    p_stats.set_defaults(func=cmd_stats)

    # draft
    p_draft = subparsers.add_parser("draft", help="Generate drafts for posts")
    p_draft.add_argument("--id", help="Specific post id (e.g. w1-01)")
    p_draft.add_argument("--all-pending", action="store_true", help="Draft all pending posts")
    p_draft.set_defaults(func=cmd_draft)

    # critique
    p_critique = subparsers.add_parser("critique", help="Critique and refine drafted posts")
    p_critique.add_argument("--id", help="Specific post id")
    p_critique.add_argument("--all-drafted", action="store_true", help="Critique all drafted posts")
    p_critique.set_defaults(func=cmd_critique)

    # image
    p_image = subparsers.add_parser("image", help="Generate card images via resvg")
    p_image.add_argument("--id", help="Specific post id")
    p_image.add_argument("--all", action="store_true", help="Generate cards for all posts")
    p_image.set_defaults(func=cmd_image)

    # review
    p_review = subparsers.add_parser("review", help="Review queued drafts")
    p_review.set_defaults(func=cmd_review)

    # kill
    p_kill = subparsers.add_parser("kill", help="Mark a post as killed")
    p_kill.add_argument("id", help="Post ID to kill")
    p_kill.add_argument("--reason", required=True, help="Reason for rejection")
    p_kill.set_defaults(func=cmd_kill)

    # publish
    p_publish = subparsers.add_parser("publish", help="Publish queued posts to Telegram")
    p_publish.add_argument("--id", help="Specific post id to publish")
    p_publish.add_argument("--dry-run", action="store_true", help="Simulate publication without sending")
    p_publish.set_defaults(func=cmd_publish)

    # pipeline
    p_pipeline = subparsers.add_parser("pipeline", help="Run full pipeline: draft -> critique -> card")
    p_pipeline.add_argument("--id", help="Specific post ID (defaults to next pending)")
    p_pipeline.set_defaults(func=cmd_pipeline)

    return parser


def main() -> None:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
