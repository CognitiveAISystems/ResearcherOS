#!/usr/bin/env python3
"""Compatibility hook: Git checks are scheduled by ResearcherOS, not IDE sessions."""


def main() -> None:
    # Keep existing Cursor hook registrations working without extra Git checks.
    print("{}")


if __name__ == "__main__":
    main()
