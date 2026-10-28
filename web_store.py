from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from PIL import Image

from prepare_images import IMAGE_SUFFIXES, prepare_directory


def component(value):
    if not re.fullmatch(r"[\w\-\u4e00-\u9fff]{1,80}", value, flags=re.ASCII):
        raise ValueError("编号和类别请使用中英文、数字、下划线或短横线，长度为 1～80")
    return value


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.database = self.root / "data/web/workspace.sqlite3"
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
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    FOREIGN KEY (tool_type, specimen_id)
                        REFERENCES specimens(tool_type, specimen_id)
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

    def add_image(self, path, tool_type, specimen_id):
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
                "INSERT INTO images (id,path,tool_type,specimen_id,width,height,created_at) VALUES (?,?,?,?,?,?,?)",
                (image_id, path.relative_to(self.root).as_posix(), tool_type, specimen_id, width, height, created_at),
            )
        return image_id, True

    def import_pilot(self):
        directory = self.root / "data/raw/pilot"
        imported = 0
        for path in sorted(directory.rglob("*")):
            parts = path.relative_to(directory).parts
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or len(parts) != 3:
                continue
            tool_type, specimen_id, _ = parts
            with self.connect() as db:
                exists = db.execute(
                    "SELECT 1 FROM specimens WHERE tool_type=? AND specimen_id=?", (tool_type, specimen_id)
                ).fetchone()
            if not exists:
                quality = "good" if specimen_id.startswith("good_") else "defect" if specimen_id.startswith("bad_") else "unknown"
                self.ensure_specimen(tool_type, specimen_id, quality)
            _, added = self.add_image(path, tool_type, specimen_id)
            imported += added
        return imported

    def state(self):
        with self.connect() as db:
            specimens = [dict(row) for row in db.execute("SELECT * FROM specimens ORDER BY tool_type,specimen_id")]
            images = [dict(row) for row in db.execute("""
                SELECT images.*, specimens.quality, specimens.split, specimens.category
                FROM images JOIN specimens USING (tool_type,specimen_id)
                ORDER BY created_at DESC, path DESC
            """)]
        for item in images:
            item["boxes"] = json.loads(item["boxes"])
            item["included"] = bool(item["included"])
        return {"specimens": specimens, "images": images}

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

    def update_image(self, image_id, included, boxes):
        item = self.image(image_id)
        for box in boxes:
            x, y, width, height = (box[key] for key in ("x", "y", "width", "height"))
            if not (0 <= x < x + width <= item["width"] and 0 <= y < y + height <= item["height"]):
                raise ValueError("标注框超出原图范围，或宽高无效")
            if not box["label"].strip():
                raise ValueError("标注框需要缺陷名称")
        with self.connect() as db:
            db.execute("UPDATE images SET included=?,boxes=? WHERE id=?", (included, json.dumps(boxes, ensure_ascii=False), image_id))

    def plan(self, tool_type, model):
        component(tool_type)
        if model not in {"patchcore", "classifier"}:
            raise ValueError("未知模型")
        selected = [item for item in self.state()["images"] if item["tool_type"] == tool_type and item["included"]]
        issues = []
        pending = [item for item in selected if item["quality"] == "unknown" or item["split"] == "unassigned"]
        if pending:
            issues.append(f"有 {len(pending)} 张已选图片尚未确定好坏或实体分组")
        images = [item for item in selected if item not in pending]
        counts = {split: {"good": 0, "defect": 0, "specimens": 0} for split in ("train", "val", "test")}
        for split, count in counts.items():
            rows = [item for item in images if item["split"] == split]
            count["specimens"] = len({item["specimen_id"] for item in rows})
            for quality in ("good", "defect"):
                count[quality] = sum(item["quality"] == quality for item in rows)
        if model == "patchcore":
            for split, quality, title in (("train", "good", "训练集正常图"), ("val", "good", "验证集正常图"), ("val", "defect", "验证集缺陷图")):
                if not counts[split][quality]:
                    issues.append(f"缺少{title}")
            images = [item for item in images if not (item["split"] == "train" and item["quality"] == "defect")]
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
