import asyncio
import unittest

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack

from rtc_receiver import Receiver
from test_camera import memory_camera


class WebSocket:
    closed = False

    def __init__(self):
        self.messages = asyncio.Queue()

    async def send_json(self, message):
        await self.messages.put(message)

    async def close(self):
        self.closed = True


class WebRTCTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_video_offer_receives_frames_and_closes(self):
        camera = memory_camera()
        ws = WebSocket()
        receiver = Receiver(camera, ws)
        sender = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        sender.addTrack(VideoStreamTrack())
        try:
            await sender.setLocalDescription(await sender.createOffer())
            await receiver.offer({"type": "offer", "sdp": sender.localDescription.sdp})
            message = await ws.messages.get()
            while message["type"] != "answer":
                message = await ws.messages.get()
            await sender.setRemoteDescription(
                RTCSessionDescription(sdp=message["sdp"], type="answer")
            )
            async with asyncio.timeout(10):
                while camera.frames < 2:
                    await asyncio.sleep(0.05)
            self.assertEqual(camera.transport, "WebRTC")
            self.assertEqual(camera.current().shape, (720, 1280, 3))
        finally:
            await sender.close()
            await receiver.close()
        self.assertTrue(receiver.closed)
        self.assertFalse(receiver.tasks)
