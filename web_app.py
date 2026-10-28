import argparse
from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from camera import DEFAULT_SDK_ROOT
from web_store import Workspace


ROOT = Path(__file__).resolve().parent


class CameraSettings(BaseModel):
    sn: str = Field(default="GL0180040948", min_length=1, max_length=80)
    packet_delay: int = Field(default=20000, ge=0, le=1000000)
    sdk_root: str = str(DEFAULT_SDK_ROOT)


class CaptureSettings(CameraSettings):
    tool_type: str
    specimen_id: str
    quality: Literal["good", "defect", "unknown"]


class SpecimenSettings(BaseModel):
    tool_type: str
    specimen_id: str
    quality: Literal["good", "defect", "unknown"]
    split: Literal["unassigned", "train", "val", "test"]
    category: str = ""


class Box(BaseModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=80)


class ImageSettings(BaseModel):
    included: bool
    boxes: list[Box] = Field(default_factory=list, max_length=100)


class TrainSettings(BaseModel):
    tool_type: str
    model: Literal["patchcore", "classifier"] = "patchcore"
    device: Literal["cuda", "cpu"] = "cuda"
    batch_size: int = Field(default=4, ge=1, le=64)
    epochs: int = Field(default=30, ge=1, le=1000)
    roi: tuple[int, int, int, int] | None = None


