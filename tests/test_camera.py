import io
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from camera import Camera, HEIGHT, WIDTH, slate


def memory_camera():
    """Use the image pipeline without loading a DLL or modifying the registry."""
    camera = Camera.__new__(Camera)
    camera.lock = threading.Lock()
    camera.waiting = slate("Waiting")
    camera.frame = camera.waiting
    camera.last_received = 0
    camera.frames = 0
    camera.flip = False
    camera.transport = "Waiting"
    camera.started = time.monotonic()
    return camera


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.camera = memory_camera()

    def test_portrait_is_letterboxed_and_not_stretched(self):
        frame = np.full((720, 360, 3), (20, 40, 60), dtype=np.uint8)
        self.camera.accept_bgr(frame)
        output = self.camera.current()
        self.assertEqual(output.shape, (HEIGHT, WIDTH, 3))
        np.testing.assert_array_equal(output[:, :460], 0)
        np.testing.assert_array_equal(output[200, 640], (20, 40, 60))

    def test_flip_changes_actual_output_without_mutating_source(self):
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        frame[:, : WIDTH // 2] = (0, 0, 255)
        self.camera.accept_bgr(frame)
        self.camera.flip = True
        np.testing.assert_array_equal(self.camera.current()[10, -10], (0, 0, 255))
        np.testing.assert_array_equal(frame[10, -10], 0)

    def test_stale_or_cleared_frame_returns_waiting_slate(self):
        self.camera.accept_bgr(np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8))
        self.camera.last_received -= 2
        self.assertIs(self.camera.current(), self.camera.waiting)
        self.camera.clear()
        self.assertIs(self.camera.current(), self.camera.waiting)

    def test_snapshot_image_and_liveness_use_the_same_clock_sample(self):
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        self.camera.accept_bgr(frame)
        self.camera.last_received = 100
        with patch("camera.time.monotonic", side_effect=[100.999, 101.001]) as clock:
            image, state = self.camera.snapshot()
            self.assertIs(image, frame)
            self.assertEqual(state, (1, False, True))
            self.assertEqual(clock.call_count, 1)
            image, state = self.camera.snapshot()
            self.assertIs(image, self.camera.waiting)
            self.assertEqual(state, (1, False, False))

    def test_rejects_non_jpeg_oversized_and_empty_frames(self):
        for size, image_format in (((100, 100), "PNG"), ((1921, 10), "JPEG")):
            data = io.BytesIO()
            Image.new("RGB", size).save(data, image_format)
            with self.assertRaises(ValueError):
                self.camera.accept(data.getvalue())
        with self.assertRaises(ValueError):
            self.camera.accept_bgr(np.zeros((0, 10, 3), dtype=np.uint8))
