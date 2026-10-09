import asyncio
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, WSServerHandshakeError, WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer
import cv2
import numpy as np

import server
from test_camera import memory_camera


LOCAL = {"Host": "127.0.0.1:8766", "Origin": "http://127.0.0.1:8766"}
PHONE = {"Origin": "https://127.0.0.1:8765"}


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.state = patch.object(server, "STATE", Path(self.directory.name))
        self.state.start()
        self.camera = memory_camera()
        self.camera.status = lambda: {
            "live": bool(self.camera.last_received),
            "frames": self.camera.frames,
        }
        self.stop = asyncio.Event()
        apps = server.create_apps(
            self.camera, "127.0.0.1", b"profile", "fingerprint", "test-secret", self.stop
        )
        self.phone, self.setup, self.dashboard = [TestClient(TestServer(app)) for app in apps]
        for client in (self.phone, self.setup, self.dashboard):
            await client.start_server()

    async def asyncTearDown(self):
        for client in (self.dashboard, self.setup, self.phone):
            await client.close()
        self.state.stop()
        self.directory.cleanup()

    async def test_dashboard_host_and_origin_guards(self):
        self.assertEqual((await self.dashboard.get("/status")).status, 403)
        self.assertEqual(
            (await self.dashboard.post("/shutdown", headers={"Host": LOCAL["Host"]})).status, 403
        )
        response = await self.dashboard.get("/status", headers=LOCAL)
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["app"], "pocketlens")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")
        self.assertIn("microphone=()", response.headers["Permissions-Policy"])
        policy = response.headers["Content-Security-Policy"]
        for directive in ("object-src 'none'", "base-uri 'self'", "form-action 'none'"):
            self.assertIn(directive, policy)

    async def test_preview_and_pairing_secret_are_not_on_lan_surfaces(self):
        for client in (self.phone, self.setup):
            for path in (
                "/status",
                "/preview-stream",
                "/qr",
                "/shutdown",
                "/camera-test",
                "/camera-test.js",
            ):
                self.assertEqual((await client.get(path)).status, 404)

    async def test_browser_check_is_served_only_on_local_dashboard(self):
        for path in ("/camera-test", "/camera-test.js"):
            response = await self.dashboard.get(path, headers=LOCAL)
            self.assertEqual(response.status, 200)
        info = await (await self.dashboard.get("/status", headers=LOCAL)).json()
        self.assertEqual(info["cameraName"], "PocketLens")

    async def test_phone_mirror_controls_output_and_syncs_dashboard_changes(self):
        response = await self.phone.get("/phone-mirror.js")
        self.assertEqual(response.status, 200)
        for path in ("/", "/legacy"):
            html = await (await self.phone.get(path)).text()
            self.assertIn('id="mirror"', html)
            self.assertIn("/phone-mirror.js", html)
        ws = await self.phone.ws_connect("/stream?token=test-secret", headers=PHONE)
        try:
            await ws.send_json({"type": "settings"})
            self.assertEqual(await ws.receive_json(timeout=2), {"type": "settings", "flip": False})
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            frame[:, :640] = (0, 0, 255)
            frame[:, 640:] = (255, 0, 0)
            self.camera.accept_bgr(frame)
            await ws.send_json({"type": "settings", "flip": True})
            self.assertEqual(await ws.receive_json(timeout=2), {"type": "settings", "flip": True})
            np.testing.assert_array_equal(self.camera.current()[400, 200], (255, 0, 0))
            self.assertEqual(
                json.loads((server.STATE / "settings.json").read_text()), {"flip": True}
            )
            response = await self.dashboard.post("/settings", json={"flip": False}, headers=LOCAL)
            self.assertEqual(response.status, 200)
            self.assertEqual(await ws.receive_json(timeout=2), {"type": "settings", "flip": False})
            np.testing.assert_array_equal(self.camera.current()[400, 200], (0, 0, 255))
            jpeg = cv2.imencode(".jpg", frame)[1].tobytes()
            await ws.send_bytes(jpeg)
            self.assertEqual((await ws.receive(timeout=2)).data, "ack")
        finally:
            await ws.close()

    async def test_phone_mirror_rejects_invalid_values(self):
        ws = await self.phone.ws_connect("/stream?token=test-secret", headers=PHONE)
        await ws.send_json({"type": "settings", "flip": "yes"})
        self.assertEqual((await ws.receive(timeout=2)).type, WSMsgType.CLOSE)
        self.assertFalse(self.camera.flip)
        self.assertFalse((server.STATE / "settings.json").exists())
        await ws.close()

    async def test_websocket_auth_origin_and_single_sender(self):
        for query, headers, expected in (
            ("wrong", PHONE, 403),
            ("é", PHONE, 403),
            ("", PHONE, 403),
            ("test-secret", {"Origin": "https://evil.example"}, 403),
        ):
            with self.assertRaises(WSServerHandshakeError) as error:
                await self.phone.ws_connect("/stream?token=" + query, headers=headers)
            self.assertEqual(error.exception.status, expected)
        ws = await self.phone.ws_connect("/stream?token=test-secret", headers=PHONE)
        try:
            with self.assertRaises(WSServerHandshakeError) as error:
                await self.phone.ws_connect("/stream?token=test-secret", headers=PHONE)
            self.assertEqual(error.exception.status, 409)
            jpeg = cv2.imencode(".jpg", np.zeros((100, 100, 3), dtype=np.uint8))[1].tobytes()
            await ws.send_bytes(jpeg)
            self.assertEqual((await ws.receive(timeout=2)).data, "ack")
            self.assertEqual(self.camera.frames, 1)
        finally:
            await ws.close()
        await asyncio.sleep(0.05)
        self.assertEqual(self.camera.last_received, 0)
        second = await self.phone.ws_connect("/stream?token=test-secret", headers=PHONE)
        await second.close()

    async def test_invalid_signaling_releases_sender_slot(self):
        ws = await self.phone.ws_connect("/stream?token=test-secret", headers=PHONE)
        await ws.send_str("[]")
        self.assertEqual((await ws.receive(timeout=2)).type, WSMsgType.CLOSE)
        await ws.close()
        await asyncio.sleep(0.05)
        next_sender = await self.phone.ws_connect("/stream?token=test-secret", headers=PHONE)
        await next_sender.close()

    async def test_preview_stream_sends_frames_only_when_they_change(self):
        async def read_part(response):
            header = await asyncio.wait_for(response.content.readuntil(b"\r\n\r\n"), 2)
            length = int(re.search(rb"Content-Length: (\d+)", header).group(1))
            return await asyncio.wait_for(response.content.readexactly(length), 2)

        async with self.dashboard.get("/preview-stream", headers=LOCAL) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"\xff\xd8", await read_part(response))
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(response.content.readuntil(b"\r\n\r\n"), 0.4)
            self.camera.accept_bgr(np.zeros((720, 1280, 3), dtype=np.uint8))
            self.assertIn(b"\xff\xd8", await read_part(response))

    async def test_idle_preview_exits_when_the_dashboard_disconnects(self):
        app = server.create_apps(
            self.camera, "127.0.0.1", b"profile", "fingerprint", "test-secret", self.stop
        )[2]
        # TestServer enables handler cancellation; use production AppRunner defaults.
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        try:
            async with ClientSession() as client:
                port = runner.addresses[0][1]
                response = await client.get(
                    f"http://127.0.0.1:{port}/preview-stream", headers=LOCAL
                )
                await response.content.readuntil(b"\r\n\r\n")
                response.close()
                async with asyncio.timeout(2):
                    while runner.server.connections:
                        await asyncio.sleep(0.02)
        finally:
            self.stop.set()
            await runner.cleanup()

    async def test_preview_sends_waiting_slate_when_snapshot_expires_after_read(self):
        self.camera.accept_bgr(np.zeros((720, 1280, 3), dtype=np.uint8))
        original = self.camera.snapshot
        expired = False

        def snapshot():
            nonlocal expired
            result = original()
            if not expired:
                expired = True
                self.camera.last_received -= 2
            return result

        async def read_image(response):
            header = await asyncio.wait_for(response.content.readuntil(b"\r\n\r\n"), 2)
            length = int(re.search(rb"Content-Length: (\d+)", header).group(1))
            body = await asyncio.wait_for(response.content.readexactly(length), 2)
            return cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)

        with patch.object(self.camera, "snapshot", snapshot):
            async with self.dashboard.get("/preview-stream", headers=LOCAL) as response:
                self.assertEqual(np.max(await read_image(response)), 0)
                self.assertGreater(np.max(await read_image(response)), 100)

    async def test_token_check_reports_pairing_validity_without_upgrading(self):
        response = await self.phone.get("/token-check?token=test-secret")
        self.assertEqual(response.status, 204)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual((await self.phone.get("/token-check?token=stale")).status, 403)
        self.assertEqual((await self.setup.get("/token-check?token=test-secret")).status, 404)

    async def test_settings_reject_invalid_data_and_persist_valid_flip(self):
        for data in ([], {"flip": "yes"}, None):
            response = await self.dashboard.post(
                "/settings",
                data=json.dumps(data),
                headers={**LOCAL, "Content-Type": "application/json"},
            )
            self.assertEqual(response.status, 400)
        response = await self.dashboard.post(
            "/settings", data="{", headers={**LOCAL, "Content-Type": "application/json"}
        )
        self.assertEqual(response.status, 400)
        response = await self.dashboard.post("/settings", json={"flip": True}, headers=LOCAL)
        self.assertEqual(response.status, 200)
        self.assertTrue(self.camera.flip)
        self.assertEqual(json.loads((server.STATE / "settings.json").read_text()), {"flip": True})
