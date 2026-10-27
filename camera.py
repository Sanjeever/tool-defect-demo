import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import time

from PIL import Image


DEFAULT_SDK_ROOT = Path(r"C:\Program Files\Daheng Imaging\GalaxySDK")
DLL_HANDLES = []


def load_sdk(sdk_root):
    if sys.platform != "win32":
        raise RuntimeError("当前相机入口面向 Windows GalaxySDK")
    python_dir = sdk_root / "Development" / "Samples" / "Python"
    if not (python_dir / "gxipy" / "__init__.py").is_file():
        raise FileNotFoundError(f"未找到厂商 gxipy，请检查 --sdk-root：{python_dir}")
    os.environ["GALAXY_GENICAM_ROOT"] = str(sdk_root / "GenICam")
    for directory in (sdk_root / "APIDll" / "Win64", sdk_root / "GenICam" / "bin" / "Win64_x64"):
        DLL_HANDLES.append(os.add_dll_directory(str(directory)))
    sys.path.insert(0, str(python_dir))
    return importlib.import_module("gxipy")


def capture(gx, manager, sn, output, timeout, packet_delay_ticks):
    if output.suffix.lower() != ".png":
        raise ValueError("相机图片请使用 .png 扩展名")
    if output.exists():
        raise FileExistsError(f"图片已存在，请指定新的保存路径：{output}")
    camera = manager.open_device_by_sn(sn)
    try:
        features = camera.get_remote_device_feature_control()
        trigger = features.get_enum_feature("TriggerMode")
        trigger_source = features.get_enum_feature("TriggerSource")
        pixel_format = features.get_enum_feature("PixelFormat")
        packet_delay = features.get_int_feature("GevSCPD")
        original_trigger = trigger.get()[1]
        original_source = trigger_source.get()[1]
        original_format = pixel_format.get()[1]
        original_delay = packet_delay.get()
        try:
            trigger.set("Off")
            trigger_source.set("Software")
            pixel_format.set("Mono8")
            packet_delay.set(packet_delay_ticks)
            trigger.set("On")
            camera.stream_on()
            try:
                # 按厂商软件触发示例，启动接收流后预留 100 毫秒准备时间。
                time.sleep(0.1)
                features.get_command_feature("TriggerSoftware").send_command()
                stream = camera.data_stream[0]
                frame = stream.dq_buf(timeout=timeout)
                if frame is None:
                    raise TimeoutError("采图超时，请检查相机连接、触发和曝光设置")
                try:
                    if frame.get_status() != gx.GxFrameStatusList.SUCCESS:
                        raise RuntimeError("相机返回不完整图像，请检查网络传输")
                    pixels = frame.get_numpy_array()
                    if pixels is None:
                        raise RuntimeError("无法读取相机图像数据")
                    image = Image.fromarray(pixels.copy())
                finally:
                    stream.q_buf(frame)
                output.parent.mkdir(parents=True, exist_ok=True)
                image.save(output)
                print(f"已保存 {image.width}×{image.height} 灰度图片：{output.resolve()}")
            finally:
                camera.stream_off()
        finally:
            trigger.set("Off")
            trigger_source.set(original_source)
            packet_delay.set(original_delay)
            pixel_format.set(original_format)
            trigger.set(original_trigger)
    finally:
        camera.close_device()


def main():
    parser = argparse.ArgumentParser(description="通过大恒 GalaxySDK 枚举相机或采集单张黑白图片")
    parser.add_argument("--sdk-root", type=Path, default=DEFAULT_SDK_ROOT, help="GalaxySDK 安装目录")
    parser.add_argument("--list", action="store_true", help="枚举相机，不打开设备")
    parser.add_argument("--sn", help="需要采集的相机序列号")
    parser.add_argument("--output", type=Path, help="保存 PNG 的路径")
    parser.add_argument("--timeout", type=int, default=3000, help="采图超时毫秒数，默认 3000")
    parser.add_argument("--packet-delay", type=int, default=10000, help="GigE 数据包间隔，单位为相机时钟周期，默认 10000")
    args = parser.parse_args()
    if not args.list and (not args.sn or args.output is None):
        parser.error("采集需要同时指定 --sn 和 --output；枚举设备请使用 --list")
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if args.packet_delay < 0:
        parser.error("--packet-delay 不能小于 0")
    gx = load_sdk(args.sdk_root)
    manager = gx.DeviceManager()
    count, devices = manager.update_all_device_list(timeout=1000)
    if args.list:
        print(json.dumps({"设备数量": count, "设备": devices}, ensure_ascii=False, indent=2))
        return
    if not any(device["sn"] == args.sn for device in devices):
        raise RuntimeError(f"未枚举到相机 {args.sn}，请检查连接并运行 --list")
    capture(gx, manager, args.sn, args.output, args.timeout, args.packet_delay)


if __name__ == "__main__":
    main()
