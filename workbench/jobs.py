from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image

from .alignment import VERSION, align, source_boxes


ROOT = Path(__file__).resolve().parent.parent
GETI_PROJECT = ROOT / "engines/geti"


class Jobs:
    def __init__(self, root, workspace):
        self.root = Path(root) / "outputs/workbench/jobs"
        self.workspace = workspace
        self.lock = threading.RLock()
        self.items = {}
        self.process = None
        self.thread = None
        for path in self.root.glob("*/job.json"):
            job = json.loads(path.read_text(encoding="utf-8"))
            self.items[job["id"]] = job
            if job["status"] in {"running", "stopping"}:
                self.update(job["id"], status="interrupted", error="服务退出导致任务中断，请重新运行")

    def get(self, job_id):
        with self.lock:
            if job_id not in self.items:
                raise FileNotFoundError("任务不存在")
            return json.loads(json.dumps(self.items[job_id]))

    def list(self):
        with self.lock:
            return [self.get(key) for key in sorted(self.items, reverse=True)]

    def update(self, job_id, **values):
        with self.lock:
            self.items[job_id].update(values)
            path = self.root / job_id / "job.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.items[job_id], ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)

    def model(self, job_id, model):
        job = self.get(job_id)
        if job["status"] != "succeeded" or job["kind"] != "train" or job["model"] != model:
            raise ValueError("请选择训练成功且类型匹配的模型")
        if job["settings"]["preprocessing"] != VERSION:
            raise ValueError("预处理版本不匹配，请重新训练")
        if not (self.root / job_id / job["checkpoint"]).is_file():
            raise FileNotFoundError("模型文件已丢失，请重新训练")
        return job

    def start(self, kind, settings, plan=None, image=None):
        with self.lock:
            if any(job["status"] in {"running", "stopping"} for job in self.items.values()):
                raise ValueError("已有任务运行，请等待完成或先停止")
            job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:6]
            directory = self.root / job_id
            directory.mkdir(parents=True)
            if image is not None:
                image.save(directory / "source.png")
            job = {"id": job_id, "kind": kind, "status": "running", "phase": "preparing",
                   "created_at": datetime.now().isoformat(timespec="seconds"), "settings": settings,
                   "tool_type": settings.get("tool_type", "auto"), "view": settings.get("view", "auto"),
                   "model": settings.get("model", "scheme"), "experimental": settings.get("experimental", True),
                   "error": "", "checkpoint": None}
            self.items[job_id] = job
            self.update(job_id)
            self.write(directory / "manifest.json", {"settings": settings, "images": plan["images"] if plan else []})
            self.thread = threading.Thread(target=self.run, args=(job_id, plan), daemon=True)
            self.thread.start()
            return self.get(job_id)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def invoke(self, job_id, module, arguments, log, geti=False):
        project = GETI_PROJECT if geti else ROOT
        command = ["uv", "run", "--no-sync", "--project", str(project), "python", "-u", "-m", module, *map(str, arguments)]
        log.write("执行：" + subprocess.list2cmdline(command) + "\n")
        log.flush()
        with self.lock:
            if self.get(job_id)["status"] == "stopping":
                raise InterruptedError("任务已停止")
            self.process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        return_code = self.process.wait()
        with self.lock:
            self.process = None
            if self.get(job_id)["status"] == "stopping":
                raise InterruptedError("任务已停止")
        if return_code:
            raise RuntimeError(f"模型进程退出码 {return_code}，请查看日志")

    def run(self, job_id, plan):
        directory = self.root / job_id
        job = self.get(job_id)
        settings = job["settings"]
        try:
            with (directory / "run.log").open("w", encoding="utf-8") as log:
                if job["kind"] == "train":
                    count = self.workspace.export(plan, directory)
                    log.write(f"已定位对齐 {count} 张图片，原图及标注保持不变\n")
                    self.update(job_id, phase="training")
                    arguments = ["train", "--data", directory / "prepared", "--output", directory / settings["model"],
                                 "--batch-size", settings["batch_size"], "--device", settings["device"]]
                    if settings["experimental"]:
                        arguments += ["--experimental"]
                    if settings["model"] == "detector":
                        arguments += ["--epochs", settings["epochs"]]
                    self.invoke(job_id, "workbench.geti_worker" if settings["model"] == "detector" else "workbench.anomaly",
                                arguments, log, geti=settings["model"] == "detector")
                    checkpoint = f"{settings['model']}/model.ckpt"
                    if not (directory / checkpoint).is_file():
                        raise FileNotFoundError("模型进程未生成预期权重")
                    metrics_path = directory / settings["model"] / "metrics.json"
                    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
                    self.update(job_id, status="succeeded", phase="finished", checkpoint=checkpoint, metrics=metrics)
                else:
                    self.update(job_id, phase="predicting")
                    result = self.detect(job_id, settings, directory, log)
                    self.write(directory / "result.json", result)
                    self.update(job_id, status="succeeded", phase="finished", result=result,
                                tool_type=result.get("tool_type", "auto"), view=result.get("view", "auto"))
        except Exception as error:
            with (directory / "run.log").open("a", encoding="utf-8") as log:
                log.write(f"\n{type(error).__name__}: {error}\n")
            self.update(job_id, status="cancelled" if isinstance(error, InterruptedError) else "failed",
                        phase="finished", error=str(error))

    def detect(self, job_id, settings, directory, log):
        with Image.open(directory / "source.png") as image:
            source = image.copy()
        candidates = []
        for scheme in settings["schemes"]:
            with Image.open(self.root / scheme["anomaly_job"] / "reference.png") as reference:
                _, metadata = align(source, reference)
            candidates.append({**scheme, "similarity": metadata["similarity"]})
        candidates.sort(key=lambda value: value["similarity"], reverse=True)
        forced = settings.get("route_tool")
        chosen = next((item for item in candidates if item["tool_type"] == forced and item["view"] == settings["route_view"]), None) if forced else candidates[0]
        recognition = {"method": "人工指定" if forced else "旋转参考图匹配", "candidates": candidates,
                       "calibrated": False, "similarity": chosen["similarity"] if chosen else None}
        if not chosen:
            raise ValueError("人工指定的类型和拍摄面没有启用方案")
        if not forced and (chosen["similarity"] < 0.65 or (len(candidates) > 1 and chosen["similarity"] - candidates[1]["similarity"] < 0.025)):
            return {"label": "待确认类型或拍摄面", "scope": "当前可见面", "recognition": recognition,
                    "boxes": [], "source_size": list(source.size), "anomaly_score": None}
        anomaly = self.model(chosen["anomaly_job"], "patchcore")
        with Image.open(self.root / anomaly["id"] / "reference.png") as reference:
            prepared, metadata = align(source, reference)
        prepared.save(directory / "aligned.png")
        prepared.resize((256, 256), Image.Resampling.LANCZOS).save(directory / "input.png")
        self.write(directory / "transform.json", metadata)
        self.invoke(job_id, "workbench.anomaly", ["predict", "--checkpoint", self.root / anomaly["id"] / anomaly["checkpoint"],
                    "--source", directory / "input.png", "--output", directory / "predictions", "--device", settings["device"]], log)
        result = json.loads((directory / "predictions/results.jsonl").read_text(encoding="utf-8").strip())
        raw_map = np.load(directory / "predictions/input.map.npy")
        display = (raw_map - raw_map.min()) / max(float(np.ptp(raw_map)), 1e-8) if anomaly["experimental"] else np.clip(raw_map, 0, 1)
        heat = cv2.resize(display, (512, 512))
        inverse = cv2.invertAffineTransform(np.asarray(metadata["matrix"]))
        mapped = cv2.warpAffine(heat, inverse, source.size)
        colors = cv2.cvtColor(cv2.applyColorMap((mapped * 255).astype(np.uint8), cv2.COLORMAP_JET), cv2.COLOR_BGR2RGB)
        alpha = (mapped * 0.55)[..., None]
        overlay = (np.asarray(source.convert("RGB")) * (1 - alpha) + colors * alpha).astype(np.uint8)
        Image.fromarray(overlay).save(directory / "heatmap.png")
        boxes = []
        detector = None
        if chosen.get("detector_job"):
            detector = self.model(chosen["detector_job"], "detector")
            with Image.open(self.root / detector["id"] / "reference.png") as reference:
                detector_input, detector_transform = align(source, reference)
            detector_input.save(directory / "detector-input.png")
            self.invoke(job_id, "workbench.geti_worker", ["predict", "--checkpoint", self.root / detector["id"] / detector["checkpoint"],
                        "--source", directory / "detector-input.png", "--output", directory / "detector.json",
                        "--device", settings["device"], "--min-confidence", settings["min_confidence"]], log, geti=True)
            detections = json.loads((directory / "detector.json").read_text(encoding="utf-8"))
            boxes = source_boxes(detections["boxes"], detector_transform)
            self.write(directory / "detector-transform.json", detector_transform)
        experimental = anomaly["experimental"] or bool(detector and detector["experimental"])
        label = "未校准" if experimental else "当前面不合格" if result["label"] == "异常" or boxes else "当前面合格"
        return {"label": label, "scope": "当前可见面", "tool_type": chosen["tool_type"], "view": chosen["view"],
                "anomaly_score": result["anomaly_score"], "anomaly_label": result["label"], "boxes": boxes,
                "recognition": recognition, "experimental": experimental, "source_size": list(source.size),
                "models": {"anomaly": anomaly["id"], "detector": detector["id"] if detector else None},
                "preprocessing": VERSION, "min_confidence": settings["min_confidence"],
                "defect_status": "已运行" if detector else "尚未配置缺陷模型"}

    def stop(self, job_id):
        with self.lock:
            if self.get(job_id)["status"] in {"running", "stopping"}:
                self.update(job_id, status="stopping")
                if self.process and self.process.poll() is None:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                    else:
                        self.process.terminate()

    def close(self):
        for job in self.list():
            self.stop(job["id"])
        if self.thread:
            self.thread.join(timeout=15)
