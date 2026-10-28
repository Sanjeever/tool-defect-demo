from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from PIL import Image

from .preprocessing import IMAGE_SUFFIXES
from .alignment import align, transform_boxes

DEFECT_LABELS = ("磨损", "缺角", "划痕", "氧化")


def component(value):
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]{1,80}", value, flags=re.ASCII):
        raise ValueError("编号和类别请使用中英文、数字、下划线或短横线，长度为 1～80")
    return value


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.database = self.root / "data/web/workspace-v2.sqlite3"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS specimens (
                    tool_type TEXT NOT NULL, specimen_id TEXT NOT NULL,
                    quality TEXT NOT NULL, split TEXT NOT NULL DEFAULT 'unassigned',
                    category TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (tool_type, specimen_id)
                );
                CREATE TABLE IF NOT EXISTS images (
                    id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                    tool_type TEXT NOT NULL, specimen_id TEXT NOT NULL,
                    width INTEGER NOT NULL, height INTEGER NOT NULL,
                    included INTEGER NOT NULL DEFAULT 0,
                    boxes TEXT NOT NULL DEFAULT '[]',
                    view TEXT NOT NULL DEFAULT 'top',
                    quality TEXT NOT NULL DEFAULT 'unknown',
                    annotated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    FOREIGN KEY (tool_type, specimen_id)
                        REFERENCES specimens(tool_type, specimen_id)
                );
                CREATE TABLE IF NOT EXISTS recipes (
                    tool_type TEXT NOT NULL, view TEXT NOT NULL,
                    roi TEXT, PRIMARY KEY (tool_type, view)
                );
                CREATE TABLE IF NOT EXISTS schemes (
                    tool_type TEXT NOT NULL, view TEXT NOT NULL,
                    anomaly_job TEXT NOT NULL, detector_job TEXT,
                    PRIMARY KEY (tool_type, view)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_specimen(self, tool_type, specimen_id, quality, split, category):
        component(tool_type)
        component(specimen_id)
        if quality not in {"good", "defect", "unknown"}:
            raise ValueError("未知好坏标签")
        if split not in {"unassigned", "train", "val", "test"}:
            raise ValueError("未知数据集分组")
        if category:
            component(category)
        if quality != "defect" and category:
            raise ValueError("缺陷类别只能分配给坏件")
        with self.connect() as db:
            db.execute("""
                INSERT INTO specimens VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tool_type, specimen_id) DO UPDATE SET
                quality=excluded.quality, split=excluded.split, category=excluded.category
            """, (tool_type, specimen_id, quality, split, category))

    def ensure_specimen(self, tool_type, specimen_id, quality):
        component(tool_type)
        component(specimen_id)
        with self.connect() as db:
            existing = db.execute(
                "SELECT quality FROM specimens WHERE tool_type=? AND specimen_id=?",
                (tool_type, specimen_id),
            ).fetchone()
        if existing and existing["quality"] != quality:
            raise ValueError("该实体已有不同好坏标签，请到图片库修改实体分组")
        if not existing:
            self.save_specimen(tool_type, specimen_id, quality, "unassigned", "")

    def add_image(self, path, tool_type, specimen_id, view="top"):
        component(view)
        path = Path(path).resolve()
        if not path.is_relative_to(self.root / "data/raw"):
            raise ValueError("图片必须位于 data/raw 内")
        with Image.open(path) as image:
            width, height = image.size
        created_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="milliseconds")
        with self.connect() as db:
            existing = db.execute(
                "SELECT id FROM images WHERE path=?", (path.relative_to(self.root).as_posix(),)
            ).fetchone()
            if existing:
                db.execute("UPDATE images SET created_at=? WHERE id=?", (created_at, existing["id"]))
                return existing["id"], False
            image_id = uuid4().hex
            db.execute(
                "INSERT INTO images (id,path,tool_type,specimen_id,width,height,created_at,view) VALUES (?,?,?,?,?,?,?,?)",
                (image_id, path.relative_to(self.root).as_posix(), tool_type, specimen_id, width, height, created_at, view),
            )
        return image_id, True

    def import_pilot(self):
        directory = self.root / "data/raw/pilot"
        imported = 0
        for path in sorted(directory.rglob("*")):
            parts = path.relative_to(directory).parts
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or len(parts) not in {3, 4}:
                continue
            tool_type, specimen_id = parts[:2]
            view = parts[2] if len(parts) == 4 else "top"
            with self.connect() as db:
                exists = db.execute(
                    "SELECT 1 FROM specimens WHERE tool_type=? AND specimen_id=?", (tool_type, specimen_id)
                ).fetchone()
            if not exists:
                quality = "good" if specimen_id.startswith("good_") else "defect" if specimen_id.startswith("bad_") else "unknown"
                self.ensure_specimen(tool_type, specimen_id, quality)
            _, added = self.add_image(path, tool_type, specimen_id, view)
            imported += added
        return imported

    def state(self):
        with self.connect() as db:
            specimens = [dict(row) for row in db.execute("SELECT * FROM specimens ORDER BY tool_type,specimen_id")]
            images = [dict(row) for row in db.execute("""
                SELECT images.*, specimens.quality AS specimen_quality, specimens.split, specimens.category
                FROM images JOIN specimens USING (tool_type,specimen_id)
                ORDER BY created_at DESC, path DESC
            """)]
            schemes = [dict(row) for row in db.execute("SELECT * FROM schemes ORDER BY tool_type,view")]
        for item in images:
            item["boxes"] = json.loads(item["boxes"])
            item["included"] = bool(item["included"])
            item["annotated"] = bool(item["annotated"])
        return {"specimens": specimens, "images": images, "labels": list(DEFECT_LABELS), "schemes": schemes}

    def image(self, image_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM images WHERE id=?", (image_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("图片不存在")
        item = dict(row)
        item["boxes"] = json.loads(item["boxes"])
        return item

    def image_path(self, image_id):
        path = (self.root / self.image(image_id)["path"]).resolve()
        if not path.is_relative_to(self.root / "data/raw") or not path.is_file():
            raise FileNotFoundError("原始图片不存在或超出 data/raw")
        return path

    def update_image(self, image_id, included=None, boxes=None, quality=None, annotated=None, view=None):
        item = self.image(image_id)
        boxes = item["boxes"] if boxes is None else boxes
        quality = item["quality"] if quality is None else quality
        annotated = bool(item["annotated"]) if annotated is None else annotated
        if quality not in {"good", "defect", "unknown"}:
            raise ValueError("未知当前面好坏标签")
        for box in boxes:
            x, y, width, height = (box[key] for key in ("x", "y", "width", "height"))
            if not (0 <= x < x + width <= item["width"] and 0 <= y < y + height <= item["height"]):
                raise ValueError("标注框超出原图范围，或宽高无效")
            if box["label"] not in DEFECT_LABELS:
                raise ValueError("缺陷类别应为磨损、缺角、划痕或氧化")
        if annotated and (quality == "unknown" or (quality == "defect" and not boxes)):
            raise ValueError("完成标注需要确认当前面好坏，坏件需要至少一个缺陷框")
        if quality != "defect" and boxes:
            raise ValueError("有缺陷框的图片应标为当前面不合格")
        if view is not None and view not in {"top", "bottom"}:
            raise ValueError("拍摄面应为正面或背面")
        with self.connect() as db:
            db.execute("UPDATE images SET included=?,boxes=?,quality=?,annotated=?,view=? WHERE id=?",
                       (bool(item["included"]) if included is None else included,
                        json.dumps(boxes, ensure_ascii=False), quality, annotated, view or item["view"], image_id))

    def recipe(self, tool_type, view):
        component(tool_type)
        component(view)
        with self.connect() as db:
            row = db.execute("SELECT roi FROM recipes WHERE tool_type=? AND view=?", (tool_type, view)).fetchone()
        return {"tool_type": tool_type, "view": view, "roi": json.loads(row["roi"]) if row and row["roi"] else None}

    def save_recipe(self, tool_type, view, roi):
        self.recipe(tool_type, view)
        if roi is not None:
            left, top, right, bottom = roi
            if not (0 <= left < right and 0 <= top < bottom):
                raise ValueError("检测区域坐标无效")
        with self.connect() as db:
            db.execute("INSERT INTO recipes VALUES (?,?,?) ON CONFLICT(tool_type,view) DO UPDATE SET roi=excluded.roi",
                       (tool_type, view, json.dumps(roi)))

    def plan(self, tool_type, model, view="top", experimental=False):
        component(tool_type)
        component(view)
        if model not in {"patchcore", "detector"}:
            raise ValueError("未知模型")
        selected = [item for item in self.state()["images"]
                    if item["tool_type"] == tool_type and item["view"] == view and item["included"]]
        issues = []
        pending = [item for item in selected if not item["annotated"] or item["quality"] == "unknown" or item["split"] == "unassigned"]
        if pending and not experimental:
            issues.append(f"有 {len(pending)} 张已选图片尚未确定好坏或实体分组")
        images = [item for item in selected if item not in pending]
        counts = {split: {"good": 0, "defect": 0, "specimens": 0} for split in ("train", "val", "test")}
        for split, count in counts.items():
            rows = [item for item in images if item["split"] == split]
            count["specimens"] = len({item["specimen_id"] for item in rows})
            for quality in ("good", "defect"):
                count[quality] = sum(item["quality"] == quality for item in rows)
        if model == "patchcore":
            requirements = [("train", "good", "训练集正常图")]
            if not experimental:
                requirements += [("val", "good", "验证集正常图"), ("val", "defect", "验证集缺陷图")]
            for split, quality, title in requirements:
                if not counts[split][quality]:
                    issues.append(f"缺少{title}")
            images = [item for item in images if not (item["split"] == "train" and item["quality"] == "defect")]
            if experimental:
                images = [item for item in images if item["split"] == "train" and item["quality"] == "good"]
        else:
            if not any(item["split"] == "train" and item["boxes"] for item in images):
                issues.append("缺少已完成缺陷框标注的训练图片")
            if not experimental and not any(item["split"] == "val" and item["boxes"] for item in images):
                issues.append("缺少独立验证实物的缺陷框图片")
            if experimental:
                images = [item for item in images if item["split"] == "train"]
        if not any(item["split"] == "train" and item["quality"] == "good" for item in images):
            issues.append("需要至少一张当前面合格的训练图片作为定位对齐参考")
        if not selected:
            issues.insert(0, "尚未选入图片，请先在图片库审核并勾选“用于数据集”")
        return {"ready": not issues, "issues": issues, "counts": counts, "images": images}

    def export(self, plan, output, roi=None):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        reference_item = next(item for item in plan["images"] if item["split"] == "train" and item["quality"] == "good")
        with Image.open(self.root / reference_item["path"]) as image:
            reference, _ = align(image)
        reference.save(output / "reference.png")
        datasets = {split: {"images": [], "annotations": [], "categories": [
            {"id": index + 1, "name": label} for index, label in enumerate(DEFECT_LABELS)
        ]} for split in ("train", "val", "test")}
        transforms = {}
        for item in plan["images"]:
            with Image.open(self.root / item["path"]) as image:
                prepared, metadata = align(image, reference)
            transforms[item["id"]] = metadata
            if plan["model"] == "patchcore":
                target = output / "prepared" / item["split"] / item["quality"] / f"{item['id']}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                prepared.resize((256, 256), Image.Resampling.LANCZOS).save(target)
            else:
                target = output / "prepared/images" / item["split"] / f"{item['id']}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                prepared.save(target)
                dataset = datasets[item["split"]]
                image_index = len(dataset["images"]) + 1
                dataset["images"].append({"id": image_index, "file_name": f"{item['id']}.png", "width": 512, "height": 512})
                for box in transform_boxes(item["boxes"], metadata["matrix"], 512):
                    dataset["annotations"].append({"id": len(dataset["annotations"]) + 1, "image_id": image_index,
                        "category_id": DEFECT_LABELS.index(box["label"]) + 1, "bbox": [box[key] for key in ("x", "y", "width", "height")],
                        "area": box["width"] * box["height"], "iscrowd": 0})
        if plan["model"] == "detector":
            annotations = output / "prepared/annotations"
            annotations.mkdir(parents=True)
            for split, dataset in datasets.items():
                if dataset["images"]:
                    (annotations / f"instances_{split}.json").write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
        (output / "transforms.json").write_text(json.dumps(transforms, ensure_ascii=False), encoding="utf-8")
        return len(plan["images"])

    def save_scheme(self, tool_type, view, anomaly_job, detector_job):
        component(tool_type)
        component(view)
        with self.connect() as db:
            db.execute("INSERT INTO schemes VALUES (?,?,?,?) ON CONFLICT(tool_type,view) DO UPDATE SET anomaly_job=excluded.anomaly_job,detector_job=excluded.detector_job",
                       (tool_type, view, anomaly_job, detector_job))
