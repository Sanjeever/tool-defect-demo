from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from workbench.api import create_app
from workbench.store import Workspace
from workbench.alignment import VERSION


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
        image = Image.new("L", (60, 40), 230)
        ImageDraw.Draw(image).rectangle((15, 8, 45, 32), fill=45)
        image.save(path)
        image_id, _ = self.workspace.add_image(path, "type_01", specimen)
        boxes = [{"x": 16, "y": 10, "width": 4, "height": 5, "label": "缺角"}] if quality == "defect" else []
        self.workspace.update_image(image_id, included, boxes, quality=quality, annotated=quality != "unknown")
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
        boxes = [{"x": 4, "y": 6, "width": 15, "height": 12, "label": "缺角"}]
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
        self.assertEqual(item["quality"], "unknown")
        self.assertEqual(item["specimen_quality"], "defect")
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

    def test_detection_requires_annotated_defects_and_normal_reference(self):
        self.add_image("bad_01", "defect", "train", category="崩角")
        self.add_image("bad_02", "defect", "val", category="崩角")
        self.assertFalse(self.workspace.plan("type_01", "detector")["ready"])
        self.add_image("bad_03", "defect", "train", category="裂纹")
        self.assertFalse(self.workspace.plan("type_01", "detector")["ready"])
        self.add_image("bad_04", "defect", "val", category="裂纹")
        self.add_image("good_01", "good", "train")
        self.assertTrue(self.workspace.plan("type_01", "detector")["ready"])

    def test_coco_export_contains_negative_images_and_transformed_defects(self):
        self.add_image("good_01", "good", "train")
        self.add_image("bad_01", "defect", "train")
        plan = self.workspace.plan("type_01", "detector", experimental=True)
        self.assertTrue(plan["ready"])
        plan["model"] = "detector"
        output = self.root / "outputs/dataset"
        self.workspace.export(plan, output)
        annotations = json.loads((output / "prepared/annotations/instances_train.json").read_text(encoding="utf-8"))
        self.assertEqual(len(annotations["images"]), 2)
        self.assertEqual(len(annotations["annotations"]), 1)
        self.assertEqual([item["name"] for item in annotations["categories"]], ["缺角"])
        box = annotations["annotations"][0]["bbox"]
        self.assertTrue(0 <= box[0] < box[0] + box[2] <= 512)
        self.assertTrue(0 <= box[1] < box[1] + box[3] <= 512)
        self.assertTrue((output / "transforms.json").is_file())

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
            response = client.post("/api/jobs", json={"tool_type": "type_01", "experimental": False})
            self.assertEqual(response.status_code, 422)
            self.assertIn("验证集正常图", response.json()["detail"])
            self.assertEqual(client.get("/api/jobs").json(), [])
            with patch("workbench.camera_session.CameraSession.capture") as camera:
                response = client.post("/api/camera/capture", headers={"origin": "https://outside.example"},
                                       json={"tool_type": "type_01", "specimen_id": "good_01", "quality": "good"})
                self.assertEqual(response.status_code, 403)
                camera.assert_not_called()

    def test_camera_failure_surfaces_error_and_does_not_register_image(self):
        with TestClient(create_app(self.root)) as client:
            with patch("workbench.camera_session.CameraSession.capture", side_effect=RuntimeError("相机返回不完整图像")):
                response = client.post("/api/camera/capture", json={"tool_type": "type_01", "specimen_id": "good_01", "quality": "good"})
            self.assertEqual(response.status_code, 503)
            self.assertIn("不完整", response.json()["detail"])
            self.assertEqual(client.get("/api/state").json()["images"], [])

    def test_training_launch_failure_is_persisted_as_failure_with_manifest(self):
        self.ready_workspace()
        with TestClient(create_app(self.root)) as client:
            with patch("workbench.jobs.subprocess.Popen", side_effect=RuntimeError("外部训练进程启动失败")):
                response = client.post("/api/jobs", json={"tool_type": "type_01", "experimental": False})
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
            self.assertEqual(client.get(f"/api/jobs/{job_id}/artifact", params={"name": "../../app.py"}).status_code, 404)
        with TestClient(create_app(self.root)) as client:
            self.assertEqual(client.get("/api/jobs").json()[0]["status"], "failed")

    def test_upload_keeps_view_and_requires_review_without_opening_camera(self):
        content = BytesIO()
        Image.new("L", (60, 40), 128).save(content, format="PNG")
        with patch("workbench.camera_session.load_sdk") as sdk, TestClient(create_app(self.root)) as client:
            self.assertFalse(client.get("/api/camera/status").json()["connected"])
            response = client.post("/api/images/upload", params={"tool_type": "type_01", "specimen_id": "good_01",
                                   "quality": "good", "view": "side"}, content=content.getvalue())
            self.assertEqual(response.status_code, 200)
            item = client.get("/api/state").json()["images"][0]
            self.assertEqual(item["view"], "side")
            self.assertFalse(item["included"])
            self.assertEqual(client.get(f"/api/images/{item['id']}/file").status_code, 200)
            self.assertEqual(client.post("/api/camera/preview").status_code, 422)
            self.assertEqual(client.get("/api/camera/live").status_code, 422)
            sdk.assert_not_called()

    def write_model_job(self, job_id="model", experimental=True, view="top"):
        directory = self.root / "outputs/workbench/jobs" / job_id
        directory.mkdir(parents=True)
        (directory / "model.ckpt").write_bytes(b"model-boundary-fixture")
        (directory / "model.json").write_text(json.dumps({"experimental": experimental}), encoding="utf-8")
        (directory / "manifest.json").write_text("{}", encoding="utf-8")
        Image.new("RGB", (512, 512)).save(directory / "reference.png")
        job = {"id": job_id, "kind": "train", "status": "succeeded", "model": "patchcore", "tool_type": "type_01",
               "view": view, "experimental": experimental, "checkpoint": "model.ckpt", "created_at": "2026-10-28",
               "settings": {"tool_type": "type_01", "view": view, "experimental": experimental, "model": "patchcore",
                            "preprocessing": VERSION}}
        (directory / "job.json").write_text(json.dumps(job), encoding="utf-8")

    def test_detection_requires_enabled_scheme_and_scheme_rejects_wrong_face(self):
        self.write_model_job(view="side")
        self.write_model_job(job_id="top_model")
        image_id = self.add_image("good_01", "good")
        with TestClient(create_app(self.root)) as client, patch("workbench.jobs.subprocess.Popen") as process:
            response = client.post("/api/detections", json={"anomaly_job": "model", "image_id": image_id})
            self.assertEqual(response.status_code, 422)
            self.assertIn("启用", response.json()["detail"])
            self.assertEqual(client.post("/api/detections", json={"anomaly_job": "model", "image_id": "missing"}).status_code, 404)
            response = client.put("/api/schemes", json={"tool_type": "type_01", "view": "top", "anomaly_job": "model"})
            self.assertEqual(response.status_code, 422)
            self.assertIn("拍摄面", response.json()["detail"])
            response = client.put("/api/schemes", json={"tool_type": "type_01", "view": "top", "anomaly_job": "top_model"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(client.get("/api/state").json()["schemes"]), 1)
            self.assertEqual(client.delete("/api/schemes/type_01/top").status_code, 200)
            self.assertEqual(client.get("/api/state").json()["schemes"], [])
            process.assert_not_called()

    def test_review_is_separate_from_model_result_and_survives_restart(self):
        directory = self.root / "outputs/workbench/jobs/result"
        directory.mkdir(parents=True)
        job = {"id": "result", "kind": "detect", "status": "succeeded", "checkpoint": None,
               "result": {"label": "未校准", "anomaly_score": 1.0}}
        (directory / "job.json").write_text(json.dumps(job), encoding="utf-8")
        Image.new("RGB", (60, 40)).save(directory / "source.png")
        with TestClient(create_app(self.root)) as client:
            response = client.post("/api/jobs/result/review", json={"quality": "defect", "note": "人工确认"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["result"], job["result"])
            exported = client.get("/api/jobs/result/artifact", params={"name": "result.json"}).json()
            self.assertEqual(exported["review"]["note"], "人工确认")
            client.post("/api/jobs/result/review", json={"quality": "good", "note": "修正判断"})
            exported = client.get("/api/jobs/result/artifact", params={"name": "result.json"}).json()
            self.assertEqual(len(exported["reviews"]), 2)
            self.assertEqual(exported["label"], "未校准")
        with TestClient(create_app(self.root)) as client:
            self.assertEqual(client.get("/api/jobs").json()[0]["review"]["quality"], "good")

    def test_model_download_includes_experimental_metadata(self):
        self.write_model_job()
        with TestClient(create_app(self.root)) as client:
            response = client.get("/api/jobs/model/artifact", params={"name": "model.zip"})
            self.assertEqual(response.status_code, 200)
            with ZipFile(BytesIO(response.content)) as archive:
                self.assertEqual(set(archive.namelist()), {"model.ckpt", "model.json", "manifest.json", "reference.png"})
                self.assertTrue(json.loads(archive.read("model.json"))["experimental"])

    def test_manual_rerun_uses_saved_source_without_recapturing(self):
        self.write_model_job()
        self.workspace.save_scheme("type_01", "top", "model", None)
        directory = self.root / "outputs/workbench/jobs/inspection"
        directory.mkdir()
        Image.new("RGB", (60, 40), "red").save(directory / "source.png")
        (directory / "job.json").write_text(json.dumps({"id": "inspection", "kind": "detect", "status": "succeeded"}), encoding="utf-8")
        app = create_app(self.root)
        with TestClient(app) as client, patch.object(app.state.jobs, "start", return_value={"id": "retry"}) as start, patch.object(app.state.camera, "capture") as camera:
            result = client.post("/api/jobs/inspection/rerun", json={"route_tool": "type_01", "route_view": "top", "camera": True})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(start.call_args.args[1]["parent_job"], "inspection")
            self.assertFalse(start.call_args.args[1]["camera"])
            self.assertEqual(start.call_args.kwargs["image"].getpixel((0, 0)), (255, 0, 0))
            camera.assert_not_called()

    def test_review_adoption_preserves_existing_validation_and_test_groups(self):
        for split in ("unassigned", "val", "test"):
            self.workspace.save_specimen("type_01", split, "defect", split, "")
            directory = self.root / "outputs/workbench/jobs" / split
            directory.mkdir(parents=True)
            Image.new("RGB", (60, 40)).save(directory / "source.png")
            job = {"id": split, "kind": "detect", "status": "succeeded", "review": {
                "quality": "good", "tool_type": "type_01", "view": "top", "boxes": []}}
            (directory / "job.json").write_text(json.dumps(job), encoding="utf-8")
            with TestClient(create_app(self.root)) as client:
                result = client.post(f"/api/jobs/{split}/adopt", json={"tool_type": "type_01", "specimen_id": split, "quality": "defect"})
                self.assertEqual(result.status_code, 200, result.text)
                state = client.get("/api/state").json()
                specimen = next(item for item in state["specimens"] if item["specimen_id"] == split)
                self.assertEqual(specimen["split"], "train" if split == "unassigned" else split)
                image = next(item for item in state["images"] if item["id"] == result.json()["id"])
                self.assertEqual(image["quality"], "good")
                self.assertEqual(image["specimen_quality"], "defect")
                self.assertEqual(client.post(f"/api/jobs/{split}/adopt", json={"tool_type": "type_01", "specimen_id": split, "quality": "defect"}).status_code, 422)

    def test_live_preview_streams_jpeg_without_registering_samples(self):
        output = BytesIO()
        Image.new("L", (30, 20), 128).save(output, format="JPEG")
        app = create_app(self.root)
        with TestClient(app) as client:
            with patch.object(app.state.camera, "status", side_effect=[{"connected": True}, {"connected": True}, {"connected": False}]), \
                 patch.object(app.state.camera, "next_preview", return_value=(1, output.getvalue())) as frame:
                response = client.get("/api/camera/live")
            self.assertEqual(response.status_code, 200)
            self.assertIn("multipart/x-mixed-replace", response.headers["content-type"])
            self.assertIn(b"Content-Type: image/jpeg", response.content)
            self.assertIn(output.getvalue(), response.content)
            frame.assert_called_once_with(0)
            self.assertEqual(client.get("/api/state").json()["images"], [])


if __name__ == "__main__":
    unittest.main()
