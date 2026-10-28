from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from PIL import Image

from .preprocessing import IMAGE_SUFFIXES, prepare_directory

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
        for item in images:
            item["boxes"] = json.loads(item["boxes"])
            item["included"] = bool(item["included"])
            item["annotated"] = bool(item["annotated"])
        return {"specimens": specimens, "images": images, "labels": list(DEFECT_LABELS)}

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
        if model not in {"patchcore", "classifier"}:
            raise ValueError("未知模型")
        selected = [item for item in self.state()["images"]
                    if item["tool_type"] == tool_type and item["view"] == view and item["included"]]
        issues = []
        pending = [item for item in selected if item["quality"] == "unknown" or item["split"] == "unassigned"]
        if pending and not experimental:
            issues.append(f"有 {len(pending)} 张已选图片尚未确定好坏或实体分组")
        images = [item for item in selected if item not in pending]
        counts = {split: {"good": 0, "defect": 0, "specimens": 0} for split in ("train", "val", "test")}
        for split, count in counts.items():
            rows = [item for item in images if item["split"] == split]
            count["specimens"] = len({item["specimen_id"] for item in rows})
            for quality in ("good", "defect"):
                count[quality] = sum(item["quality"] == quality for item in rows)
        if experimental and model != "patchcore":
            raise ValueError("实验建库适用于 PatchCore")
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
            images = [item for item in images if item["quality"] == "defect"]
            if any(not item["category"] for item in images):
                issues.append("已选坏件需要填写真实缺陷类别")
            classes = {item["category"] for item in images if item["split"] == "train" and item["category"]}
            if len(classes) < 2:
                issues.append("YOLO 分类需要至少两个真实缺陷类别")
            for split in ("val", "test"):
                split_classes = {item["category"] for item in images if item["split"] == split}
                if (split == "val" or split_classes) and split_classes != classes:
                    issues.append(f"{split} 缺陷类别必须与训练集一致，且每类需要不同实体")
        if not selected:
            issues.insert(0, "尚未选入图片，请先在图片库审核并勾选“用于数据集”")
        if len({(item["width"], item["height"]) for item in images}) > 1:
            issues.append("同一型号和拍摄面的训练图片需要保持相同原图尺寸")
        return {"ready": not issues, "issues": issues, "counts": counts, "images": images}

    def export(self, plan, output, roi):
        output = Path(output)
        raw = output / "raw"
        for item in plan["images"]:
            category = item["quality"] if plan["model"] == "patchcore" else item["category"]
            target = raw / item["split"] / category / f"{item['id']}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(self.root / item["path"]) as image:
                image.save(target)
        return prepare_directory(raw, output / "prepared", roi, 256)
