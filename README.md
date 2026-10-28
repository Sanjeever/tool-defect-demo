# 刀具视觉工作台

本机采集、标注、训练和检测单把刀具。支持大恒 MER-132-30GM 工业相机与离线图片。
每张图片判断当前可见面，支持刀具在固定台面上移动、旋转和翻面。Anomalib PatchCore 输出异常分数与热力图，Geti / getitune YOLOX 输出磨损、缺角、划痕、氧化的缺陷框、类别和模型分数。

现有样本为 7 种刀具各一好一坏。当前阶段用于验证采集、标注和模型流程，对新刀具的漏检率、误报率、类型识别效果及合格阈值尚未验证。实验模型显示“未校准”，不输出合格结论。同一把刀具多次拍摄不等于增加独立实物。

## 安装与启动

Windows x64、Python 3.11、uv、Node.js 22.17+、pnpm。

```powershell
Set-Location D:\code\python\tool-defect-demo
uv sync --locked
uv sync --locked --project engines/geti
Set-Location web
pnpm install --frozen-lockfile
pnpm build
Set-Location ..
uv run python app.py
```

打开 <http://127.0.0.1:8765>。日常启动运行 `uv run python app.py`，需要其他端口时加 `--port 8766`。Ctrl+C 退出会停止本工作台的模型任务并释放已连接相机。

主环境保留 NumPy 1.26.4，供相机 SDK 和 Anomalib 使用。`engines/geti/` 使用单独的虚拟环境与锁文件，安装 getitune 0.1.3、NumPy 2.x。两边均使用 PyTorch 2.6 / torchvision 0.21 CUDA 12.4，已验证本机 GTX 1650 Ti 4GB 可运行。默认训练批量为 2；可在参数页调整，显存不足会报告错误。

首次训练会下载官方通用预训练权重。这些权重不包含本项目的刀具缺陷知识。

## 第一次使用

1. **样本 → 采集**：选择刀具类型和正面／背面，填写固定实物编号。实物好坏用于登记，照片的当前面好坏在标注时确认。连接相机前，先在 GalaxyView 中停止采集并关闭设备。也可批量导入已有图片。
2. **样本**：逐张确认当前面好坏。拖框后选择磨损、缺角、划痕或氧化，一张图可以标多处、多类。支持放大、拖动画面、更改类别、重画选中框和删除框。点击“确认并采用”。已标注照片也可“取消采用”。
3. **实物分组**：首次确认未分组实物时设为训练组。正反面、连拍和其他重复图片共用该实物的分组。验证、测试需要不同实物；已有分组不会被自动覆盖。
4. **模型 → 训练**：先训练 Anomalib 正常外观模型，再训练 Geti 缺陷区域模型。现有样本默认采用实验训练，完全不使用验证集，也不复制训练图片充当验证数据。Geti 可从一个已有标注的缺陷类别开始，只有训练组实际出现的类别才进入模型。
5. **模型 → 启用方案**：将同类型、同拍摄面的两个模型关联并启用。也可先启用 Anomalib，结果会明确显示尚未配置缺陷模型。方案可停用或替换版本。对每种刀具的正反面分别准备样本、训练并启用。
6. **检测**：放入一把刀具，点击“拍照检测”或导入一张图片。系统在已启用方案中匹配类型和拍摄面，再分别执行 Anomalib 和 Geti。结果显示原图缺陷框、类别与分数、原图热力图和对齐图。
7. **复核与记录**：人工修改类型、拍摄面、当前面结论和缺陷框，保存复核。填写实物编号后可把复核结果加入样本。原始预测与历次复核分别保留。记录支持按日期、类型、复核状态筛选，以及导出 ZIP。

未保存的标注需要保存或撤销后切换工作区。窄屏通过列表、画面和操作面板切换，样本、缺陷框、记录和日志分页。

## 采集与判断范围

