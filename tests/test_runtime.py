import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import server


class RuntimeTests(unittest.TestCase):
    def test_powershell_helpers_and_receiver_resolve_the_same_data_directory(self):
        helper = Path(__file__).resolve().parents[1] / "PocketLens Runtime.ps1"
        command = (
            "$ErrorActionPreference = 'Stop'; "
            ". $env:POCKETLENS_TEST_HELPER; "
            "[Console]::Write((Get-PocketLensDataDirectory))"
        )
        with tempfile.TemporaryDirectory() as directory:
            for override, local, roaming in (
                (directory, "", ""),
                ("relative-data", "", ""),
                ("", directory, ""),
                ("", "", directory),
                ("", "", ""),
            ):
                with self.subTest(override=override, local=local, roaming=roaming):
                    environment = {
                        **os.environ,
                        "POCKETLENS_DATA_DIR": override,
                        "LOCALAPPDATA": local,
                        "APPDATA": roaming,
                        "POCKETLENS_TEST_HELPER": str(helper),
                    }
                    with patch.dict(os.environ, environment):
                        expected = server.data_directory()
                    output = subprocess.check_output(
                        ["powershell.exe", "-NoProfile", "-Command", command],
                        env=environment,
                        text=True,
                    )
                    # Junctions can spell the same runtime directory differently.
                    self.assertEqual(Path(output).resolve(), expected.resolve())
