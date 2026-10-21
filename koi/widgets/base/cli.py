#!/usr/bin/env python3
"""CLI: list / enable / disable ResearchOS widgets (from koi-structure)."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ResearchOS widgets")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List discovered widgets")
    p_list.add_argument("--json", action="store_true")
    p_list.add_argument("--all", action="store_true", help="Include broken packages")

    p_en = sub.add_parser("enable", help="Enable a widget (id or project/id)")
    p_en.add_argument("widget")

    p_dis = sub.add_parser("disable", help="Disable a widget (id or project/id)")
    p_dis.add_argument("widget")

    p_show = sub.add_parser("show", help="Show one widget")
    p_show.add_argument("widget")
    p_show.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    from koi.widgets.base.registry import list_widgets, set_widget_enabled

    if args.cmd == "list":
        rows = list_widgets(ok_only=not args.all)
        if args.json:
            print(json.dumps([r.to_public_dict() for r in rows], ensure_ascii=False, indent=2))
            return 0
        if not rows:
            print("(no widgets — add packages under koi-structure/widgets/)")
            return 0
        for r in rows:
            flag = "ON " if r.enabled else "off"
            where = r.manifest.project_id or r.manifest.source
            err = "" if r.manifest.ok else f"  ERRORS={r.manifest.errors}"
            print(f"[{flag}] {r.key:40} ({where})  {r.manifest.title}{err}")
        return 0

    if args.cmd == "show":
        rows = list_widgets(ok_only=False)
        rec = next((r for r in rows if r.key == args.widget or r.id == args.widget), None)
        if rec is None:
            print(f"unknown widget: {args.widget}", file=sys.stderr)
            return 1
        payload = rec.to_public_dict()
        if not rec.manifest.ok:
            payload["errors"] = list(rec.manifest.errors)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if rec.manifest.ok else 1

    if args.cmd in {"enable", "disable"}:
        try:
            rec = set_widget_enabled(args.widget, args.cmd == "enable")
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        state = "enabled" if rec.enabled else "disabled"
        print(f"{rec.key}: {state}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
