"""Widget contracts: manifest parsing, registry, enable/disable."""

from __future__ import annotations

from koi.widgets.base.manifest import WidgetManifest, parse_widget_dir
from koi.widgets.base.registry import (
    WidgetRecord,
    enabled_widget_ids,
    enabled_widget_keys,
    list_widgets,
    resolve_widget_asset,
    resolve_widget_dir,
    set_widget_enabled,
)

__all__ = [
    "WidgetManifest",
    "WidgetRecord",
    "enabled_widget_ids",
    "enabled_widget_keys",
    "list_widgets",
    "parse_widget_dir",
    "resolve_widget_asset",
    "resolve_widget_dir",
    "set_widget_enabled",
]
