from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from scripts import package_release


class ReleaseTests(unittest.TestCase):
    def test_windows_archive_excludes_development_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = {
                "VERSION": "0.1.0",
                "README.md": "PocketLens",
                "pyproject.toml": "Development configuration",
                "web/phone.js": "Phone client",
                "scripts/unregister.py": "Uninstaller",
                "scripts/package_release.py": "Packager",
                "tests/test_camera.py": "Tests",
                "native/src/example.cpp": "Source",
            }
            for arch in ("x64", "x86"):
                for name in ("pocketlens.dll", "register-system.exe"):
                    sources[f"native/bin/{arch}/{name}"] = "Native binary"
            for name, content in sources.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            with patch.object(
                package_release, "ROOT_FILES", ("VERSION", "README.md", "pyproject.toml")
            ):
                archive = package_release.package(root, root / "dist", "windows")
            with zipfile.ZipFile(archive) as bundle:
                names = bundle.namelist()
                self.assertIn("pocketlens-0.1.0/scripts/unregister.py", names)
                self.assertIn("pocketlens-0.1.0/web/phone.js", names)
                for name in (
                    "pyproject.toml",
                    "scripts/package_release.py",
                    "tests/test_camera.py",
                    "native/src/example.cpp",
                ):
                    self.assertNotIn(f"pocketlens-0.1.0/{name}", names)

    def test_private_state_and_unlisted_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "VERSION").write_text("0.1.0")
            (root / "README.md").write_text("Public documentation")
            (root / "work").mkdir()
            (root / "work/root-key.pem").write_text("private state")
            (root / "private-notes.txt").write_text("private notes")
            with patch.object(package_release, "ROOT_FILES", ("VERSION", "README.md")):
                archive = package_release.package(root, root / "dist", "source")
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(
                    set(bundle.namelist()),
                    {"pocketlens-0.1.0/VERSION", "pocketlens-0.1.0/README.md"},
                )
            self.assertTrue(archive.with_suffix(".zip.sha256").is_file())

    def test_private_key_in_allowed_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("-----BEGIN " + "PRIVATE KEY-----\nsecret")
            with patch.object(package_release, "ROOT_FILES", ("README.md",)):
                with self.assertRaisesRegex(ValueError, "Private key detected"):
                    package_release.release_files(root, "source")
