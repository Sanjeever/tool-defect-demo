import cv2
import numpy as np
from PIL import Image, ImageOps


VERSION = "single-tool-align-v1"


def locate(image, size=512):
    source = np.asarray(ImageOps.grayscale(ImageOps.exif_transpose(image)))
    height, width = source.shape
    border = np.concatenate((source[0], source[-1], source[:, 0], source[:, -1]))
    background = float(np.median(border))
    difference = np.abs(source.astype(np.float32) - background).astype(np.uint8)
    _, mask = cv2.threshold(cv2.GaussianBlur(difference, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)
    if not contours or cv2.contourArea(contours[0]) < width * height * 0.003:
        raise ValueError("未找到完整刀具，请检查背景、光线和摆放")
    if len(contours) > 1 and cv2.contourArea(contours[1]) > cv2.contourArea(contours[0]) * 0.2:
        raise ValueError("画面存在多个明显物体，请保留一把刀具并移开手和杂物")
    contour = contours[0]
    x, y, w, h = cv2.boundingRect(contour)
    if x <= 1 or y <= 1 or x + w >= width - 1 or y + h >= height - 1:
        raise ValueError("刀具接近画面边界，请完整放入画面")
    (cx, cy), radius = cv2.minEnclosingCircle(contour)
    extent = radius * 2.3
    scale = size / extent
    matrix = np.array([[scale, 0, size / 2 - cx * scale], [0, scale, size / 2 - cy * scale]], dtype=np.float64)
    normalized = cv2.warpAffine(source, matrix, (size, size), borderValue=round(background))
    return Image.fromarray(normalized).convert("RGB"), matrix, [x, y, w, h], round(background)


def signature(image):
    gray = np.asarray(image.convert("L").resize((64, 64)))
    gray = cv2.GaussianBlur(gray, (5, 5), 0).astype(np.float32)
    gray -= gray.mean()
    length = float(np.linalg.norm(gray))
    if length < 1:
        raise ValueError("刀具区域缺少可辨认的灰度结构")
    return gray / length


def match_rotation(image, reference, background):
    current = np.asarray(image.convert("L").resize((64, 64)))
    expected = signature(reference)
    best = (-2.0, 0)
    for angle in range(0, 360, 5):
        rotation = cv2.getRotationMatrix2D((31.5, 31.5), angle, 1)
        rotated = cv2.warpAffine(current, rotation, (64, 64), borderValue=background)
        value = float(np.sum(signature(Image.fromarray(rotated)) * expected))
        if value > best[0]:
            best = (value, angle)
    for angle in range(best[1] - 4, best[1] + 5):
        rotation = cv2.getRotationMatrix2D((31.5, 31.5), angle, 1)
        rotated = cv2.warpAffine(current, rotation, (64, 64), borderValue=background)
        value = float(np.sum(signature(Image.fromarray(rotated)) * expected))
        if value > best[0]:
            best = (value, angle)
    return best


def align(image, reference=None, size=512):
    normalized, matrix, bounds, background = locate(image, size)
    score, angle = match_rotation(normalized, reference, background) if reference is not None else (None, 0)
    rotation = cv2.getRotationMatrix2D(((size - 1) / 2, (size - 1) / 2), angle, 1)
    matrix = (np.vstack((rotation, [0, 0, 1])) @ np.vstack((matrix, [0, 0, 1])))[:2]
    source = np.asarray(ImageOps.grayscale(ImageOps.exif_transpose(image)))
    result = cv2.warpAffine(source, matrix, (size, size), borderValue=background)
    return Image.fromarray(result).convert("RGB"), {
        "version": VERSION, "matrix": matrix.tolist(), "source_size": list(image.size),
        "size": size, "bounds": bounds, "angle": angle, "similarity": score,
    }


def transform_boxes(boxes, matrix, size, strict=True):
    matrix = np.asarray(matrix, dtype=np.float64)
    transformed = []
    for box in boxes:
        x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
        corners = np.array([[x, y, 1], [x + w, y, 1], [x + w, y + h, 1], [x, y + h, 1]]) @ matrix.T
        left, top = np.maximum(corners.min(axis=0), 0)
        right, bottom = np.minimum(corners.max(axis=0), size)
        if right <= left or bottom <= top:
            if strict:
                raise ValueError("缺陷框位于刀具裁剪区域之外，请检查标注或定位结果")
            continue
        transformed.append({**box, "x": float(left), "y": float(top), "width": float(right - left), "height": float(bottom - top)})
    return transformed


def source_boxes(boxes, metadata):
    inverse = cv2.invertAffineTransform(np.asarray(metadata["matrix"], dtype=np.float64))
    size = metadata["source_size"]
    result = transform_boxes(boxes, inverse, np.array(size), strict=False)
    return result
