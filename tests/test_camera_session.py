from pathlib import Path
from io import BytesIO
from queue import Empty, Queue
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from workbench.camera_session import CameraSession


class CameraSessionTests(unittest.TestCase):
    def sdk(self):
        gx = MagicMock()
        gx.DeviceManager.return_value.update_all_device_list.return_value = (1, [{"sn": "sample"}])
        device = gx.DeviceManager.return_value.open_device_by_sn.return_value
        features = device.get_remote_device_feature_control.return_value
        enums = {name: MagicMock() for name in ("TriggerMode", "TriggerSource", "PixelFormat")}
        for name, feature in enums.items():
            feature.get.return_value = (0, f"original-{name}")
        features.get_enum_feature.side_effect = enums.__getitem__
        features.get_int_feature.return_value.get.return_value = 100
        queue = Queue()
        def receive(timeout):
            try:
                return queue.get(timeout=0.02)
            except Empty:
                return None
        device.data_stream[0].dq_buf.side_effect = receive
        return gx, device, enums, queue

    def frame(self, gx, pixels):
        frame = MagicMock()
        frame.get_status.return_value = gx.GxFrameStatusList.SUCCESS
        frame.get_numpy_array.return_value = pixels
        return frame

    def test_open_is_explicit_and_disconnect_restores_and_releases(self):
        gx, device, enums, _ = self.sdk()
        with patch("workbench.camera_session.load_sdk", return_value=gx) as load:
            session = CameraSession()
            self.assertFalse(session.status()["connected"])
            load.assert_not_called()
            session.connect("sample", Path("sdk"), 20000)
            self.assertTrue(session.status()["connected"])
            device.stream_on.assert_called_once()
            self.assertEqual(enums["TriggerMode"].set.call_args.args, ("Off",))
            device.get_remote_device_feature_control.return_value.get_command_feature.assert_not_called()
            session.disconnect()
            device.stream_off.assert_called_once()
            device.close_device.assert_called_once()
            for name, feature in enums.items():
                self.assertEqual(feature.set.call_args.args, (f"original-{name}",))
            self.assertFalse(session.status()["connected"])

    def test_bad_frame_returns_buffer_without_producing_image(self):
        gx, device, _, queue = self.sdk()
        with patch("workbench.camera_session.load_sdk", return_value=gx):
            session = CameraSession()
            session.connect("sample", Path("sdk"), 20000)
            stream = device.data_stream[0]
            frame = MagicMock()
            frame.get_status.return_value = "incomplete"
            queue.put(frame)
            with self.assertRaisesRegex(RuntimeError, "不完整"):
                session.capture()
            stream.q_buf.assert_called_once_with(frame)
            frame.get_numpy_array.assert_not_called()
            session.disconnect()

    def test_capture_copies_pixels_before_buffer_is_returned(self):
        gx, device, _, queue = self.sdk()
        pixels = np.full((4, 4), 128, dtype=np.uint8)
        with patch("workbench.camera_session.load_sdk", return_value=gx):
            session = CameraSession()
            session.connect("sample", Path("sdk"), 20000)
            stream = device.data_stream[0]
            frame = self.frame(gx, pixels)
            stream.q_buf.side_effect = lambda frame: pixels.fill(0)
            queue.put(frame)
            image = session.capture()
            self.assertEqual(image.getpixel((0, 0)), 128)
            self.assertEqual(pixels[0, 0], 0)
            session.disconnect()

    def test_failed_stream_start_releases_device(self):
        gx, device, _, _ = self.sdk()
        device.stream_on.side_effect = RuntimeError("流启动失败")
        with patch("workbench.camera_session.load_sdk", return_value=gx):
            session = CameraSession()
            with self.assertRaisesRegex(RuntimeError, "流启动失败"):
                session.connect("sample", Path("sdk"), 20000)
            device.close_device.assert_called_once()
            self.assertFalse(session.status()["connected"])

    def test_slow_viewer_gets_latest_frame_and_capture_keeps_full_resolution(self):
        gx, device, _, queue = self.sdk()
        with patch("workbench.camera_session.load_sdk", return_value=gx):
            session = CameraSession()
            self.addCleanup(session.disconnect)
            session.connect("sample", Path("sdk"), 20000)
            queue.put(self.frame(gx, np.full((964, 1292), 30, dtype=np.uint8)))
            first, _ = session.next_preview(0)
            queue.put(self.frame(gx, np.full((964, 1292), 90, dtype=np.uint8)))
            queue.put(self.frame(gx, np.full((964, 1292), 180, dtype=np.uint8)))
            deadline = time.monotonic() + 2
            while session.sequence < 3 and time.monotonic() < deadline:
                time.sleep(0.01)
            latest, jpeg = session.next_preview(first)
            self.assertEqual(latest, 3)
            with Image.open(BytesIO(jpeg)) as preview:
                self.assertEqual(preview.width, 960)
                self.assertAlmostEqual(preview.getpixel((0, 0)), 180, delta=2)
            original = session.capture()
            self.assertEqual(original.size, (1292, 964))
            self.assertEqual(original.getpixel((0, 0)), 180)
            session.disconnect()
            self.assertFalse(session.worker)
