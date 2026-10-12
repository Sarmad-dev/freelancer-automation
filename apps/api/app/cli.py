"""Operational commands: ``python -m app.cli <command>``.

Commands
- ``seed``            Insert idempotent development seed data (development/test only).
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    export = sub.add_parser("export-openapi")
    export.add_argument("target")
    args = parser.parse_args(argv)
    try:
        if args.command == "seed":
            return seed()
        return export_openapi(args.target)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
