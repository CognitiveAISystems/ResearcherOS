"""ResearchOS widget runtime (base classes + discovery). Packages live in koi-structure."""

from __future__ import annotations

from pathlib import Path

__all__ = ["WIDGETS_ROOT"]

WIDGETS_ROOT = Path(__file__).resolve().parent
