# 刀具缺陷检测实验

使用 Anomalib PatchCore 判断刀具正常／异常并生成热力图，使用 YOLO 分类模型识别已知缺陷类型。
从离线图片开始，再接入大恒工业相机单张采集。

仓库提供环境配置和可执行入口，不附带刀具图片或训练权重。初始化时尚未收到刀具样本，
刀具类型、缺陷类别、检测区域和合格阈值均未确定，尚无真实刀具检测效果结论。

## 环境准备

当前配置面向 Windows x64、Python 3.11、NVIDIA 显卡，使用 uv 管理环境。
本机配置为 GTX 1650 Ti 4GB、约 32GB 内存，显卡驱动 552.12。

在 PowerShell 中运行：

```powershell
Set-Location D:\code\python\tool-defect-demo
uv sync --locked
uv run python check_env.py
```

首次同步会下载 Python 及依赖，PyTorch CUDA 包约 2.4GB，请预留下载和解压空间。
无需手动激活虚拟环境。环境检查会导入模型入口并实际执行一次矩阵运算，不下载权重、不训练模型。

主要依赖：

| 组件 | 配置 |
| --- | --- |
| Python | 3.11 |
| Anomalib | 2.7.0 |
| PyTorch／torchvision | 2.6.0／0.21.0，CUDA 12.4 构建 |
| Ultralytics | `ultralytics-opencv-headless` 8.4.190 |
| NumPy | 1.26.4，本机 `gxipy` 依赖 NumPy 1.x 接口 |

YOLO 使用官方 headless 发行包，Python 导入仍为 `from ultralytics import YOLO`。
本项目保存图片和结果文件，不依赖 OpenCV 弹窗。不要再安装 `opencv-python`，以免覆盖共享的 `cv2` 文件。
依赖的完整版本记录在 `uv.lock` 中。
OpenCV 和 imagecodecs 也固定为兼容 NumPy 1.x 的版本，避免 SDK 导入失败。

没有可用 GPU 时，可以显式使用 CPU：

```powershell
uv run python check_env.py --device cpu
```

各模型入口也支持 `--device cpu`。当前锁文件仍安装 CUDA 版 PyTorch，选择 CPU 运算不会减少下载体积。

## 项目入口

| 文件 | 用途 |
| --- | --- |
| `check_env.py` | 检查依赖、CUDA 运算及可选 SDK 导入 |
| `camera.py` | 枚举相机，按 SN 采集一张灰度 PNG |
| `prepare_images.py` | 裁剪 ROI、等比例缩放、补边并转换为 RGB PNG |
| `anomaly.py` | PatchCore 训练、独立测试、图片检测及可选缺陷分类 |
| `classifier.py` | YOLO 分类训练、独立测试与单图分类 |
| `tests/` | 图像预处理回归检查 |
| `data/` | 本地样本，Git 中保留空目录 |
| `outputs/` | 运行时生成的模型、指标和检测结果 |

每个入口及模型子命令都支持 `--help`，例如：

```powershell
uv run python anomaly.py train --help
uv run python classifier.py train --help
```

## 1. 准备图片

先选择一种刀具和一个固定视角。固定相机、刀具位置、光源、曝光及增益，确认原图能清楚呈现目标缺陷。
可以先用 GalaxyView 保存无损图片，再进行离线实验。

按实际刀具划分数据，同一把刀具的连拍、裁剪和增强图归入同一组。
`train` 用于建模，`val` 用于校准阈值，`test` 用于最终评估。不要把测试集用于调参。

将原图按以下结构整理到 `data/raw/anomaly/`：

```text
data/raw/anomaly/
├── train/
│   └── good/       正常训练图
├── val/
│   ├── good/       正常验证图
│   └── defect/     缺陷验证图
└── test/
    ├── good/       正常测试图
    └── defect/     缺陷测试图
```

每个目录都需要真实图片。第一版不要求逐像素标注，支持 PNG、JPEG、BMP、TIFF。

生成模型输入：

```powershell
uv run python prepare_images.py --source data/raw/anomaly --output data/anomaly
```

有明确检测区域后，通过 `--roi 左 上 右 下` 裁剪，单位为原图像素。
以下数字仅演示参数格式，执行前换成实际坐标：

```powershell
uv run python prepare_images.py --source data/raw/anomaly --output data/anomaly-roi --roi 100 100 700 500
```

右、下边界不包含在裁剪结果中。图片统一转换成三通道 RGB，灰度图复制为三个相同通道；
等比例缩放后用黑色补边为 256×256，保留输入目录结构。原图不会被覆盖，已存在的输出图片也不会覆盖。
变更 ROI 后使用新的数据输出目录，并重新训练。

当前模型入口要求输入为已处理的 256×256 图片。这个尺寸用于跑通流程，是否足以保留细小缺陷需要实图验证。
训练、验证、测试和新图检测必须使用同样的 ROI 与预处理设置。

## 2. 训练并验证 PatchCore

```powershell
uv run python anomaly.py train --data data/anomaly --output outputs/patchcore
```

默认使用 ResNet18 特征提取器、批量大小 4、特征库采样比例 0.01，作为 4GB 显存的起点。
首次训练会联网下载预训练特征提取器权重。
PatchCore 收集正常图的特征，不通过多轮反向传播训练；增加训练轮数不是当前入口的调优方式。

训练读取 `train/good` 建立正常特征库，使用 `val/good` 和 `val/defect` 校准异常阈值。
程序通过 Anomalib `Folder` 的 `same_as_test` 模式把这两个验证目录接入验证流程；
训练命令不会读取磁盘上的 `test/`。模型与校准参数保存在 `outputs/patchcore/model.ckpt`。

