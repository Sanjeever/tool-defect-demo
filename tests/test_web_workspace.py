from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from web_app import create_app
from web_store import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = Workspace(self.root)

    def add_image(self, specimen, quality, split="unassigned", name="one.png", included=True, category=""):
        self.workspace.save_specimen("type_01", specimen, quality, split, category)
        path = self.root / "data/raw/pilot/type_01" / specimen / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("L", (60, 40), 128).save(path)
        image_id, _ = self.workspace.add_image(path, "type_01", specimen)
        self.workspace.update_image(image_id, included, [])
        return image_id

    def ready_workspace(self):
        self.add_image("good_01", "good", "train")
        self.add_image("good_02", "good", "val")
        self.add_image("bad_01", "defect", "val", category="崩角")

    def test_entity_split_changes_all_repeated_images(self):
        self.add_image("good_01", "good", "train")
        self.add_image("good_01", "good", "train", "two.png")
        self.workspace.save_specimen("type_01", "good_01", "good", "val", "")
        images = self.workspace.state()["images"]
        self.assertEqual({item["split"] for item in images}, {"val"})
        plan = self.workspace.plan("type_01", "patchcore")
        self.assertFalse(plan["ready"])
        self.assertIn("缺少训练集正常图", plan["issues"])
        self.assertEqual(plan["counts"]["val"]["specimens"], 1)

    def test_annotations_round_trip_and_invalid_box_does_not_replace_saved_box(self):
        image_id = self.add_image("bad_01", "defect")
        boxes = [{"x": 4, "y": 6, "width": 15, "height": 12, "label": "崩角"}]
        self.workspace.update_image(image_id, True, boxes)
        reopened = Workspace(self.root)
        self.assertEqual(reopened.image(image_id)["boxes"], boxes)
        with self.assertRaisesRegex(ValueError, "超出原图"):
            reopened.update_image(image_id, False, [{**boxes[0], "width": 100}])
        self.assertEqual(reopened.image(image_id)["boxes"], boxes)
        self.assertEqual(reopened.image(image_id)["included"], 1)

    def test_import_is_idempotent_and_requires_review(self):
        directory = self.root / "data/raw/pilot/type_01/bad_01"
        directory.mkdir(parents=True)
        Image.new("L", (10, 10)).save(directory / "capture.png")
        self.assertEqual(self.workspace.import_pilot(), 1)
        item = self.workspace.state()["images"][0]
        self.assertFalse(item["included"])
        self.assertEqual(item["quality"], "defect")
        self.workspace.update_image(item["id"], True, [])
        self.assertEqual(self.workspace.import_pilot(), 0)
        self.assertTrue(self.workspace.state()["images"][0]["included"])

    def test_path_components_cannot_escape_workspace(self):
        for value in ("../outside", "a/b", "C:\\outside", "a.b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.workspace.ensure_specimen(value, "good_01", "good")
        with self.assertRaises(ValueError):
            self.workspace.add_image(self.root / "outside.png", "type_01", "good_01")

    def test_export_preserves_groups_and_uses_only_normal_training_images(self):
        self.ready_workspace()
        train_id = self.add_image("bad_02", "defect", "train")
        self.add_image("good_03", "good", "test")
        ignored_id = self.add_image("good_04", "good", "train", included=False)
        plan = self.workspace.plan("type_01", "patchcore")
        self.assertTrue(plan["ready"])
        plan["model"] = "patchcore"
        output = self.root / "outputs/job"
        self.assertEqual(self.workspace.export(plan, output, None), 4)
        self.assertFalse((output / "prepared/train/defect").exists())
        self.assertFalse(any(output.rglob(f"{train_id}.png")))
        self.assertFalse(any(output.rglob(f"{ignored_id}.png")))
        self.assertEqual(len(list((output / "prepared/val/good").glob("*.png"))), 1)
        self.assertEqual(len(list((output / "prepared/test/good").glob("*.png"))), 1)
        for path in (output / "prepared").rglob("*.png"):
            with Image.open(path) as image:
                self.assertEqual(image.size, (256, 256))

    def test_classification_requires_real_classes_in_independent_entities(self):
        self.add_image("bad_01", "defect", "train", category="崩角")
        self.add_image("bad_02", "defect", "val", category="崩角")
        self.assertFalse(self.workspace.plan("type_01", "classifier")["ready"])
        self.add_image("bad_03", "defect", "train", category="裂纹")
        self.assertFalse(self.workspace.plan("type_01", "classifier")["ready"])
        self.add_image("bad_04", "defect", "val", category="裂纹")
        self.assertTrue(self.workspace.plan("type_01", "classifier")["ready"])

    def test_experimental_bank_contains_only_normal_training_images(self):
        self.add_image("good_01", "good", "train")
        self.add_image("bad_01", "defect", "unassigned")
        plan = self.workspace.plan("type_01", "patchcore", experimental=True)
        self.assertTrue(plan["ready"])
        self.assertEqual([(item["specimen_id"], item["split"]) for item in plan["images"]], [("good_01", "train")])
        self.assertFalse(self.workspace.plan("type_01", "patchcore")["ready"])
        self.assertFalse(self.workspace.plan("type_01", "patchcore", view="side", experimental=True)["ready"])

    def test_recipe_persists_without_changing_another_view(self):
        self.workspace.save_recipe("type_01", "top", [1, 2, 30, 40])
        reopened = Workspace(self.root)
        self.assertEqual(reopened.recipe("type_01", "top")["roi"], [1, 2, 30, 40])
        self.assertIsNone(reopened.recipe("type_01", "side")["roi"])

    def test_api_blocks_incomplete_data_and_cross_origin_camera_requests(self):
        self.add_image("good_01", "good", "train")
        self.add_image("bad_01", "defect", "val")
        with TestClient(create_app(self.root)) as client:
            response = client.post("/api/jobs", json={"tool_type": "type_01"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("验证集正常图", response.json()["detail"])
            self.assertEqual(client.get("/api/jobs").json(), [])
            with patch("camera_session.CameraSession.capture") as camera:
                response = client.post("/api/camera/capture", headers={"origin": "https://outside.example"},
                                       json={"tool_type": "type_01", "specimen_id": "good_01", "quality": "good"})
                self.assertEqual(response.status_code, 403)
                camera.assert_not_called()

    def test_camera_failure_surfaces_error_and_does_not_register_image(self):
        with TestClient(create_app(self.root)) as client:
            with patch("camera_session.CameraSession.capture", side_effect=RuntimeError("相机返回不完整图像")):
                response = client.post("/api/camera/capture", json={"tool_type": "type_01", "specimen_id": "good_01", "quality": "good"})
            self.assertEqual(response.status_code, 503)
            self.assertIn("不完整", response.json()["detail"])
            self.assertEqual(client.get("/api/state").json()["images"], [])

    def test_training_launch_failure_is_persisted_as_failure_with_manifest(self):
        self.ready_workspace()
        with TestClient(create_app(self.root)) as client:
            with patch("jobs.subprocess.Popen", side_effect=RuntimeError("外部训练进程启动失败")):
                response = client.post("/api/jobs", json={"tool_type": "type_01"})
                self.assertEqual(response.status_code, 200)
                job_id = response.json()["id"]
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    job = client.get("/api/jobs").json()[0]
                    if job["status"] == "failed":
                        break
                    time.sleep(0.02)
            self.assertEqual(job["status"], "failed")
            self.assertIn("外部训练进程启动失败", client.get(f"/api/jobs/{job_id}/log").json()["text"])
            manifest = client.get(f"/api/jobs/{job_id}/artifact", params={"name": "manifest.json"}).json()
            self.assertEqual(len(manifest["images"]), 3)
            self.assertEqual(manifest["settings"]["model"], "patchcore")
            self.assertEqual(client.get(f"/api/jobs/{job_id}/artifact", params={"name": "../../web_app.py"}).status_code, 404)
        with TestClient(create_app(self.root)) as client:
            self.assertEqual(client.get("/api/jobs").json()[0]["status"], "failed")

    def test_upload_keeps_view_and_requires_review_without_opening_camera(self):
        content = BytesIO()
        Image.new("L", (60, 40), 128).save(content, format="PNG")
        with patch("camera_session.load_sdk") as sdk, TestClient(create_app(self.root)) as client:
            self.assertFalse(client.get("/api/camera/status").json()["connected"])
            response = client.post("/api/images/upload", params={"tool_type": "type_01", "specimen_id": "good_01",
                                   "quality": "good", "view": "side"}, content=content.getvalue())
            self.assertEqual(response.status_code, 200)
            item = client.get("/api/state").json()["images"][0]
            self.assertEqual(item["view"], "side")
            self.assertFalse(item["included"])
            self.assertEqual(client.get(f"/api/images/{item['id']}/file").status_code, 200)
            self.assertEqual(client.post("/api/camera/preview").status_code, 422)
            sdk.assert_not_called()

    def write_model_job(self, job_id="model", experimental=True, view="top"):
        directory = self.root / "outputs/web/jobs" / job_id
        directory.mkdir(parents=True)
        (directory / "model.ckpt").write_bytes(b"model-boundary-fixture")
        job = {"id": job_id, "kind": "train", "status": "succeeded", "model": "patchcore", "tool_type": "type_01",
               "view": view, "experimental": experimental, "checkpoint": "model.ckpt", "created_at": "2026-10-28",
               "settings": {"tool_type": "type_01", "view": view, "experimental": experimental, "model": "patchcore",
                            "source_size": [60, 40], "roi": None, "preprocessing": "gray-pad-256-v1"}}
        (directory / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def test_detection_rejects_wrong_view_and_experimental_classification(self):
        self.write_model_job(view="side")
        image_id = self.add_image("good_01", "good")
        with TestClient(create_app(self.root)) as client, patch("jobs.subprocess.Popen") as process:
            response = client.post("/api/detections", json={"anomaly_job": "model", "image_id": image_id})
            self.assertEqual(response.status_code, 422)
            self.assertIn("拍摄面", response.json()["detail"])
            self.assertEqual(client.post("/api/detections", json={"anomaly_job": "model", "image_id": "missing"}).status_code, 404)
            process.assert_not_called()

    def test_review_is_separate_from_model_result_and_survives_restart(self):
        directory = self.root / "outputs/web/jobs/result"
        directory.mkdir(parents=True)
        job = {"id": "result", "kind": "detect", "status": "succeeded", "checkpoint": None,
               "result": {"label": "未校准", "anomaly_score": 1.0}}
        (directory / "job.json").write_text(json.dumps(job), encoding="utf-8")
        with TestClient(create_app(self.root)) as client:
            response = client.post("/api/jobs/result/review", json={"quality": "defect", "note": "人工确认"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["result"], job["result"])
        with TestClient(create_app(self.root)) as client:
            self.assertEqual(client.get("/api/jobs").json()[0]["review"]["quality"], "defect")


if __name__ == "__main__":
    unittest.main()
