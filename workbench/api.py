import argparse
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4
from zipfile import ZipFile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from .camera import DEFAULT_SDK_ROOT
from .camera_session import CameraSession
from .jobs import Jobs
from .jobs import GETI_PROJECT
from .alignment import VERSION, align
from .store import Workspace, component


ROOT = Path(__file__).resolve().parent.parent


class CameraSettings(BaseModel):
    sn: str = Field(default="GL0180040948", min_length=1, max_length=80)
    packet_delay: int = Field(default=20000, ge=0, le=1000000)
    sdk_root: Path = DEFAULT_SDK_ROOT


class SpecimenSettings(BaseModel):
    tool_type: str
    specimen_id: str
    quality: Literal["good", "defect", "unknown"] = "unknown"
    split: Literal["unassigned", "train", "val", "test"] = "unassigned"
    category: str = ""


class CaptureSettings(BaseModel):
    tool_type: str
    specimen_id: str
    quality: Literal["good", "defect", "unknown"] = "unknown"
    view: str = "top"


class ImageSettings(BaseModel):
    included: bool | None = None
    quality: Literal["good", "defect", "unknown"] | None = None
    annotated: bool | None = None
    view: Literal["top", "bottom"] | None = None
    boxes: list["DefectBox"] | None = None


class DefectBox(BaseModel):
    x: float = Field(ge=0, allow_inf_nan=False)
    y: float = Field(ge=0, allow_inf_nan=False)
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)
    label: Literal["磨损", "缺角", "划痕", "氧化"]


class RecipeSettings(BaseModel):
    tool_type: str
    view: str = "top"
    roi: tuple[int, int, int, int] | None = None


class TrainSettings(RecipeSettings):
    model: Literal["patchcore", "detector"] = "patchcore"
    experimental: bool = True
    device: Literal["cuda", "cpu"] = "cuda"
    batch_size: int = Field(default=4, ge=1, le=64)
    epochs: int = Field(default=30, ge=1, le=1000)


class DetectSettings(BaseModel):
    route_tool: str | None = None
    route_view: Literal["top", "bottom"] | None = None
    device: Literal["cuda", "cpu"] = "cuda"
    min_confidence: float = Field(default=0.5, ge=0, le=1)
    image_id: str | None = None
    camera: bool = False


class ReviewSettings(BaseModel):
    quality: Literal["good", "defect", "unknown"]
    note: str = Field(default="", max_length=500)
    boxes: list[DefectBox] = Field(default_factory=list)
    tool_type: str | None = None
    view: Literal["top", "bottom"] | None = None


class SchemeSettings(BaseModel):
    tool_type: str
    view: Literal["top", "bottom"]
    anomaly_job: str
    detector_job: str | None = None


