import ipaddress
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes

import server


class CertificateTests(unittest.TestCase):
    def test_unique_local_ca_is_preserved_and_leaf_tracks_ip(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(server, "STATE", Path(directory)),
        ):
            profile, fingerprint = server.certificates("192.168.1.20")
            root = x509.load_pem_x509_certificate((server.STATE / "root.pem").read_bytes())
            key = (server.STATE / "root-key.pem").read_bytes()
            self.assertEqual(root.fingerprint(hashes.SHA256()).hex(), fingerprint)
            payload = plistlib.loads(profile)
            self.assertEqual(payload["PayloadContent"][0]["PayloadType"], "com.apple.security.root")
            self.assertNotIn(b"PRIVATE KEY", profile)
            _, again = server.certificates("192.168.1.21")
            self.assertEqual(fingerprint, again)
            self.assertEqual(key, (server.STATE / "root-key.pem").read_bytes())
            leaf = x509.load_pem_x509_certificate((server.STATE / "server.pem").read_bytes())
            addresses = leaf.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value.get_values_for_type(x509.IPAddress)
            self.assertIn(ipaddress.ip_address("192.168.1.21"), addresses)
            self.assertIn(ipaddress.ip_address("127.0.0.1"), addresses)

    def test_state_directory_migrates_legacy_state_once(self):
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as data:
            legacy = Path(base) / "work" / "interview-camera-state"
            legacy.mkdir(parents=True)
            (legacy / "root.pem").write_text("legacy")
            with patch.object(server, "BASE", Path(base)):
                state = server.state_directory(Path(data))
            self.assertEqual((state / "root.pem").read_text(), "legacy")
            (state / "root.pem").write_text("current")
            with patch.object(server, "BASE", Path(base)):
                again = server.state_directory(Path(data))
            self.assertEqual((again / "root.pem").read_text(), "current")

    def test_data_directory_uses_override_then_local_app_data(self):
        with patch.dict("os.environ", {"POCKETLENS_DATA_DIR": r"D:\custom"}):
            self.assertEqual(server.data_directory(), Path(r"D:\custom"))
        with patch.dict("os.environ", {"POCKETLENS_DATA_DIR": "", "LOCALAPPDATA": r"C:\local"}):
            self.assertEqual(server.data_directory(), Path(r"C:\local") / "PocketLens")
