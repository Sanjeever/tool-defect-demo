import argparse
from functools import partial
import json
from pathlib import Path
import shutil


def make_model(labels):
    from torch.optim import SGD
    from getitune.backend.lightning.models.detection.yolox import YOLOX
    from getitune.backend.lightning.models.base import DataInputParams, DefaultSchedulerCallable

    return YOLOX(label_info=labels, model_name="yolox_tiny", data_input_params=DataInputParams(
        input_size=(512, 512), mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)),
        optimizer=partial(SGD, lr=0.0002, momentum=0.9, weight_decay=0.0001),
        scheduler=partial(DefaultSchedulerCallable, factor=1.0, total_iters=0))


def make_data(args):
    from getitune.config.data import SubsetConfig
    from getitune.data.module import DataModule
    from getitune.types.task import TaskType

    def subset(name):
        return SubsetConfig(subset_name=name, batch_size=args.batch_size, num_workers=0, input_size=(512, 512),
            augmentations_cpu=[{"class_path": "torchvision.transforms.v2.Normalize", "init_args": {
                "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]}}])

    return DataModule(task=TaskType.DETECTION, data_root=str(args.data), input_size=(512, 512),
                      train_subset=subset("train"), val_subset=subset("val"), test_subset=subset("test"))


def train(args):
    from getitune.engine import create_engine
    from lightning.pytorch.callbacks import ModelCheckpoint
    from lightning.pytorch.loggers import CSVLogger

    data = make_data(args)
    model = make_model(data.label_info)
    engine = create_engine(model=model, data=data, work_dir=args.output, device="gpu" if args.device == "cuda" else "cpu")
    callback = ModelCheckpoint(dirpath=args.output, filename="weights", monitor=None, save_top_k=1,
                               save_on_train_epoch_end=True)
    metrics = engine.train(max_epochs=args.epochs, seed=42, precision="32-true", logger=CSVLogger(args.output / "logs"), callbacks=[callback],
                 limit_val_batches=0 if args.experimental else 1.0, num_sanity_val_steps=0)
    shutil.copy2(engine.checkpoint, args.output / "model.ckpt")
    (args.output / "model.json").write_text(json.dumps({
        "labels": data.label_info.label_names, "experimental": args.experimental,
        "engine": "getitune", "version": "0.1.3", "architecture": "yolox_tiny", "input_size": 512,
        "optimizer": {"name": "SGD", "lr": 0.0002, "momentum": 0.9, "weight_decay": 0.0001},
        "scheduler": "constant",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "metrics.json").write_text(json.dumps({"scope": "训练过程" if args.experimental else "训练与验证",
        "values": metrics}, ensure_ascii=False, default=lambda value: value.tolist()), encoding="utf-8")
    print("Geti 缺陷区域模型已保存；实验训练不产生独立验证指标" if args.experimental else "Geti 缺陷区域模型已保存")


def predict(args):
    import torch
    from PIL import Image
    from torchvision.transforms import functional as F
    from getitune.data.entity.base import ImageInfo
    from getitune.data.entity.sample import SampleBatch

    metadata = json.loads(args.checkpoint.with_name("model.json").read_text(encoding="utf-8"))
    model = make_model(metadata["labels"])
    model.load_state_dict(torch.load(args.checkpoint, map_location="cpu", weights_only=False))
    model.to(args.device).eval()
    with Image.open(args.source) as image:
        if image.size != (512, 512):
            raise ValueError("Geti 输入应为完成定位对齐的 512×512 图片")
        tensor = F.normalize(F.to_tensor(image.convert("RGB")), [0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    batch = SampleBatch(images=tensor.unsqueeze(0).to(args.device), imgs_info=[ImageInfo(img_idx=0, img_shape=(512, 512), ori_shape=(512, 512))])
    with torch.inference_mode():
        prediction = model(batch)
    boxes = []
    for coordinates, label, score in zip(prediction.bboxes[0].tolist(), prediction.labels[0].tolist(), prediction.scores[0].tolist()):
        if score < args.min_confidence:
            continue
        left, top, right, bottom = [max(0, min(512, float(value))) for value in coordinates]
        if right > left and bottom > top:
            boxes.append({"x": left, "y": top, "width": right - left, "height": bottom - top,
                          "label": metadata["labels"][label], "confidence": score})
    args.output.write_text(json.dumps({"boxes": boxes, "experimental": metadata["experimental"]}, ensure_ascii=False), encoding="utf-8")


def test(args):
    from getitune.engine import create_engine

    metadata = json.loads(args.checkpoint.with_name("model.json").read_text(encoding="utf-8"))
    if metadata["experimental"]:
        raise ValueError("实验模型不能报告正式测试指标，请补充独立验证实物后训练")
    data = make_data(args)
    if "test" not in data.subsets:
        raise ValueError("数据中没有独立测试组")
    model = make_model(metadata["labels"])
    engine = create_engine(model=model, data=data, checkpoint=args.checkpoint, work_dir=args.output,
                           device="gpu" if args.device == "cuda" else "cpu")
    metrics = engine.test()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "metrics.json").write_text(json.dumps(metrics, default=lambda value: value.tolist()), encoding="utf-8")
    print(f"独立测试指标：{args.output / 'metrics.json'}")


def main():
    parser = argparse.ArgumentParser(description="独立 Geti 环境：训练与预测多类别刀具缺陷区域")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="验证 Geti、PyTorch 和 CUDA，不训练、不打开相机")
    for name in ("train", "predict", "test"):
        command = commands.add_parser(name)
        command.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
        command.add_argument("--output", type=Path, required=True)
        if name in {"train", "test"}:
            command.add_argument("--data", type=Path, required=True)
            command.add_argument("--batch-size", type=int, default=2)
        if name == "train":
            command.add_argument("--epochs", type=int, default=30)
            command.add_argument("--experimental", action="store_true")
        else:
            command.add_argument("--checkpoint", type=Path, required=True)
        if name == "predict":
            command.add_argument("--source", type=Path, required=True)
            command.add_argument("--min-confidence", type=float, default=0.5)
    args = parser.parse_args()
    import torch
    import getitune

    if args.command == "check":
        from getitune.backend.lightning.models.detection.yolox import YOLOX
        print(json.dumps({"getitune": getitune.__version__, "torch": torch.__version__, "cuda": torch.cuda.is_available(), "model": YOLOX.__name__}))
        return
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Geti 环境 CUDA 不可用，请修复环境或显式选择 CPU")
    if args.command == "train":
        if args.epochs < 1 or args.batch_size < 1:
            parser.error("训练轮数与批量必须大于 0")
        args.output.mkdir(parents=True, exist_ok=True)
        if (args.output / "model.ckpt").exists():
            raise FileExistsError("输出模型已存在，请指定新的 --output")
        train(args)
    elif args.command == "test":
        test(args)
    else:
        if not 0 <= args.min_confidence <= 1:
            parser.error("置信度门槛应在 0～1 之间")
        predict(args)


if __name__ == "__main__":
    main()
