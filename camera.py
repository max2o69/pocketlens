"""Local, current-user DirectShow camera. Derived native library: tshino/softcam (MIT)."""

import ctypes
from pathlib import Path
import threading
import time
import winreg
import cv2
import numpy as np

NAME = "PocketLens"
CLSID = "{E54B414E-D1EC-4D35-B8C4-AD9D9E0F2163}"
CATEGORY = "{860BB310-5D01-11D0-BD3B-00A0C911CE86}"
BASE = Path(__file__).resolve().parent
WIDTH, HEIGHT, FPS = 1280, 720, 30


def register():
    # Validate both binaries before writing any registry entries.
    for arch in ("x64", "x86"):
        dll = BASE / "native/bin" / arch / "pocketlens.dll"
        if not dll.is_file():
            raise FileNotFoundError(
                "Camera binaries missing. Run Build PocketLens Native.ps1 or use the Windows release ZIP."
            )
    # Prefer the complete machine-wide registration installed for packaged apps.
    system_registered = True
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                f"Software\\Classes\\CLSID\\{CLSID}\\InprocServer32",
                0,
                winreg.KEY_READ | view,
            ) as key:
                path = winreg.QueryValueEx(key, "")[0]
                # A pre-PocketLens DLL uses different shared-memory names.
                if Path(path).name.lower() != "pocketlens.dll" or not Path(path).is_file():
                    system_registered = False
        except FileNotFoundError:
            system_registered = False
    if system_registered:
        # Remove our old per-user shadow entries to avoid duplicate devices.
        unregister()
        return
    for arch, view in [("x64", winreg.KEY_WOW64_64KEY), ("x86", winreg.KEY_WOW64_32KEY)]:
        dll = BASE / "native/bin" / arch / "pocketlens.dll"
        if not dll.exists():
            raise FileNotFoundError(dll)
        entries = {
            f"Software\\Classes\\CLSID\\{CLSID}": {"": NAME},
            f"Software\\Classes\\CLSID\\{CLSID}\\InprocServer32": {
                "": str(dll),
                "ThreadingModel": "Both",
            },
            f"Software\\Classes\\CLSID\\{CATEGORY}\\Instance\\{CLSID}": {
                "CLSID": CLSID,
                "FriendlyName": NAME,
            },
        }
        for path, values in entries.items():
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE | view
            ) as key:
                for name, value in values.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def unregister():
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        for path in [
            f"Software\\Classes\\CLSID\\{CLSID}\\InprocServer32",
            f"Software\\Classes\\CLSID\\{CLSID}",
            f"Software\\Classes\\CLSID\\{CATEGORY}\\Instance\\{CLSID}",
        ]:
            try:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, path, view, 0)
            except FileNotFoundError:
                pass


def slate(text):
    frame = np.full((HEIGHT, WIDTH, 3), (28, 24, 20), np.uint8)
    cv2.putText(
        frame,
        "POCKETLENS",
        (70, 310),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        (238, 234, 224),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame, text, (70, 370), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (165, 176, 180), 1, cv2.LINE_AA
    )
    return frame


class Camera:
    def __init__(self):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise RuntimeError("PocketLens requires 64-bit Python.")
        self.dll = ctypes.CDLL(str(BASE / "native/bin/x64/pocketlens.dll"))
        self.dll.scCreateCamera.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_float]
        self.dll.scCreateCamera.restype = ctypes.c_void_p
        self.dll.scSendFrame.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.dll.scSendFrame.restype = None
        self.dll.scDeleteCamera.argtypes = [ctypes.c_void_p]
        self.dll.scDeleteCamera.restype = None
        self.dll.scIsConnected.argtypes = [ctypes.c_void_p]
        self.dll.scIsConnected.restype = ctypes.c_bool
        self.handle = self.dll.scCreateCamera(WIDTH, HEIGHT, FPS)
        if not self.handle:
            raise RuntimeError("PocketLens is already running. Open http://127.0.0.1:8766")
        self.lock = threading.Lock()
        self.frame = slate("Waiting for your iPhone")
        self.waiting = self.frame
        self.last_received = 0.0
        self.frames = 0
        self.flip = False
        self.transport = "Waiting"
        self.started = time.monotonic()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def accept(self, data):
        # Pillow checks dimensions before OpenCV allocates the decoded image.
        from PIL import Image
        import io

        with Image.open(io.BytesIO(data)) as probe:
            if probe.format != "JPEG" or probe.width > 1920 or probe.height > 1920:
                raise ValueError("Expected a JPEG no larger than 1920 x 1920")
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Invalid JPEG")
        self.accept_bgr(frame)

    def accept_bgr(self, frame):
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError("Expected uint8 BGR frame")
        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            raise ValueError("Camera frame must not be empty")
        if (w, h) != (WIDTH, HEIGHT):
            scale = min(WIDTH / w, HEIGHT / h)
            nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
            resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            frame = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
            x, y = (WIDTH - nw) // 2, (HEIGHT - nh) // 2
            frame[y : y + nh, x : x + nw] = resized
        with self.lock:
            self.frame = np.ascontiguousarray(frame)
            self.last_received = time.monotonic()
            self.frames += 1

    def clear(self):
        with self.lock:
            self.frame = self.waiting
            self.last_received = 0

    def current(self):
        return self.snapshot()[0]

    def snapshot(self):
        """Return the output image and cache key from the same locked state."""
        with self.lock:
            live = time.monotonic() - self.last_received < 1
            state = (self.frames, self.flip, live)
            frame = self.frame if live else self.waiting
            flip = self.flip and live
        return (cv2.flip(frame, 1) if flip else frame), state

    def _run(self):
        while not self.stop_event.is_set():
            frame = self.current()
            self.dll.scSendFrame(self.handle, frame.ctypes.data)

    def status(self):
        return {
            "live": time.monotonic() - self.last_received < 1,
            "flip": self.flip,
            "transport": self.transport,
            "cameraInUse": bool(self.dll.scIsConnected(self.handle)),
            "frames": self.frames,
            "uptime": round(time.monotonic() - self.started),
        }

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError("Camera thread did not stop")
        self.dll.scDeleteCamera(self.handle)
