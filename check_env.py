import argparse
import importlib.metadata
import json
import platform


def main():
    parser = argparse.ArgumentParser(description="检查依赖导入与 PyTorch 运算，不训练模型、不打开相机")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda", help="默认验证 CUDA，可显式选择 CPU")
    parser.add_argument("--check-sdk", action="store_true", help="额外验证本机 GalaxySDK 导入，不枚举或打开相机")
    args = parser.parse_args()

    import cv2
    import torch
    import torchvision
    from anomalib.engine import Engine
    from anomalib.models import Patchcore
    from ultralytics import YOLO

    versions = {
        name: importlib.metadata.version(name)
        for name in ("anomalib", "ultralytics-opencv-headless", "numpy", "pillow")
    }
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用，请检查驱动与 PyTorch 安装；需要 CPU 时显式指定 --device cpu")
    matrix = torch.ones((32, 32), device=args.device)
    result = (matrix @ matrix).sum().item()
    report = {
        "Python": platform.python_version(),
        "依赖版本": versions,
        "PyTorch": torch.__version__,
        "torchvision": torchvision.__version__,
        "OpenCV": cv2.__version__,
        "CUDA 构建版本": torch.version.cuda,
        "运行设备": args.device,
        "矩阵运算结果": result,
        "模型入口": [Engine.__name__, Patchcore.__name__, YOLO.__name__],
    }
    if args.device == "cuda":
        report["显卡"] = torch.cuda.get_device_name(0)
    if args.check_sdk:
        from camera import DEFAULT_SDK_ROOT, load_sdk

        gx = load_sdk(DEFAULT_SDK_ROOT)
        report["GalaxySDK Python 接口"] = gx.__version__
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