def create_app(root=ROOT):
    root = Path(root).resolve()
    workspace = Workspace(root)
    camera = CameraSession()
    jobs = Jobs(root, workspace)

    @asynccontextmanager
    async def lifespan(app):
        yield
        try:
            jobs.close()
        finally:
            camera.disconnect()

    app = FastAPI(title="刀具视觉工作台", lifespan=lifespan)
    app.state.workspace, app.state.camera, app.state.jobs = workspace, camera, jobs
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

    @app.exception_handler(UnidentifiedImageError)
    async def image_error(request, error):
        return JSONResponse({"detail": "无法读取图片，请选择 PNG、JPEG、BMP 或 TIFF 图片"}, status_code=422)

    @app.exception_handler(FileNotFoundError)
    async def file_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(RuntimeError)
    async def runtime_error(request, error):
        return JSONResponse({"detail": str(error)}, status_code=503)

    @app.get("/api/state")
    def state():
        return {**workspace.state(), "geti_ready": (GETI_PROJECT / ".venv/Scripts/python.exe").is_file()}

    @app.post("/api/import")
    def import_images():
        return {"imported": workspace.import_pilot()}

    @app.put("/api/specimens")
    def save_specimen(settings: SpecimenSettings):
        workspace.save_specimen(**settings.model_dump())
        return {"saved": True}

    @app.patch("/api/images/{image_id}")
    def update_image(image_id: str, settings: ImageSettings):
        workspace.update_image(image_id, **settings.model_dump(exclude_none=True))
        return {"saved": True}

    @app.get("/api/images/{image_id}/file")
    def image_file(image_id: str):
        return FileResponse(workspace.image_path(image_id))

    @app.get("/api/images/{image_id}/aligned")
    def aligned_image(image_id: str):
        with Image.open(workspace.image_path(image_id)) as source:
            prepared, _ = align(source)
        output = BytesIO()
        prepared.save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png")

    async def uploaded_image(request):
        body = await request.body()
        if len(body) > 25 * 1024 * 1024:
            raise ValueError("每张图片不能超过 25 MB")
        with Image.open(BytesIO(body)) as image:
            return ImageOps.exif_transpose(image).convert("RGB")

    def register_image(image, settings):
        component(settings.view)
        workspace.ensure_specimen(settings.tool_type, settings.specimen_id, settings.quality)
        name = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.png"
        path = root / "data/raw/pilot" / settings.tool_type / settings.specimen_id / settings.view / name
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path)
        image_id, _ = workspace.add_image(path, settings.tool_type, settings.specimen_id, settings.view)
        return {"id": image_id, "path": path.relative_to(root).as_posix()}

    @app.post("/api/images/upload")
    async def upload(request: Request, tool_type: str, specimen_id: str, quality: Literal["good", "defect", "unknown"], view: str = "top"):
        settings = CaptureSettings(tool_type=tool_type, specimen_id=specimen_id, quality=quality, view=view)
        return register_image(await uploaded_image(request), settings)

    @app.get("/api/camera/status")
    def camera_status():
        return camera.status()

    @app.post("/api/camera/connect")
    def connect_camera(settings: CameraSettings):
        try:
            return camera.connect(settings.sn, settings.sdk_root, settings.packet_delay)
        except ValueError:
            raise
        except Exception as error:
            raise HTTPException(503, f"连接失败：{error}") from error

    @app.post("/api/camera/disconnect")
    def disconnect_camera():
        return camera.disconnect()

    @app.post("/api/camera/preview")
    def preview():
        output = BytesIO()
        camera.capture().save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/camera/live")
    def live_preview():
        if not camera.status()["connected"]:
            raise ValueError("请先连接相机")

        def frames():
            sequence = 0
            while camera.status()["connected"]:
                try:
                    sequence, jpeg = camera.next_preview(sequence)
                except ValueError:
                    if not camera.status()["connected"]:
                        break
                    raise
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"

        return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/camera/capture")
    def capture(settings: CaptureSettings):
        component(settings.tool_type)
        component(settings.specimen_id)
        component(settings.view)
        return register_image(camera.capture(), settings)

    @app.get("/api/recipe")
    def recipe(tool_type: str, view: str = "top"):
        return workspace.recipe(tool_type, view)

    @app.put("/api/recipe")
    def save_recipe(settings: RecipeSettings):
        workspace.save_recipe(**settings.model_dump())
        return workspace.recipe(settings.tool_type, settings.view)

    @app.get("/api/dataset")
    def dataset(tool_type: str, model: Literal["patchcore", "detector"] = "patchcore", view: str = "top", experimental: bool = True):
        plan = workspace.plan(tool_type, model, view, experimental)
        return {key: value for key, value in plan.items() if key != "images"}

    @app.get("/api/jobs")
    def list_jobs():
        return jobs.list()

    @app.post("/api/jobs")
    def start_job(settings: TrainSettings):
        if settings.view not in {"top", "bottom"}:
            raise ValueError("请选择正面或背面")
        if settings.model == "detector" and not (GETI_PROJECT / ".venv/Scripts/python.exe").is_file():
            raise RuntimeError("Geti 环境尚未安装，请运行 uv sync --locked --project engines/geti")
        plan = workspace.plan(settings.tool_type, settings.model, settings.view, settings.experimental)
        if not plan["ready"]:
            raise ValueError("；".join(plan["issues"]))
        values = settings.model_dump(mode="json")
        values["preprocessing"] = VERSION
        plan["model"] = settings.model
        return jobs.start("train", values, plan=plan)

    @app.put("/api/schemes")
    def save_scheme(settings: SchemeSettings):
        for model_type, job_id in (("patchcore", settings.anomaly_job), ("detector", settings.detector_job)):
            if job_id:
                model = jobs.model(job_id, model_type)
                if (model["tool_type"], model["view"]) != (settings.tool_type, settings.view):
                    raise ValueError("模型类型和拍摄面与方案不匹配")
        workspace.save_scheme(**settings.model_dump())
        return {"saved": True}

    def detect(settings, image, source_item=None):
        schemes = workspace.state()["schemes"]
        if not schemes:
            raise ValueError("请先在模型页启用至少一个检测方案")
        if bool(settings.route_tool) != bool(settings.route_view):
            raise ValueError("人工指定需要同时选择刀具类型和拍摄面")
        for scheme in schemes:
            jobs.model(scheme["anomaly_job"], "patchcore")
            if scheme["detector_job"]:
                jobs.model(scheme["detector_job"], "detector")
        values = {**settings.model_dump(mode="json"), "model": "scheme", "schemes": schemes,
                  "preprocessing": VERSION, "source_item": source_item,
                  "camera_info": camera.status() if settings.camera else None}
        return jobs.start("detect", values, image=image)

    @app.post("/api/detections")
    def detect_image(settings: DetectSettings):
        if settings.camera == bool(settings.image_id):
            raise ValueError("请选择一张样本图片或相机拍照")
        if settings.camera:
            return detect(settings, camera.capture())
        workspace.image_path(settings.image_id)
        item = next(item for item in workspace.state()["images"] if item["id"] == settings.image_id)
        with Image.open(workspace.image_path(settings.image_id)) as image:
            return detect(settings, image.copy(), item)

    @app.post("/api/detections/upload")
    async def detect_upload(request: Request, route_tool: str | None = None, route_view: Literal["top", "bottom"] | None = None,
                            device: Literal["cuda", "cpu"] = "cuda", min_confidence: float = 0.5):
        settings = DetectSettings(route_tool=route_tool, route_view=route_view, device=device, min_confidence=min_confidence)
        return detect(settings, await uploaded_image(request))

    @app.post("/api/jobs/{job_id}/review")
    def review(job_id: str, settings: ReviewSettings):
        job = jobs.get(job_id)
        if job.get("kind") != "detect" or job["status"] != "succeeded":
            raise ValueError("请选择已完成的检测结果")
        image_path = jobs.root / job_id / "source.png"
        with Image.open(image_path) as image:
            for box in settings.boxes:
                if box.x + box.width > image.width or box.y + box.height > image.height:
                    raise ValueError("复核缺陷框超出原图")
        if settings.quality == "good" and settings.boxes:
            raise ValueError("合格复核不能保留缺陷框")
        review = {**settings.model_dump(mode="json"), "at": datetime.now().isoformat(timespec="seconds")}
        reviews = [*job.get("reviews", []), review]
        jobs.update(job_id, review=review, reviews=reviews)
        (jobs.root / job_id / "result.json").write_text(
            json.dumps({**job["result"], "review": review, "reviews": reviews}, ensure_ascii=False, indent=2), encoding="utf-8")
        return jobs.get(job_id)

    @app.post("/api/jobs/{job_id}/adopt")
    def adopt_detection(job_id: str, settings: CaptureSettings):
        job = jobs.get(job_id)
        if job["kind"] != "detect" or job["status"] != "succeeded" or not job.get("review"):
            raise ValueError("请先完成人工复核")
        if job.get("adopted_image"):
            raise ValueError("该记录已加入样本")
        review = job["review"]
        if review["quality"] == "unknown" or (review["quality"] == "defect" and not review["boxes"]):
            raise ValueError("请确认当前面好坏，并框出不合格区域")
        if review.get("tool_type") != settings.tool_type or review.get("view") != settings.view:
            raise ValueError("采纳类型和拍摄面应与人工复核一致")
        with Image.open(jobs.root / job_id / "source.png") as source:
            registered = register_image(source.copy(), settings)
        workspace.update_image(registered["id"], included=True, quality=review["quality"], boxes=review["boxes"], annotated=True)
        jobs.update(job_id, adopted_image=registered["id"])
        return registered

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str):
        jobs.get(job_id)
        path = jobs.root / job_id / "run.log"
        if not path.exists():
            return {"text": "正在准备数据…"}
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 64000))
            return {"text": stream.read().decode("utf-8", errors="replace")}

    @app.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str):
        jobs.stop(job_id)
        return jobs.get(job_id)

    @app.get("/api/jobs/{job_id}/artifact")
    def artifact(job_id: str, name: str):
        job = jobs.get(job_id)
        if name == "record.zip":
            if job["kind"] != "detect" or job["status"] != "succeeded":
                raise ValueError("请选择已完成的检测记录")
            output = BytesIO()
            with ZipFile(output, "w") as archive:
                for entry in (jobs.root / job_id).iterdir():
                    if entry.is_file() and entry.suffix in {".json", ".png", ".log"}:
                        archive.write(entry, entry.name)
            return Response(output.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{job_id}.zip"'})
        if name == "model.zip":
            jobs.model(job_id, job["model"])
            path = jobs.root / job_id / name
            with jobs.lock:
                if not path.exists():
                    checkpoint = jobs.root / job_id / job["checkpoint"]
                    with ZipFile(path, "w") as archive:
                        archive.write(checkpoint, checkpoint.name)
                        metadata = checkpoint.with_name("model.json")
                        if metadata.exists():
                            archive.write(metadata, metadata.name)
                        archive.write(jobs.root / job_id / "reference.png", "reference.png")
                        archive.write(jobs.root / job_id / "manifest.json", "manifest.json")
            return FileResponse(path, filename=f"{job_id}-{job['model']}.zip")
        if name not in {"manifest.json", "run.log", "source.png", "input.png", "aligned.png", "heatmap.png", "reference.png",
                        "transform.json", "detector-transform.json", "detector-input.png", "predictions/input.heatmap.png", "result.json", job["checkpoint"]}:
            raise FileNotFoundError("文件不存在")
        path = jobs.root / job_id / name
        if not path.is_file():
            raise FileNotFoundError("文件尚未生成")
        return FileResponse(path, filename=path.name)

    app.mount("/assets", StaticFiles(directory=ROOT / "web/dist/assets", check_dir=False), name="assets")

    @app.get("/")
    def index():
        path = ROOT / "web/dist/index.html"
        if not path.exists():
            raise HTTPException(503, "前端尚未构建，请在 web 目录运行 pnpm install 和 pnpm build")
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    return app


def main():
    parser = argparse.ArgumentParser(description="本机刀具视觉工作台：采集、训练与检测")
    parser.add_argument("--port", type=int, default=8765, help="本机监听端口，默认 8765")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1～65535 之间")
    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
