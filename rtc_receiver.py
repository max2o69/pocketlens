"""WebRTC signaling over the existing authenticated WebSocket."""

import asyncio
import contextlib
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError


class Receiver:
    def __init__(self, camera, ws):
        self.camera, self.ws = camera, ws
        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self.tasks = set()
        self.closed = False
        self.last_frame = asyncio.get_running_loop().time()
        self.connected_at = None

        @self.pc.on("track")
        def track_received(track):
            if track.kind == "video":
                task = asyncio.create_task(self.consume(track))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

        @self.pc.on("connectionstatechange")
        async def connection_state():
            state = self.pc.connectionState
            if not ws.closed:
                await ws.send_json({"type": "state", "state": state})
            if state == "connected":
                self.connected_at = asyncio.get_running_loop().time()
            if state == "failed" and not ws.closed:
                await ws.close()

        self.watchdog = asyncio.create_task(self.watch())

    async def watch(self):
        # Renegotiate if a connected stream stops producing frames.
        while not self.closed:
            await asyncio.sleep(1)
            if (
                self.connected_at
                and asyncio.get_running_loop().time() - max(self.last_frame, self.connected_at) > 5
            ):
                await self.ws.close()
                return

    async def consume(self, track):
        latest = None
        ready = asyncio.Event()

        async def convert_latest():
            nonlocal latest
            try:
                while True:
                    await ready.wait()
                    frame = latest
                    ready.clear()
                    if not (0 < frame.width <= 1920 and 0 < frame.height <= 1920):
                        raise ValueError("Video frame exceeds supported dimensions")
                    # A single replaceable pending frame prevents decoder/conversion backlog.
                    pixels = await asyncio.to_thread(frame.to_ndarray, format="bgr24")
                    if self.closed:
                        return
                    self.camera.accept_bgr(pixels)
            except Exception as error:
                print(f"Video conversion failed: {type(error).__name__}", flush=True)
                if not self.ws.closed:
                    await self.ws.close()

        worker = asyncio.create_task(convert_latest())
        try:
            while not self.closed:
                latest = await track.recv()
                self.last_frame = asyncio.get_running_loop().time()
                ready.set()
                # Drain already-decoded frames before yielding to the converter.
        except MediaStreamError:
            pass
        except Exception as error:
            print(f"Video stream failed: {type(error).__name__}", flush=True)
            if not self.ws.closed:
                await self.ws.close()
        finally:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker

    async def offer(self, data):
        if data.get("type") != "offer" or not isinstance(data.get("sdp"), str):
            raise ValueError("Expected WebRTC offer")
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type="offer"))
        await self.pc.setLocalDescription(await self.pc.createAnswer())
        answer = self.pc.localDescription.sdp
        await self.ws.send_json({"type": "answer", "sdp": answer})
        self.camera.transport = "WebRTC"

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.watchdog.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.watchdog
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.pc.close()
