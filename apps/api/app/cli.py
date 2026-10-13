"""Operational commands: ``python -m app.cli <command>``.

Commands
- ``seed``            Insert idempotent development seed data (development/test only).
- ``process-jobs``    Classify queued inbound messages (``--loop`` keeps running as a worker).
- ``ai-eval``         Run the AI evaluation fixtures against the configured provider (exit 1 on any failure).
- ``export-openapi``  Write the OpenAPI document used to generate frontend types.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import ConfigError, get_settings
from app.db.models import AppMetadata
from app.db.session import get_sessionmaker
from app.seed import DEMO_EMAIL, DEMO_PASSWORD, seed_demo

SEED_MARKER_KEY = "seed.scaffold"


def seed() -> int:
    settings = get_settings()
    if settings.app_env not in ("development", "test"):
        print(
            f"Refusing to seed: APP_ENV={settings.app_env} (development/test only).",
            file=sys.stderr,
        )
        return 1
    with get_sessionmaker()() as session:
        existing = session.scalar(select(AppMetadata).where(AppMetadata.key == SEED_MARKER_KEY))
        if existing is None:
            session.add(AppMetadata(key=SEED_MARKER_KEY, value="applied"))
            session.commit()
            print("Seed applied.")
        else:
            print("Seed already applied; nothing to do.")
        created, _workspace_id = seed_demo(session)
        session.commit()
        if created:
            print(
                f"Demo data created. Sign in as {DEMO_EMAIL} / '{DEMO_PASSWORD}' (development only)."
            )
        else:
            print("Demo data already present; nothing to do.")
    return 0


def export_openapi(target: str) -> int:
    from app.main import create_app

    schema = create_app().openapi()
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {path}")
    return 0


def process_jobs(loop: bool, interval: float) -> int:
    import time

    from app.main import create_app
    from app.services.email_jobs import run_worker

    app = create_app()
    while True:
        stats = run_worker(app)
        if stats.claimed:
            print(
                f"claimed={stats.claimed} classified={stats.classified} retried={stats.retried} "
                f"failed={stats.failed} skipped={stats.skipped}"
            )
        if not loop:
            return 0
        time.sleep(interval)


def ai_eval() -> int:
    from app.ai.evals import run_evals
    from app.ai.factory import build_provider

    provider = build_provider(get_settings())
    if provider.name == "disabled":
        print("AI is disabled (AI_PROVIDER=disabled); nothing to evaluate.", file=sys.stderr)
        return 1
    report = run_evals(provider)
    kind = (
        "rule-based demo stand-in (measures the stand-in and the safety checks, not a model)"
        if report.is_mock
        else "live provider"
    )
    print(f"Evaluated provider: {report.provider}, {kind}")
    for task, (passed, total) in report.by_task().items():
        print(f"  {task:<24} {passed}/{total}")
    for r in report.results:
        if not r.passed:
            print(f"  FAIL {r.id}: {r.reason}")
    print(f"Total: {report.passed}/{report.total}")
    return 0 if report.passed == report.total else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    jobs = sub.add_parser("process-jobs")
    jobs.add_argument(
        "--loop",
        action="store_true",
        help="keep running instead of exiting when the queue is empty",
    )
    jobs.add_argument(
        "--interval", type=float, default=5.0, help="seconds between polls with --loop"
    )
    sub.add_parser("ai-eval")
    export = sub.add_parser("export-openapi")
    export.add_argument("target")
    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            return seed()
        if args.command == "process-jobs":
            return process_jobs(args.loop, args.interval)
        if args.command == "ai-eval":
            return ai_eval()
        return export_openapi(args.target)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