def create_app(root=ROOT):
    root = Path(root).resolve()
    workspace = Workspace(root)
    job_root = root / "outputs/web/jobs"
    preview_root = root / "outputs/web/preview"
    camera_lock = threading.Lock()
    jobs_lock = threading.Lock()
    jobs = {}
    processes = {}
    threads = []
    for path in sorted(job_root.glob("*/job.json")):
        job = json.loads(path.read_text(encoding="utf-8"))
        if job["status"] in {"running", "stopping"}:
            job["status"] = "interrupted"
            job["error"] = "服务退出前任务未完成，请检查日志后重新运行"
            path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        jobs[job["id"]] = job

    def persist(job):
        directory = job_root / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "job.json"
        temporary = directory / "job.json.tmp"
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def update_job(job_id, **values):
        with jobs_lock:
            jobs[job_id].update(values)
            persist(jobs[job_id])

    def run_job(job_id, plan, settings):
        directory = job_root / job_id
        try:
            (directory / "manifest.json").write_text(
                json.dumps({"settings": settings.model_dump(), "images": plan["images"]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with (directory / "run.log").open("w", encoding="utf-8") as log:
                count = workspace.export(plan, directory, settings.roi)
                log.write(f"已预处理 {count} 张图片，输入为 256×256\n")
                log.flush()
                model_dir = directory / settings.model
                script = "anomaly.py" if settings.model == "patchcore" else "classifier.py"
                command = [sys.executable, "-u", str(ROOT / script), "train", "--data", str(directory / "prepared"),
                           "--output", str(model_dir), "--device", settings.device, "--batch-size", str(settings.batch_size)]
                if settings.model == "classifier":
                    command.extend(["--epochs", str(settings.epochs)])
                with jobs_lock:
                    if jobs[job_id]["status"] == "stopping":
                        jobs[job_id]["status"] = "cancelled"
                        jobs[job_id]["phase"] = "finished"
                        persist(jobs[job_id])
                        return
                    process = subprocess.Popen(
                        command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                        encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
                    )
                    processes[job_id] = process
                    jobs[job_id]["phase"] = "training"
                    persist(jobs[job_id])
                return_code = process.wait()
            with jobs_lock:
                stopped = jobs[job_id]["status"] == "stopping"
            checkpoint = model_dir / ("model.ckpt" if settings.model == "patchcore" else "weights/best.pt")
            if stopped:
                update_job(job_id, status="cancelled", phase="finished", return_code=return_code)
            elif return_code != 0:
                update_job(job_id, status="failed", phase="finished", return_code=return_code, error="训练失败，请查看日志")
            elif not checkpoint.is_file():
                raise RuntimeError("训练进程退出，但未找到预期模型文件")
            else:
                update_job(job_id, status="succeeded", phase="finished", checkpoint=checkpoint.relative_to(directory).as_posix(), return_code=0)
        except Exception as error:
            with (directory / "run.log").open("a", encoding="utf-8") as log:
                log.write(f"\n任务失败：{type(error).__name__}: {error}\n")
            with jobs_lock:
                stopped = jobs[job_id]["status"] == "stopping"
            update_job(job_id, status="cancelled" if stopped else "failed", phase="finished", error=str(error))
        finally:
            with jobs_lock:
                processes.pop(job_id, None)

    @asynccontextmanager
    async def lifespan(app):
        yield
        with jobs_lock:
            for job_id, job in jobs.items():
                if job["status"] == "running":
                    job["status"] = "stopping"
                    persist(job)
            for process in processes.values():
                if process.poll() is None:
                    process.terminate()
        for thread in threads:
            thread.join(timeout=10)

    app = FastAPI(title="刀具视觉工作台", lifespan=lifespan)
    app.state.workspace = workspace
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "请从本机工作台页面发起操作"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def file_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    def camera_command(settings, output=None):
        if not camera_lock.acquire(blocking=False):
            raise HTTPException(409, "相机正在采集，请稍后再试")
        try:
            command = [sys.executable, str(ROOT / "camera.py"), "--sdk-root", settings.sdk_root]
            if output is None:
                command.append("--list")
            else:
                command.extend(["--sn", settings.sn, "--output", str(output), "--packet-delay", str(settings.packet_delay)])
            try:
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            except subprocess.TimeoutExpired as error:
                raise HTTPException(504, "相机操作超时，请检查设备连接与占用情况") from error
            if result.returncode:
                raise HTTPException(503, result.stderr.strip() or result.stdout.strip())
            return result.stdout
        finally:
            camera_lock.release()

    @app.get("/api/state")
    def state():
        return workspace.state()

    @app.post("/api/import")
    def import_images():
        return {"imported": workspace.import_pilot()}

    @app.put("/api/specimens")
    def save_specimen(settings: SpecimenSettings):
        workspace.save_specimen(**settings.model_dump())
        return {"saved": True}

    @app.patch("/api/images/{image_id}")
    def update_image(image_id: str, settings: ImageSettings):
        workspace.update_image(image_id, settings.included, [box.model_dump() for box in settings.boxes])
        return {"saved": True}

    @app.get("/api/images/{image_id}/file")
    def image_file(image_id: str):
        return FileResponse(workspace.image_path(image_id), headers={"Cache-Control": "no-cache"})

    @app.post("/api/camera/devices")
    def devices(settings: CameraSettings):
        return json.loads(camera_command(settings))

    @app.post("/api/camera/preview")
    def preview(settings: CameraSettings):
        preview_root.mkdir(parents=True, exist_ok=True)
        path = preview_root / f"{uuid4().hex}.png"
        try:
            camera_command(settings, path)
            return Response(path.read_bytes(), media_type="image/png", headers={"Cache-Control": "no-store"})
        finally:
            path.unlink(missing_ok=True)

    @app.post("/api/camera/capture")
    def capture(settings: CaptureSettings):
        workspace.ensure_specimen(settings.tool_type, settings.specimen_id, settings.quality)
        name = f"top_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:6]}.png"
        path = root / "data/raw/pilot" / settings.tool_type / settings.specimen_id / name
        camera_command(settings, path)
        image_id, _ = workspace.add_image(path, settings.tool_type, settings.specimen_id)
        return {"id": image_id, "path": path.relative_to(root).as_posix()}

    @app.get("/api/dataset")
    def dataset(tool_type: str, model: Literal["patchcore", "classifier"] = "patchcore"):
        plan = workspace.plan(tool_type, model)
        return {key: value for key, value in plan.items() if key != "images"}

    @app.get("/api/jobs")
    def list_jobs():
        with jobs_lock:
            return json.loads(json.dumps(sorted(jobs.values(), key=lambda job: job["created_at"], reverse=True)))

    @app.post("/api/jobs")
    def start_job(settings: TrainSettings):
        plan = workspace.plan(settings.tool_type, settings.model)
        if not plan["ready"]:
            raise HTTPException(422, "；".join(plan["issues"]))
        if settings.roi is not None:
            left, top, right, bottom = settings.roi
            if any(not (0 <= left < right <= image["width"] and 0 <= top < bottom <= image["height"]) for image in plan["images"]):
                raise HTTPException(422, "统一 ROI 超出部分图片范围或尺寸无效")
        plan["model"] = settings.model
        with jobs_lock:
            if any(job["status"] in {"running", "stopping"} for job in jobs.values()):
                raise HTTPException(409, "已有训练任务运行，请等待完成或先停止")
            job_id = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid4().hex[:6]
            job = {"id": job_id, "status": "running", "phase": "preparing", "created_at": datetime.now().isoformat(timespec="seconds"),
                   "tool_type": settings.tool_type, "model": settings.model, "device": settings.device, "image_count": len(plan["images"]),
                   "error": "", "checkpoint": None}
            jobs[job_id] = job
            persist(job)
            thread = threading.Thread(target=run_job, args=(job_id, plan, settings), daemon=True)
            threads.append(thread)
            thread.start()
            return dict(job)

    def known_job(job_id):
        with jobs_lock:
            if job_id not in jobs:
                raise HTTPException(404, "训练任务不存在")
            return dict(jobs[job_id])

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str):
        known_job(job_id)
        path = job_root / job_id / "run.log"
        if not path.exists():
            return {"text": "正在准备数据…"}
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 64000))
            content = stream.read().decode("utf-8", errors="replace")
        return {"text": content}

    @app.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str):
        known_job(job_id)
        with jobs_lock:
            if jobs[job_id]["status"] in {"running", "stopping"}:
                jobs[job_id]["status"] = "stopping"
                persist(jobs[job_id])
                process = processes.get(job_id)
                if process and process.poll() is None:
                    process.terminate()
        return {"stopping": True}

    @app.get("/api/jobs/{job_id}/artifact")
    def artifact(job_id: str, name: str):
        job = known_job(job_id)
        if name not in {"manifest.json", "run.log", job["checkpoint"]}:
            raise HTTPException(404, "文件不存在")
        path = job_root / job_id / name
        if not path.is_file():
            raise HTTPException(404, "文件尚未生成")
        return FileResponse(path, filename=path.name)

    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "web/index.html")

    return app


def main():
    parser = argparse.ArgumentParser(description="本机刀具视觉工作台：拍摄、标注与训练")
    parser.add_argument("--port", type=int, default=8765, help="本机监听端口，默认 8765")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1～65535 之间")
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
