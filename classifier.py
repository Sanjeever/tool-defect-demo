import argparse
import json
from pathlib import Path

from PIL import Image

from prepare_images import check_prepared_images


def check_classes(root, split, expected=None):
    directory = root / split
    if not directory.is_dir():
        raise FileNotFoundError(f"分类数据目录不存在：{directory}")
    classes = sorted(path.name for path in directory.iterdir() if path.is_dir() and not path.name.startswith("."))
    if len(classes) < 2:
        raise ValueError(f"{directory} 至少需要两个真实缺陷类别目录")
    if expected is not None and classes != expected:
        raise ValueError(f"{split} 类别与训练集不一致：{classes}，训练集类别：{expected}")
    for name in classes:
        check_prepared_images(directory / name)
    return classes


def yolo_device(device):
    import torch

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用；如需使用 CPU，请显式指定 --device cpu")
    return 0 if device == "cuda" else "cpu"


def load_classifier(checkpoint):
    from ultralytics import YOLO

    if not checkpoint.is_file():
        raise FileNotFoundError(f"分类模型不存在，请先训练：{checkpoint}")
    model = YOLO(str(checkpoint))
    if model.task != "classify":
        raise ValueError("需要 YOLO 分类权重，不能使用检测或分割权重")
    return model


def classify_image(model, path, device, min_confidence):
    with Image.open(path) as image:
        if image.size != (256, 256):
            raise ValueError(f"请先使用 prepare_images.py 生成 256×256 图片：{path}")
        result = model.predict(image.convert("RGB"), imgsz=256, device=yolo_device(device), verbose=False)[0]
    confidence = float(result.probs.top1conf.item())
    category = result.names[result.probs.top1]
    return {
        "category": category,
        "confidence": confidence,
        "decision": category if confidence >= min_confidence else "异常待复核",
    }


def main():
    parser = argparse.ArgumentParser(description="YOLO 已知缺陷图像分类，输入为已预处理的 256×256 图片")
    commands = parser.add_subparsers(dest="command", required=True)
    train_parser = commands.add_parser("train", help="按类别文件夹训练分类模型")
    train_parser.add_argument("--data", type=Path, default=Path("data/classification"))
    train_parser.add_argument("--model", default="yolo26n-cls.pt", help="预训练分类权重，首次使用会下载")
    train_parser.add_argument("--epochs", type=int, default=30)
    train_parser.add_argument("--batch-size", type=int, default=4)
    train_parser.add_argument("--output", type=Path, default=Path("outputs/classifier"))
    test_parser = commands.add_parser("test", help="在独立分类测试集上评价模型")
    test_parser.add_argument("--data", type=Path, default=Path("data/classification"))
    test_parser.add_argument("--checkpoint", type=Path, required=True)
    test_parser.add_argument("--output", type=Path, default=Path("outputs/classifier-test"))
    predict_parser = commands.add_parser("predict", help="预测单张已预处理的异常图片")
    predict_parser.add_argument("--checkpoint", type=Path, required=True)
    predict_parser.add_argument("--source", type=Path, required=True)
    predict_parser.add_argument("--min-confidence", type=float, default=0.7)
    for command in (train_parser, test_parser, predict_parser):
        command.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    args = parser.parse_args()
    if args.command == "train" and (args.epochs <= 0 or args.batch_size <= 0):
        parser.error("--epochs 和 --batch-size 必须大于 0")
    if args.command == "predict" and not 0 <= args.min_confidence <= 1:
        parser.error("--min-confidence 必须在 0 到 1 之间")
    if args.command == "predict":
        result = classify_image(load_classifier(args.checkpoint), args.source, args.device, args.min_confidence)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    classes = check_classes(args.data, "train")
    check_classes(args.data, "val" if args.command == "train" else "test", expected=classes)
    if args.output.exists():
        raise FileExistsError(f"输出目录已存在，请指定新的 --output：{args.output}")
    device = yolo_device(args.device)
    if args.command == "train":
        from ultralytics import YOLO

        model = YOLO(args.model)
        if model.task != "classify":
            raise ValueError("--model 需要分类模型，例如 yolo26n-cls.pt")
        model.train(
            data=str(args.data.resolve()), epochs=args.epochs, batch=args.batch_size,
            imgsz=256, device=device, workers=0, seed=42, amp=False,
            project=str(args.output.resolve().parent), name=args.output.name,
            scale=0.0, fliplr=0.0, flipud=0.0, auto_augment=None, erasing=0.0,
            hsv_h=0.0, hsv_s=0.0, hsv_v=0.0,
        )
        print(f"分类权重：{args.output.resolve() / 'weights' / 'best.pt'}")
    else:
        model = load_classifier(args.checkpoint)
        if list(model.names.values()) != classes:
            raise ValueError("测试集类别与分类模型中的类别不一致")
        results = model.val(
            data=str(args.data.resolve()), split="test", imgsz=256, batch=4,
            device=device, workers=0, project=str(args.output.resolve().parent), name=args.output.name,
        )
        (args.output / "metrics.json").write_text(
            json.dumps(results.results_dict, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
