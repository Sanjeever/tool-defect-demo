from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from workbench.api import create_app
from workbench.store import Workspace


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = Workspace(self.root)
        self.workspace.save_specimen("刀具01", "坏件01", "defect", "train", "")
        path = self.root / "data/raw/face.png"
        path.parent.mkdir(parents=True)
        Image.new("L", (640, 480)).save(path)
        self.image_id, _ = self.workspace.add_image(path, "刀具01", "坏件01")

    def test_visible_face_quality_is_independent_of_specimen(self):
        self.workspace.update_image(self.image_id, quality="good", annotated=True, included=True)
        item = Workspace(self.root).state()["images"][0]
        self.assertEqual(item["specimen_quality"], "defect")
        self.assertEqual(item["quality"], "good")
        self.assertTrue(item["annotated"])

    def test_api_saves_multiple_defects_and_rejects_invalid_replacement(self):
        boxes = [{"x": 10, "y": 20, "width": 30, "height": 40, "label": label} for label in ("划痕", "氧化")]
        with TestClient(create_app(self.root)) as client:
            result = client.patch(f"/api/images/{self.image_id}", json={"quality": "defect", "annotated": True, "boxes": boxes})
            self.assertEqual(result.status_code, 200, result.text)
            result = client.patch(f"/api/images/{self.image_id}", json={"boxes": [{**boxes[0], "width": 900}]})
            self.assertEqual(result.status_code, 422)
            self.assertEqual(client.get("/api/state").json()["images"][0]["boxes"], boxes)
            self.assertEqual(client.patch(f"/api/images/{self.image_id}", json={"quality": "good"}).status_code, 422)

    def test_incomplete_bad_image_cannot_be_confirmed(self):
        with self.assertRaisesRegex(ValueError, "缺陷框"):
            self.workspace.update_image(self.image_id, quality="defect", annotated=True)


if __name__ == "__main__":
    unittest.main()