- 固定相机、照明、工作距离，使用单一哑光背景。刀具平放，每次一把，允许在画面内移动和旋转。刀具出画、画面无明显刀具或有多个明显物体时，定位会失败并报告原因。
- 定位采用背景灰度差与轮廓。模型输入采用 `single-tool-crop-v2`，完成居中、裁剪和缩放，保留实际朝向。三角形等近似旋转对称刀片无法从外形可靠确定唯一方向，因此旋转参考图匹配仅用于类型／拍摄面候选评分，不再旋转模型输入。训练图片应覆盖实际摆放角度，旋转稳健性需要实测。
- 类型／拍摄面选择是实验参考匹配，不是经过独立测试的型号分类器。外形接近、正反面相似时会要求人工确认，可选定类型和面后继续检测同一张原图。检测设置中也可预先人工指定类型和拍摄面。
- 匹配相似度门槛 0.65、候选差距 0.025 是尚未校准的初始值。缺陷检测分数门槛默认 0.5，也需要真实数据验证。高分不能证明能够识别未知缺陷。
- 正常训练图片生成每个模型自己的识别参考。训练、推理使用相同处理版本。Anomalib 输入 256×256，Geti 输入 512×512，均为灰度三通道；细小损伤是否保留需查看模型输入并用实物验证。旧版自动旋转模型需要按新流程重新训练。
- Anomalib 与 Geti 分别执行。已知缺陷框来自 Geti；热力图表示异常响应，不给异常区域强行赋予缺陷名称。异常分数和分类／检测分数不是同一种数值，也不等于不合格概率。
- 实验热力图按单张图的数值范围显示，跨图颜色深浅不能直接比较。结果坐标映射回原图，变换矩阵单独留存。
- 一张图的结论针对当前可见面。实物本身是不合格件，不能推出它每一面都能看见缺陷。当前单色相机中的氧化需要存在可见灰度或纹理差异；颜色信息不在该相机的检测范围内。

## 模型验证

有更多独立实物后，可关闭“实验训练”。PatchCore 需要正常训练实物，以及不同实物的正常、异常验证图；Geti 需要已框选的训练缺陷、正常参考图和独立验证缺陷图。测试组不参与训练与阈值调整。

Geti 训练过程／验证指标可从模型任务下载。任务不会自动执行独立测试。准备好测试实物后，使用任务快照的 `prepared` 数据运行：

```powershell
uv run python -m workbench.anomaly test --data outputs/workbench/jobs/异常训练编号/prepared --checkpoint outputs/workbench/jobs/异常训练编号/patchcore/model.ckpt --output outputs/异常独立测试
uv run --project engines/geti python -m workbench.geti_worker test --data outputs/workbench/jobs/缺陷训练编号/prepared --checkpoint outputs/workbench/jobs/缺陷训练编号/detector/model.ckpt --output outputs/缺陷独立测试 --device cuda
```

实验模型不能报告正式独立测试指标。模型下载包包含权重、元数据、参考图和训练清单；Geti 的预测入口需要该模型旁的 `model.json`，软件运行还需要已安装的对应环境。

## 文件位置

```text
app.py                       工作台入口
workbench/                   API、数据管理、采集、对齐、任务与模型入口
engines/geti/                Geti 独立项目、锁文件与本机虚拟环境
web/src/                     React 界面
tests/                       数据、坐标、API、SDK 生命周期检查
data/raw/pilot/               类型/实物编号/拍摄面/原图.png
data/web/workspace-v2.sqlite3 样本、图片标注、分组及启用方案
outputs/workbench/jobs/       每次任务的快照、权重、日志和检测记录
```

检测记录保存原图、对齐图、原图热力图、坐标变换、模型版本、分数门槛、采集来源、原始预测和历次复核。界面中的记录 ZIP 可下载这些文件，结果 JSON 保留原始预测。

本次改造采用新数据库和任务目录，不迁移旧工作台数据。图片、数据库、权重、检测记录、虚拟环境和前端构建产物不提交 Git。

## 环境与开发检查

```powershell
uv run python -m unittest discover -s tests -v
uv run python check_env.py --check-sdk
uv run --project engines/geti python -m workbench.geti_worker check
uv run python -m workbench.anomaly train --help
uv run --project engines/geti python -m workbench.geti_worker train --help
Set-Location web
pnpm build
pnpm dev
```

Vite 默认 <http://127.0.0.1:5173>，代理 API 到 8765。主环境检查、Geti 检查及自动化测试不会打开相机。SDK 从本机 `C:\Program Files\Daheng Imaging\GalaxySDK` 加载，仓库不包含厂商 SDK、DLL 或驱动。

已用临时几何图形验证 GPU 训练、权重重载、旋转图片推理、双模型串联、原图坐标、记录导出、复核与回流。已检查桌面与窄屏页面。这些是软件流程验证；新工作台的真实相机持续采集、真实刀具定位和缺陷检测效果仍需实物验证。
