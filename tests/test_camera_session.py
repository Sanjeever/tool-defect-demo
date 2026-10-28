from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from camera_session import CameraSession


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
        return gx, device, enums

    def test_open_is_explicit_and_disconnect_restores_and_releases(self):
        gx, device, enums = self.sdk()
        with patch("camera_session.load_sdk", return_value=gx) as load:
            session = CameraSession()
            self.assertFalse(session.status()["connected"])
            load.assert_not_called()
            session.connect("sample", Path("sdk"), 20000)
            self.assertTrue(session.status()["connected"])
            device.stream_on.assert_called_once()
            session.disconnect()
            device.stream_off.assert_called_once()
            device.close_device.assert_called_once()
            for name, feature in enums.items():
                self.assertEqual(feature.set.call_args.args, (f"original-{name}",))
            self.assertFalse(session.status()["connected"])

    def test_bad_frame_returns_buffer_without_producing_image(self):
        gx, device, _ = self.sdk()
        with patch("camera_session.load_sdk", return_value=gx):
            session = CameraSession()
            session.connect("sample", Path("sdk"), 20000)
            stream = device.data_stream[0]
            frame = stream.dq_buf.return_value
            frame.get_status.return_value = "incomplete"
            with self.assertRaisesRegex(RuntimeError, "不完整"):
                session.capture()
            stream.q_buf.assert_called_once_with(frame)
            frame.get_numpy_array.assert_not_called()
            session.disconnect()

    def test_capture_copies_pixels_before_buffer_is_returned(self):
        gx, device, _ = self.sdk()
        pixels = np.full((4, 4), 128, dtype=np.uint8)
        with patch("camera_session.load_sdk", return_value=gx):
            session = CameraSession()
            session.connect("sample", Path("sdk"), 20000)
            stream = device.data_stream[0]
            frame = stream.dq_buf.return_value
            frame.get_status.return_value = gx.GxFrameStatusList.SUCCESS
            frame.get_numpy_array.return_value = pixels
            stream.q_buf.side_effect = lambda frame: pixels.fill(0)
            image = session.capture()
            self.assertEqual(image.getpixel((0, 0)), 128)
            self.assertEqual(pixels[0, 0], 0)
            session.disconnect()

    def test_failed_stream_start_releases_device(self):
        gx, device, _ = self.sdk()
        device.stream_on.side_effect = RuntimeError("流启动失败")
        with patch("camera_session.load_sdk", return_value=gx):
            session = CameraSession()
            with self.assertRaisesRegex(RuntimeError, "流启动失败"):
                session.connect("sample", Path("sdk"), 20000)
            device.close_device.assert_called_once()
            self.assertFalse(session.status()["connected"])
