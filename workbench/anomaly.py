import argparse
import json
from pathlib import Path

from PIL import Image

from .preprocessing import check_prepared_images


def make_datamodule(root, split, batch_size):
    from anomalib.data import Folder

    for directory in (root / "train/good", root / split / "good", root / split / "defect"):
        check_prepared_images(directory)
    return Folder(
        name="tool",
        root=root.resolve(),
        normal_dir="train/good",
        normal_test_dir=f"{split}/good",
        abnormal_dir=f"{split}/defect",
        train_batch_size=batch_size,
        eval_batch_size=batch_size,
        num_workers=0,
        val_split_mode="same_as_test" if split == "val" else "none",
        seed=42,
    )


def make_engine(device, output, **options):
    import torch
    from anomalib.engine import Engine

    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA 不可用；如需使用 CPU，请显式指定 --device cpu")
    return Engine(
        accelerator="gpu" if device == "cuda" else "cpu",
        devices=1,
        default_root_dir=output,
        logger=False,
        **options,
    )


def train(args):
    from lightning import seed_everything
    from anomalib.models import Patchcore

    checkpoint = args.output / "model.ckpt"
    if checkpoint.exists():
        raise FileExistsError(f"模型已存在，请指定新的 --output：{checkpoint}")
    seed_everything(42, workers=True)
    model = Patchcore(backbone="resnet18", coreset_sampling_ratio=0.01, visualizer=False,
                      post_processor=not args.experimental, evaluator=False)
    engine = make_engine(args.device, args.output)
    if args.experimental:
        from anomalib.data import FolderDataset
        from torch.utils.data import DataLoader

        check_prepared_images(args.data / "train/good")
        dataset = FolderDataset(name="tool", root=args.data.resolve(), normal_dir="train/good", split="train")
        loader = DataLoader(dataset, batch_size=args.batch_size, num_workers=0, collate_fn=dataset.collate_fn)
        engine = make_engine(args.device, args.output, limit_val_batches=0, num_sanity_val_steps=0)
        engine.fit(model=model, train_dataloaders=loader)
    else:
        engine.fit(model=model, datamodule=make_datamodule(args.data, "val", args.batch_size))
    args.output.mkdir(parents=True, exist_ok=True)
    engine.trainer.save_checkpoint(checkpoint)
    (args.output / "model.json").write_text(json.dumps({
        "experimental": args.experimental, "preprocessing": "gray-pad-256-v1",
    }), encoding="utf-8")
    print(f"已保存{'未校准实验模型' if args.experimental else '模型与验证集校准参数'}：{checkpoint.resolve()}")


def load_model(checkpoint):
    from anomalib.models import Patchcore

    if not checkpoint.is_file():
        raise FileNotFoundError(f"模型不存在，请先训练：{checkpoint}")
    metadata = checkpoint.with_name("model.json")
    experimental = json.loads(metadata.read_text(encoding="utf-8"))["experimental"] if metadata.exists() else False
    return Patchcore.load_from_checkpoint(checkpoint, map_location="cpu", pre_trained=False,
                                         visualizer=False, post_processor=not experimental, evaluator=False)


def test(args):
    from anomalib.metrics import AUROC, Evaluator, F1Score

    metadata = args.checkpoint.with_name("model.json")
    if metadata.exists() and json.loads(metadata.read_text(encoding="utf-8"))["experimental"]:
        raise ValueError("未校准实验模型不能用于正式指标测试，请补充独立验证实物后重新训练")
    datamodule = make_datamodule(args.data, "test", args.batch_size)
    model = load_model(args.checkpoint)
    model.evaluator = Evaluator(test_metrics=[
        AUROC(fields=["pred_score", "gt_label"], prefix="image_"),
        F1Score(fields=["pred_label", "gt_label"], prefix="image_"),
    ])
    engine = make_engine(args.device, args.output)
    results = engine.test(model=model, datamodule=datamodule)
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "metrics.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"测试指标：{path.resolve()}")


def predict(args):
    import cv2
    import numpy as np
    from anomalib.data import PredictDataset

    if args.source.is_dir():
        check_prepared_images(args.source)
        source_root = args.source.resolve()
    else:
        with Image.open(args.source) as image:
            if image.size != (256, 256):
                raise ValueError("请先运行 uv run python -m workbench.preprocessing 生成 256×256 图片")
        source_root = args.source.resolve().parent
    result_path = args.output / "results.jsonl"
    if result_path.exists():
        raise FileExistsError(f"结果已存在，请指定新的 --output：{result_path}")
    model = load_model(args.checkpoint)
    engine = make_engine(args.device, args.output)
    predictions = engine.predict(model=model, dataset=PredictDataset(path=args.source.resolve()))
    args.output.mkdir(parents=True, exist_ok=True)
    with result_path.open("w", encoding="utf-8") as output:
        for batch in predictions:
            for index, image_path in enumerate(batch.image_path):
                path = Path(image_path)
                anomalous = bool(batch.pred_label[index].item()) if batch.pred_label is not None else None
                result = {
                    "image": str(path),
                    "label": "未校准" if anomalous is None else "异常" if anomalous else "正常",
                    "anomaly_score": float(batch.pred_score[index].item()),
                }
                anomaly_map = batch.anomaly_map[index].detach().cpu().numpy().squeeze()
                np.save(args.output / f"{path.stem}.map.npy", anomaly_map)
                display_map = anomaly_map
                if anomalous is None:
                    display_map = (anomaly_map - anomaly_map.min()) / max(float(np.ptp(anomaly_map)), 1e-8)
                heatmap = cv2.applyColorMap((np.clip(display_map, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_JET)
                heatmap = Image.fromarray(cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB))
                with Image.open(path) as image:
                    overlay = Image.blend(image.convert("RGB"), heatmap.resize(image.size), alpha=0.45)
                overlay_path = args.output / path.resolve().relative_to(source_root).with_suffix(".heatmap.png")
                overlay_path.parent.mkdir(parents=True, exist_ok=True)
                overlay.save(overlay_path)
                result["heatmap"] = str(overlay_path.resolve())
                line = json.dumps(result, ensure_ascii=False)
                output.write(line + "\n")
                print(line)
    print(f"检测结果：{result_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(description="PatchCore 刀具异常检测，输入为已预处理的 256×256 图片")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description, function in (
        ("train", "使用正常图训练，并用验证集校准异常阈值", train),
        ("test", "在独立测试集上评价模型", test),
        ("predict", "检测图片，保存异常分数和热力图", predict),
    ):
        command = commands.add_parser(name, help=description, description=description)
        command.set_defaults(function=function)
        command.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
        command.add_argument("--output", type=Path, default=Path("outputs") / {"train": "patchcore", "test": "test", "predict": "predictions"}[name])
        if name in ("train", "test"):
            command.add_argument("--data", type=Path, default=Path("data/anomaly"))
            command.add_argument("--batch-size", type=int, default=4)
        if name == "train":
            command.add_argument("--experimental", action="store_true", help="仅用正常训练图建库，输出原始分数，不校准阈值")
        if name != "train":
            command.add_argument("--checkpoint", type=Path, required=True, help="本项目训练的 model.ckpt")
        if name == "predict":
            command.add_argument("--source", type=Path, required=True, help="单张图片或图片目录")
    args = parser.parse_args()
    if hasattr(args, "batch_size") and args.batch_size <= 0:
        parser.error("--batch-size 必须大于 0")
    if hasattr(args, "min_confidence") and not 0 <= args.min_confidence <= 1:
        parser.error("--min-confidence 必须在 0 到 1 之间")
    args.function(args)


if __name__ == "__main__":
    main()
