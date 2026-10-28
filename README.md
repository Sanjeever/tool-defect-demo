# 刀具视觉工作台

在本机浏览器中采集刀具图片、整理样本、训练模型并检测单张图片。
后端使用 Python、FastAPI 和 uv，前端使用 React、Vite、Tailwind CSS 和 HeroUI。
Anomalib PatchCore 输出异常分数与热力图，YOLO 分类模型识别人工确认的已知缺陷类型。

目前有 7 对刀具，每对一好一坏。现有样品可用于拍摄和模型实验，对新刀具的检测效果尚未验证。
同一把刀具重复拍照不能增加独立实物数量，也不能据此评价生产检测准确率。

**启动**

环境为 Windows x64、Python 3.11、Node.js 22.17+、pnpm 11。
在 PowerShell 中运行：

```powershell
Set-Location D:\code\python\tool-defect-demo
uv sync --locked
Set-Location web
pnpm install --frozen-lockfile
pnpm build
Set-Location ..
uv run python app.py
```

打开 <http://127.0.0.1:8765>。前端构建完成后，日常启动运行 `uv run python app.py` 即可。
需要更换端口时使用 `uv run python app.py --port 8766`。
在启动终端按 Ctrl+C 退出，服务会停止自己的模型任务并释放已连接相机。

**第一次操作**

1. 选一对缺陷明显的刀具，固定相机、照明、背景、摆放位置及拍摄面。
2. 在 GalaxyView 中停止采集并关闭设备，释放相机控制权；工作台不会结束 GalaxyView 进程。
3. 在网页点击“连接相机”，再点击“刷新预览”或“连续预览”。先确认缺陷在工业相机原图中清晰可见。
4. 型号可先用 `type_01`，拍摄面用 `top`。好件实物编号用 `good_01`，坏件用 `bad_01`，分别确认好坏标签。
5. 每件先拍约 20～30 张，每次取下再放回，覆盖日常摆放变化。不要把同一把刀具换个编号当成新实物。
6. 在样本区剔除模糊、拍错面、缺陷出画面的图片，勾选可用图片。已有采集目录可点击“扫描已有图片”登记。
7. 在“实物分组”把好件设为“训练”并保存。当前样品量先选择“模型 → PatchCore · 未校准实验”建库。
8. 建库成功后进入“检测”，选择异常模型，再检测好件和坏件图片，查看分数与热力图，填写人工复核。

实物标签和训练／验证／测试分组跨拍摄面共用。样本筛选与检测区域按型号、拍摄面分别设置。
新拍摄或导入图片默认未选入数据集，原图不会被预处理结果覆盖。
第一版按单件、单面检测，照片中看不见的侧面或背面缺陷不在该次检测范围内。

**三种训练方式**

| 方式 | 数据条件 | 输出与限制 |
| --- | --- | --- |
| PatchCore · 未校准实验 | 至少有已选入的正常训练图片 | 建立正常特征库；输出原始异常分数和热力图，标签为“未校准”，不触发分类 |
| PatchCore · 阈值校准 | 正常训练实物，以及不同实物的正常、异常验证图片 | 使用验证集校准正常／异常阈值；仍需独立测试实物评价漏检和误报 |
| YOLO · 缺陷分类 | 至少两个真实缺陷类别，训练与验证每类使用不同实物 | 只用坏件图片训练类别；刀具型号不作为缺陷类别 |

同一实物的连拍、裁剪和增强图必须属于同一分组。验证集用于调阈值，测试集用于最终评价。
当前每种一好一坏无法满足完整的独立训练、验证、测试要求，需要补充不同实物。
工作台训练不会自动执行独立测试，离线测试命令见下文。

检测区域可在参考图上拖动框选，也可以填写原图像素坐标；右、下边界不包含在区域内。
预处理统一为灰度三通道、等比例缩放和黑色补边，输入尺寸为 256×256。
这个尺寸用于初步实验，细小缺陷是否保留需查看“模型输入”。更改检测区域后需重新训练。
旧模型检测始终使用训练快照中的区域与原图尺寸，避免后续配置改变模型输入。

