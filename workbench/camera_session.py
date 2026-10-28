import threading
import time

from PIL import Image

from .camera import load_sdk


class CameraSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.camera = None
        self.sn = None
        self.original = []

    def status(self):
        with self.lock:
            return {"connected": self.camera is not None, "sn": self.sn}

    def connect(self, sn, sdk_root, packet_delay):
        with self.lock:
            if self.camera is not None:
                raise ValueError("相机已连接，请先断开再修改连接设置")
            self.gx = load_sdk(sdk_root)
            self.manager = self.gx.DeviceManager()
            _, devices = self.manager.update_all_device_list(timeout=1000)
            if not any(device["sn"] == sn for device in devices):
                raise RuntimeError(f"未找到相机 {sn}")
            camera = self.manager.open_device_by_sn(sn)
            self.camera = camera
            self.streaming = False
            try:
                self.features = camera.get_remote_device_feature_control()
                self.trigger = self.features.get_enum_feature("TriggerMode")
                source = self.features.get_enum_feature("TriggerSource")
                pixel = self.features.get_enum_feature("PixelFormat")
                delay = self.features.get_int_feature("GevSCPD")
                self.original = [(self.trigger, self.trigger.get()[1]), (source, source.get()[1]),
                                 (pixel, pixel.get()[1]), (delay, delay.get())]
                self.trigger.set("Off")
                source.set("Software")
                pixel.set("Mono8")
                delay.set(packet_delay)
                self.trigger.set("On")
                camera.stream_on()
                self.streaming = True
                time.sleep(0.1)
                self.sn = sn
            except Exception:
                self.disconnect()
                raise
            return self.status()

    def capture(self):
        with self.lock:
            if self.camera is None:
                raise ValueError("请先连接相机")
            self.features.get_command_feature("TriggerSoftware").send_command()
            stream = self.camera.data_stream[0]
            frame = stream.dq_buf(timeout=3000)
            if frame is None:
                raise RuntimeError("采图超时，请检查连接、触发和曝光设置")
            try:
                if frame.get_status() != self.gx.GxFrameStatusList.SUCCESS:
                    raise RuntimeError("相机返回不完整图像，请检查网络传输")
                pixels = frame.get_numpy_array()
                if pixels is None:
                    raise RuntimeError("无法读取相机图像数据")
                return Image.fromarray(pixels.copy())
            finally:
                stream.q_buf(frame)

    def disconnect(self):
        with self.lock:
            if self.camera is None:
                return self.status()
            try:
                try:
                    if self.streaming:
                        self.camera.stream_off()
                finally:
                    if self.original:
                        self.trigger.set("Off")
                        for feature, value in self.original[1:]:
                            feature.set(value)
                        self.trigger.set(self.original[0][1])
            finally:
                try:
                    self.camera.close_device()
                finally:
                    self.camera = None
                    self.sn = None
                    self.original = []
            return self.status()
