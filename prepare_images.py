import argparse
from pathlib import Path

from PIL import Image, ImageOps


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def image_files(directory):
    if not directory.is_dir():
        raise FileNotFoundError(f"图片目录不存在：{directory}")
    files = sorted(
        path for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not files:
        raise ValueError(f"图片目录为空：{directory}")
    return files


def check_prepared_images(directory):
    files = image_files(directory)
    for path in files:
        with Image.open(path) as image:
            if image.size != (256, 256):
                raise ValueError(f"请先使用 prepare_images.py 生成 256×256 图片：{path}")
    return files


def prepare_image(image, roi, size):
    if size <= 0:
        raise ValueError("输出边长必须大于 0")
    image = ImageOps.exif_transpose(image).convert("RGB")
    if roi is not None:
        left, top, right, bottom = roi
        if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
            raise ValueError(f"ROI {roi} 超出图像边界或尺寸无效，图像尺寸为 {image.size}")
        image = image.crop(roi)
    return ImageOps.pad(
        image, (size, size), method=Image.Resampling.LANCZOS, color=(0, 0, 0)
    )


def prepare_directory(source, output, roi, size):
    source, output = source.resolve(), output.resolve()
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("输入与输出目录不能相同或互相包含")
    sources = image_files(source)
    targets = [output / path.relative_to(source).with_suffix(".png") for path in sources]
    if len(set(targets)) != len(targets):
        raise ValueError("存在同目录同名但扩展名不同的图片，转换 PNG 后会重名，请先重命名")
    for target in targets:
        if target.exists():
            raise FileExistsError(f"输出已存在，请使用新的输出目录：{target}")
    for source_file, target in zip(sources, targets, strict=True):
        with Image.open(source_file) as image:
            prepared = prepare_image(image, roi, size)
        target.parent.mkdir(parents=True, exist_ok=True)
        prepared.save(target)
    return len(targets)


def main():
    parser = argparse.ArgumentParser(description="裁剪 ROI，等比例缩放并补边为方形 PNG，保留目录结构")
    parser.add_argument("--source", type=Path, required=True, help="输入图片目录，可含子目录")
    parser.add_argument("--output", type=Path, required=True, help="输出图片目录")
    parser.add_argument("--roi", nargs=4, type=int, metavar=("左", "上", "右", "下"), help="原图像素坐标，右下边界不包含在内")
    parser.add_argument("--size", type=int, default=256, help="输出边长，默认 256")
    args = parser.parse_args()
    count = prepare_directory(args.source, args.output, args.roi, args.size)
    print(f"已处理 {count} 张图片，输出目录：{args.output.resolve()}")


if __name__ == "__main__":
    main()
