from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from uuid import uuid4

from PIL import Image

from .preprocessing import prepare_image


ROOT = Path(__file__).resolve().parent.parent


class Jobs:
    def __init__(self, root, workspace):
        self.root = Path(root) / "outputs/web/jobs"
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
            job = self.items[job_id]
            job.update(values)
            path = self.root / job_id / "job.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)

    def model(self, job_id, model):
        job = self.get(job_id)
        if job["status"] != "succeeded" or job.get("kind") != "train" or job["model"] != model:
            raise ValueError("请选择训练成功且类型匹配的模型")
        if job["settings"].get("preprocessing") != "gray-pad-256-v1":
            raise ValueError("该模型使用旧版预处理，请重新训练")
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
                   "tool_type": settings["tool_type"], "view": settings["view"], "model": settings["model"],
                   "experimental": settings.get("experimental", False), "error": "", "checkpoint": None}
            self.items[job_id] = job
            self.update(job_id)
            (directory / "manifest.json").write_text(json.dumps({"settings": settings, "images": plan["images"] if plan else []},
                                                               ensure_ascii=False, indent=2), encoding="utf-8")
            self.thread = threading.Thread(target=self.run, args=(job_id, plan), daemon=True)
            self.thread.start()
            return self.get(job_id)

    def run(self, job_id, plan):
        directory = self.root / job_id
        job = self.get(job_id)
        settings = job["settings"]
        process = None
        try:
            with (directory / "run.log").open("w", encoding="utf-8") as log:
                if job["kind"] == "train":
                    count = self.workspace.export(plan, directory, settings["roi"])
                    log.write(f"已预处理 {count} 张图片，输入为灰度三通道 256×256\n")
                    script = "workbench.anomaly" if settings["model"] == "patchcore" else "workbench.classifier"
                    command = [script, "train", "--data", str(directory / "prepared"), "--output", str(directory / settings["model"]),
                               "--batch-size", str(settings["batch_size"])]
                    if settings["model"] == "classifier":
                        command += ["--epochs", str(settings["epochs"])]
                    elif settings["experimental"]:
                        command += ["--experimental"]
                else:
                    with Image.open(directory / "source.png") as source:
                        prepare_image(source, settings["roi"], 256).save(directory / "input.png")
                    model = self.model(settings["anomaly_job"], "patchcore")
                    command = ["workbench.anomaly", "predict", "--checkpoint", str(self.root / model["id"] / model["checkpoint"]),
                               "--source", str(directory / "input.png"), "--output", str(directory / "predictions")]
                    if settings["classifier_job"]:
                        classifier = self.model(settings["classifier_job"], "classifier")
                        command += ["--classifier", str(self.root / classifier["id"] / classifier["checkpoint"]),
                                    "--min-confidence", str(settings["min_confidence"])]
                command = [sys.executable, "-u", "-m", command[0], *command[1:], "--device", settings["device"]]
                log.flush()
                with self.lock:
                    if self.get(job_id)["status"] == "stopping":
                        self.update(job_id, status="cancelled", phase="finished")
                        return
                    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
                    self.process = process
                    self.update(job_id, phase="training" if job["kind"] == "train" else "predicting")
                return_code = process.wait()
            with self.lock:
                if self.get(job_id)["status"] == "stopping":
                    self.update(job_id, status="cancelled", phase="finished")
                    return
                if return_code:
                    raise RuntimeError(f"模型进程退出码 {return_code}，请查看日志")
                if job["kind"] == "train":
                    checkpoint = f"{settings['model']}/" + ("model.ckpt" if settings["model"] == "patchcore" else "weights/best.pt")
                    if not (directory / checkpoint).is_file():
                        raise FileNotFoundError("模型进程未生成预期权重")
                    self.update(job_id, status="succeeded", phase="finished", checkpoint=checkpoint)
                else:
                    result = json.loads((directory / "predictions/results.jsonl").read_text(encoding="utf-8").strip())
                    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    self.update(job_id, status="succeeded", phase="finished", result=result)
        except Exception as error:
            with (directory / "run.log").open("a", encoding="utf-8") as log:
                log.write(f"\n{type(error).__name__}: {error}\n")
            self.update(job_id, status="cancelled" if self.get(job_id)["status"] == "stopping" else "failed",
                        phase="finished", error=str(error))
        finally:
            with self.lock:
                if self.process is process:
                    self.process = None

    def stop(self, job_id):
        with self.lock:
            if self.get(job_id)["status"] in {"running", "stopping"}:
                self.update(job_id, status="stopping")
                if self.process and self.process.poll() is None:
                    self.process.terminate()

    def close(self):
        for job in self.list():
            self.stop(job["id"])
        if self.thread:
            self.thread.join(timeout=15)