校准模型判为异常后，才会调用所选 YOLO 分类模型。两个模型的型号、拍摄面、原图尺寸和检测区域必须一致。
分类置信度门槛默认 0.7，是需要验证的初始值。低于门槛或未选择分类模型时，异常交由人工复核。
高分类置信度不能保证识别未知缺陷。PatchCore 漏掉的缺陷不会进入分类环节。
异常分数不等于缺陷概率；未校准热力图按单张图数值范围显示颜色，跨图颜色深浅不能直接比较。

**相机与环境**

- 相机为 Daheng MER-132-30GM，SN `GL0180040948`，当前 IP `192.168.0.22`。
- 厂商 SDK 从 `C:\Program Files\Daheng Imaging\GalaxySDK` 加载，`GalaxyView.exe` 是调试软件。
- 启动服务或打开网页不会连接相机。点击“连接相机”后才打开设备，预览和拍照使用 Mono8 软件触发。
- 连续预览按顺序采图，适合调整摆放，帧率受触发和曝光影响。预览图不作为样本自动保存。
- 断开或正常退出时恢复触发模式、触发源、像素格式及 GigE 包间隔；不修改曝光、增益和网络配置。
- 保留 NumPy 1.26.4、OpenCV headless 4.11、PyTorch 2.6／torchvision 0.21 CUDA 12.4 的兼容组合。
- 本机 GTX 1650 Ti 4GB，训练默认批量为 4；显存不足可改为 1。CPU 需显式选择，不会自动切换。
- 首次训练可能下载预训练权重；这些通用权重不包含你的刀具缺陷知识。

**文件位置**

```text
app.py                    工作台启动入口
check_env.py              依赖、CUDA、可选 SDK 导入检查
workbench/                后端、相机会话、模型与图像预处理
web/src/                  React 界面
tests/                    存储、API、预处理与相机会话检查
data/raw/pilot/            型号/实物编号/拍摄面/原图.png
data/web/workspace.sqlite3 样本标签、实物分组与检测区域
outputs/web/jobs/         每次任务的数据快照、模型、日志和检测结果
```

旧的“型号/实物编号/原图”目录扫描后默认归入 `top`，现有图片、分组和旧矩形标注会保留。
训练与检测同一时间运行一个任务，可在任务日志中停止。重启后，未完成任务标为“已中断”，需重新运行。
检测原图、模型输入、热力图和结果 JSON 保存在任务目录；人工复核与模型预测分别记录。
下载模型会得到包含权重、数据清单及 PatchCore 模式元数据的 ZIP，解压后保留这些文件在同一目录。
图片、模型、数据库、结果、依赖目录和构建产物均不提交 Git。

**开发与验证**

```powershell
uv run python -m unittest discover -s tests -v
uv run python check_env.py --check-sdk
Set-Location web
pnpm build
pnpm dev
```

开发时另一个终端运行 `uv run python app.py`，Vite 默认在 <http://127.0.0.1:5173>，代理 API 到 8765。
项目检查不会自动打开相机。相机 SDK 生命周期的自动化检查使用 mock，不能替代实物采图验证。

以下入口用于需要时的离线操作，各命令支持 `--help`：

```powershell
uv run python -m workbench.camera --help
uv run python -m workbench.preprocessing --help
uv run python -m workbench.anomaly train --help
uv run python -m workbench.anomaly test --help
uv run python -m workbench.classifier train --help
uv run python -m workbench.classifier test --help
```

离线异常数据采用 `train/good`、`val/good`、`val/defect`、`test/good`、`test/defect`，输入需经过相同预处理。
分类数据采用 `train/类别`、`val/类别`、`test/类别`。使用训练时的任务快照或相同处理设置。

```powershell
uv run python -m workbench.anomaly test --data outputs/web/jobs/训练任务编号/prepared --checkpoint outputs/web/jobs/训练任务编号/patchcore/model.ckpt --output outputs/独立异常测试
uv run python -m workbench.classifier test --data outputs/web/jobs/训练任务编号/prepared --checkpoint outputs/web/jobs/训练任务编号/classifier/weights/best.pt --output outputs/独立分类测试
```

上述测试需要任务数据中确实包含独立测试实物。未校准实验模型不能用于正式指标测试。
软件流程已使用临时生成图验证训练、重载、推理和串联分类；这些结果不代表真实刀具检测效果。
真实相机在新工作台内的连接、持续预览、单张采集，以及真实刀具检测效果仍需实机验证。
