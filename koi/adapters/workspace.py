"""Engine layout and runtime paths.

ENGINE_ROOT — product code (this repository).
Project data is discovered via ``koi/adapters/project_mount.py``
(``tree/*/koi-structure/``, plus legacy ``*/koi-structure/``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent.parent


def _runtime_data_dir() -> Path:
    """Writable app state; source checkouts keep their historical layout."""
    configured = os.environ.get("KOI_DATA_DIR", "").strip()
    return Path(configured).expanduser().resolve() if configured else ENGINE_ROOT


@dataclass(frozen=True)
class Workspace:
    engine_root: Path
    run_dir: Path
    scan_roots: tuple[Path, ...]
    legacy_data_root: Path | None

    @property
    def experiment_report_template(self) -> Path:
        return (
            self.engine_root
            / "agents"
            / "skills"
            / "koi-report-review"
            / "experiment-report.md"
        )

    @property
    def env_file(self) -> Path:
        return _runtime_data_dir() / ".env"

    @property
    def scripts_dir(self) -> Path:
        return self.engine_root / "scripts"

    @property
    def venv_python(self) -> Path:
        return self.engine_root / ".venv" / "bin" / "python"

    @property
    def tools_dir(self) -> Path:
        return _runtime_data_dir() / ".tools"

    @property
    def library_upload(self) -> Path:
        """Primary CSV path for library uploads (legacy workspace fallback)."""
        if self.legacy_data_root:
            return self.legacy_data_root / "library" / "library.csv"
        return _runtime_data_dir() / "library" / "library.csv"

    def library_csv_candidates(self) -> tuple[Path, ...]:
        from koi.adapters.project_mount import list_mounts

        candidates: list[Path] = []
        for mount in list_mounts():
            for rel in ("library/library.csv", "library.csv"):
                p = mount.koi_root / rel
                if p.is_file():
                    candidates.append(p)
        if self.legacy_data_root:
            lib = self.legacy_data_root / "library"
            candidates.extend(
                [
                    lib / "library.csv",
                    lib / "scene_graph_papers_abstract.csv",
                    self.legacy_data_root / "library_team" / "library.csv",
                    self.legacy_data_root
                    / "library_team"
                    / "scene_graph_papers_abstract.csv",
                ]
            )
        return tuple(dict.fromkeys(candidates))

    def relative_to_engine(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.engine_root.resolve()))

    def agent_cwd(self) -> Path:
        """Default working directory for LLM agents (parent of engine / scan root)."""
        if self.scan_roots:
            return self.scan_roots[0]
        return self.engine_root.parent

    def git_root(self) -> Path:
        """Git repo root for engine-level operations."""
        if (self.engine_root / ".git").is_dir():
            return self.engine_root
        if self.legacy_data_root and (self.legacy_data_root / ".git").is_dir():
            return self.legacy_data_root
        return self.engine_root


def _legacy_data_root() -> Path | None:
    raw = os.environ.get("KOI_WORKSPACE", "").strip()
    if raw:
        p = Path(raw).expanduser().resolve()
        return p if p.is_dir() else None
    sibling = (ENGINE_ROOT.parent / "koi-workspace").resolve()
    return sibling if sibling.is_dir() else None


def _scan_roots() -> tuple[Path, ...]:
    from koi.adapters.project_mount import scan_roots

    return scan_roots()


@lru_cache(maxsize=1)
def get_workspace() -> Workspace:
    return Workspace(
        engine_root=ENGINE_ROOT.resolve(),
        run_dir=_runtime_data_dir() / ".run",
        scan_roots=_scan_roots(),
        legacy_data_root=_legacy_data_root(),
    )


def reset_workspace_cache() -> None:
    """Clear cached layout (tests)."""
    get_workspace.cache_clear()
    from koi.adapters.project_mount import rescan_projects

    rescan_projects()


# Convenience re-export.
_ws = get_workspace()
WORKSPACE_ROOT = _ws.engine_root
RUN_DIR = _ws.run_dir
