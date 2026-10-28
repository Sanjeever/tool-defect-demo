from collections import deque
from io import BytesIO
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
        self.frames = threading.Condition()
        self.stop = threading.Event()
        self.worker = None
        self.latest = None
        self.jpeg = None
        self.sequence = 0
        self.error = ""
        self.times = deque(maxlen=30)

    def status(self):
        with self.lock:
            with self.frames:
                recent = self.times and time.monotonic() - self.times[-1] < 1
                fps = (len(self.times) - 1) / (self.times[-1] - self.times[0]) if recent and len(self.times) > 1 else 0
                return {"connected": self.camera is not None, "sn": self.sn, "fps": round(fps, 1),
                        "size": list(self.latest.size) if self.latest else None, "error": self.error}

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
                pixel.set("Mono8")
                delay.set(packet_delay)
                camera.stream_on()
                self.streaming = True
                self.sn = sn
                self.stop.clear()
                self.worker = threading.Thread(target=self.receive, name="camera-receive", daemon=True)
                self.worker.start()
            except Exception:
                self.disconnect()
                raise
            return self.status()

    def receive(self):
        stream = self.camera.data_stream[0]
        last_received = time.monotonic()
        try:
            while not self.stop.is_set():
                frame = stream.dq_buf(timeout=500)
                if frame is None:
                    if time.monotonic() - last_received >= 3:
                        raise RuntimeError("采图超时，请检查相机连接和曝光设置")
                    continue
                try:
                    if frame.get_status() != self.gx.GxFrameStatusList.SUCCESS:
                        raise RuntimeError("相机返回不完整图像，请检查网络传输")
                    pixels = frame.get_numpy_array()
                    if pixels is None:
                        raise RuntimeError("无法读取相机图像数据")
                    image = Image.fromarray(pixels.copy())
                finally:
                    stream.q_buf(frame)
                preview = image.copy()
                preview.thumbnail((960, 720))
                output = BytesIO()
                preview.save(output, format="JPEG", quality=75)
                last_received = time.monotonic()
                with self.frames:
                    self.latest, self.jpeg = image, output.getvalue()
                    self.sequence += 1
                    self.times.append(last_received)
                    self.frames.notify_all()
        except Exception as error:
            if not self.stop.is_set():
                with self.frames:
                    self.error = str(error)
                    self.frames.notify_all()

    def wait_frame(self, after=None):
        if self.camera is None:
            raise ValueError("请先连接相机")
        ready = self.frames.wait_for(lambda: self.error or self.stop.is_set() or (
            self.latest is not None and time.monotonic() - self.times[-1] < 1 and
            (after is None or self.sequence > after)), timeout=3)
        if self.error:
            raise RuntimeError(self.error)
        if self.stop.is_set():
            raise ValueError("相机已断开")
        if not ready:
            raise RuntimeError("等待相机新图像超时")

    def capture(self):
        with self.frames:
            self.wait_frame()
            return self.latest.copy()

    def next_preview(self, after):
        with self.frames:
            self.wait_frame(after)
            return self.sequence, self.jpeg

    def disconnect(self):
        with self.lock:
            if self.camera is None:
                return self.status()
            self.stop.set()
            with self.frames:
                self.frames.notify_all()
            if self.worker:
                self.worker.join(timeout=4)
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
                    self.worker = None
                    with self.frames:
                        self.latest, self.jpeg = None, None
                        self.sequence = 0
                        self.error = ""
                        self.times.clear()
                        self.frames.notify_all()
            return self.status()