在独立测试集上评价：

```powershell
uv run python anomaly.py test --data data/anomaly --checkpoint outputs/patchcore/model.ckpt
```

图像级 AUROC、F1 等指标写入 `outputs/test/metrics.json`。
未提供像素掩码时，不能据此声称像素级缺陷定位准确率。
样本少时还应逐张查看结果，统计漏检和误报。

显存不足时先将训练批量降为 1，仍需根据实际图片数量和运行结果调整：

```powershell
uv run python anomaly.py train --data data/anomaly --output outputs/patchcore-small --batch-size 1
```

## 3. 检测新图片

把新原图放入 `data/raw/incoming/`，按训练时相同的设置处理：

```powershell
uv run python prepare_images.py --source data/raw/incoming --output data/incoming
uv run python anomaly.py predict --checkpoint outputs/patchcore/model.ckpt --source data/incoming --output outputs/predictions
```

输出目录包含每张图片的热力图叠加图和 `results.jsonl`，每行对应一张图片，包含路径、正常／异常标签和异常分数。
异常分数不等于缺陷概率。热力图用于检查模型关注的位置，缺少像素标注时仍需人工核对。
再次实验时指定新的 `--output`，避免覆盖已有结果。

## 4. 接入大恒相机

当前目标相机为 MER-132-30GM，SN 为 `GL0180040948`，IP 为 `192.168.0.22`。
默认读取以下本机 SDK，不通过 PyPI 安装同名 `gxipy`：

```text
C:\Program Files\Daheng Imaging\GalaxySDK
```

先检查 SDK 能否导入，再枚举设备：

```powershell
uv run python check_env.py --check-sdk
uv run python camera.py --list
```

枚举不会打开相机。采集前在 GalaxyView 中停止采集并关闭该设备，释放控制权。
运行以下命令保存一张图片：

```powershell
uv run python camera.py --sn GL0180040948 --output data/raw/incoming/tool-001.png
```

采集时暂时关闭触发、使用 Mono8，结束时恢复原触发模式和像素格式并释放设备。
不会修改曝光、增益、IP 或网关。GalaxySDK 安装位置不同时，用 `--sdk-root` 指定路径。
保存图片后，按照上一节预处理并检测。

## 5. 按已知缺陷类型分类

这一阶段需要真实缺陷类别和对应图片。YOLO 分类给整张 ROI 图片一个类别；
一张图存在多种缺陷、需要分别定位时，应另行设计目标检测或多标签任务。

将分类原图放入 `data/raw/classification/`，目录格式如下。
`class_a`、`class_b` 是结构示例，需替换为真实类别名称：

```text
data/raw/classification/
├── train/
│   ├── class_a/
│   └── class_b/
├── val/
│   ├── class_a/
│   └── class_b/
└── test/
    ├── class_a/
    └── class_b/
```

先使用相同 ROI 预处理，再训练。首次训练会下载 YOLO26n 分类预训练权重：

```powershell
uv run python prepare_images.py --source data/raw/classification --output data/classification
uv run python classifier.py train --data data/classification --epochs 30
uv run python classifier.py test --data data/classification --checkpoint outputs/classifier/weights/best.pt
```

为保留刀尖和刃口，输入先补边为方形，分类训练关闭随机缩放裁剪、翻转、擦除和颜色增强。
本机 GTX 1650 Ti 未通过 Ultralytics 的混合精度检查，训练显式关闭 AMP，使用单精度运算。
得到真实数据后，再决定哪些增强符合拍摄条件。

单张异常图分类：

```powershell
uv run python classifier.py predict --checkpoint outputs/classifier/weights/best.pt --source data/incoming/tool-001.png
```

将两个模型串联，仅对 PatchCore 判为异常的图片进行分类：

```powershell
uv run python anomaly.py predict --checkpoint outputs/patchcore/model.ckpt --source data/incoming --classifier outputs/classifier/weights/best.pt --output outputs/combined
```

分类置信度低于 `--min-confidence` 时输出“异常待复核”。默认值 0.7 是初始参数，需要用验证集调整，
不能据此保证未知缺陷识别。分类器可能对未知缺陷给出高置信度；PatchCore 漏掉的缺陷也不会进入分类环节。
串联流程需要单独评价整体漏检和分类结果。

## 开发检查

```powershell
uv run python -m unittest discover -s tests -v
uv run python check_env.py --check-sdk
```

预处理检查使用临时生成的图片，验证 ROI、补边、灰度转换及文件保护，不代表刀具检测效果。
真实训练、测试和采集应分别记录实际结果。

初始化时已在本机通过以下验证：

- 依赖兼容性检查、CUDA 矩阵运算、Anomalib／YOLO／GalaxySDK 导入。
- 6 项图像预处理检查。
- 枚举到 MER-132-30GM，SN 为 `GL0180040948`。
- 临时生成图片上的 PatchCore 与 YOLO 训练、模型重载、测试、图片推理及串联分类流程。

临时图片用于检查软件流程，相关权重与结果不作为刀具模型交付。实际刀具检测效果尚未验证。
单张相机采集入口已提供，初始化时 GalaxyView 正在占用设备，因此未实测采图。

## 参考

- [Anomalib 入门](https://anomalib.readthedocs.io/en/stable/markdown/get_started/anomalib.html)
- [PatchCore](https://anomalib.readthedocs.io/en/stable/markdown/guides/reference/models/image/patchcore.html)
- [YOLO 图像分类](https://docs.ultralytics.com/tasks/classify/)
- [Ultralytics 安装与 headless 发行包](https://docs.ultralytics.com/quickstart/)
- [uv 与 PyTorch](https://docs.astral.sh/uv/guides/integration/pytorch/)
