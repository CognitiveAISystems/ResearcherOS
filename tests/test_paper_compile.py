"""Tests for paper compile engine selection."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from koi.paper.generator import TEX_NAME, _slot_prefers_pdflatex, _which_tool


class PaperCompileRecipeTests(unittest.TestCase):
    def test_external_paper_prefers_pdflatex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            slot = Path(tmp)
            (slot / "paper.json").write_text(
                json.dumps({"source": "external", "format": "emnlp2023"}),
                encoding="utf-8",
            )
            (slot / TEX_NAME).write_text("\\documentclass{article}\n", encoding="utf-8")
            self.assertTrue(_slot_prefers_pdflatex(slot))

    def test_neurips_generated_slot_prefers_tectonic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            slot = Path(tmp)
            (slot / "paper.json").write_text(
                json.dumps({"format": "neurips2025"}),
                encoding="utf-8",
            )
            (slot / TEX_NAME).write_text(
                "\\documentclass{article}\n\\usepackage{neurips_2025}\n",
                encoding="utf-8",
            )
            (slot / "neurips_2025.sty").write_text("% stub", encoding="utf-8")
            self.assertFalse(_slot_prefers_pdflatex(slot))

    def test_bibliography_in_tex_prefers_pdflatex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            slot = Path(tmp)
            (slot / TEX_NAME).write_text(
                "\\documentclass{article}\n\\bibliography{custom}\n",
                encoding="utf-8",
            )
            self.assertTrue(_slot_prefers_pdflatex(slot))

    def test_which_tool_finds_binary_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / "bin"
            bindir.mkdir()
            tool = bindir / "pdflatex"
            tool.write_text("#!/bin/sh\n", encoding="utf-8")
            tool.chmod(0o755)
            listed = root / "paths"
            listed.write_text(f"{bindir}\n", encoding="utf-8")
            with patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}):
                with patch("koi.paper.generator._system_path_files", return_value=[listed]):
                    self.assertEqual(_which_tool("pdflatex"), str(tool))


if __name__ == "__main__":
    unittest.main()
