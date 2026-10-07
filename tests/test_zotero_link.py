import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from koi.adapters.project_mount import ProjectMount
from koi.adapters.project_sync import _copy_koi_tree
from koi.literature.selection import read_selection, write_selection
from koi.literature.zotero_link import (
    clear_zotero_link,
    read_zotero_link,
    write_zotero_link,
)


class ZoteroLinkTests(unittest.TestCase):
    def test_account_is_shared_outside_the_project_tree(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            koi = root / "repo" / "koi-structure"
            koi.mkdir(parents=True)
            (koi / "project.md").write_text("keep\n", encoding="utf-8")
            account = root / "run" / "zotero.local.json"
            with (
                patch("koi.literature.zotero_link.koi_root", return_value=koi),
                patch("koi.literature.zotero_link.account_path", return_value=account),
                patch("koi.literature.zotero_link._legacy_links", side_effect=lambda: iter(())),
            ):
                write_zotero_link(
                    "demo",
                    api_key="secret-key",
                    user_id="16171270",
                    username="zoya",
                    collection_key="ABC123",
                    collection_name="SLM",
                )
                self.assertFalse((koi / "zotero.local.json").exists())
                saved = read_zotero_link("demo")
                self.assertIsNotNone(saved)
                assert saved is not None
                self.assertEqual(saved["api_key"], "secret-key")
                self.assertEqual(saved["collection_name"], "SLM")

                account.unlink()
                (koi / "zotero.local.json").write_text(
                    json.dumps({"api_key": "secret-key", "collection_key": "ABC123"}),
                    encoding="utf-8",
                )
                migrated = read_zotero_link("demo")
                assert migrated is not None
                self.assertEqual(migrated["collection_key"], "ABC123")
                self.assertTrue(account.is_file())

                target = root / "worktree"
                target.mkdir()
                mount = ProjectMount(
                    project_id="demo",
                    repo_root=root / "repo",
                    koi_root=koi,
                    code_root=root / "repo",
                    programs=(),
                )
                _copy_koi_tree(mount, target)
                copied = target / "koi-structure"
                self.assertEqual((copied / "project.md").read_text(encoding="utf-8"), "keep\n")
                self.assertFalse((copied / "zotero.local.json").exists())

                clear_zotero_link("demo")
                self.assertIsNone(read_zotero_link("demo"))
                self.assertFalse(account.exists())
                self.assertFalse((koi / "zotero.local.json").exists())

    def test_blank_key_is_not_a_link(self) -> None:
        with TemporaryDirectory() as tmp:
            koi = Path(tmp)
            (koi / "zotero.local.json").write_text(
                json.dumps({"api_key": "  "}),
                encoding="utf-8",
            )
            with (
                patch("koi.literature.zotero_link.koi_root", return_value=koi),
                patch("koi.literature.zotero_link.account_path", return_value=koi / "account.json"),
                patch("koi.literature.zotero_link._legacy_links", side_effect=lambda: iter(())),
            ):
                self.assertIsNone(read_zotero_link("demo"))

    def test_selection_keeps_one_row_per_url(self) -> None:
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with patch("koi.literature.selection.literature_dir", return_value=folder):
                saved = write_selection(
                    "demo",
                    [
                        {
                            "url": "https://arxiv.org/abs/1",
                            "title": "TinyStories",
                            "authors": "Eldan",
                            "year": "2023",
                        },
                        {"url": "  ", "title": "skip"},
                        {"url": "https://arxiv.org/abs/1", "title": "dup"},
                    ],
                )
                self.assertEqual(len(saved), 1)
                self.assertEqual(read_selection("demo")[0]["title"], "TinyStories")


if __name__ == "__main__":
    unittest.main()
