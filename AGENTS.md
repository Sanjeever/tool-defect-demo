# 项目约定

## 目标与范围

本项目用于学习刀具工业视觉检测，先验证离线图片，再接入大恒工业相机。
Anomalib PatchCore 负责正常／异常判断与热力图，YOLO 分类模型负责已知缺陷分类。
当前尚未收到刀具样本，不预设刀具类型、缺陷类别、ROI 或合格阈值。
不得将随机图片、预训练分类结果或软件检查结果描述为刀具检测效果。

## 开发环境

- 使用 Windows、PowerShell、Python 3.11 和 uv。
- 安装环境用 `uv sync --locked`，运行入口用 `uv run python 文件名.py`。
- Python 依赖写入 `pyproject.toml`，同步提交 `uv.lock`。
- PyTorch 使用项目指定的 CUDA 12.4 索引，升级前核对显卡驱动与 torchvision 配套版本。
- YOLO 使用官方 `ultralytics-opencv-headless` 发行包，导入名称仍为 `ultralytics`。
  不同时安装多个提供 `cv2` 的 OpenCV 包。
- 大恒 `gxipy` 从本机 GalaxySDK 加载，不将厂商 SDK、DLL 或驱动复制进仓库。
- 本机 `gxipy` 依赖 NumPy 1.x，保持 NumPy 1.26.4 及配套 OpenCV、imagecodecs 版本，升级前验证 SDK 导入。

## 数据与模型

- 原始图片放在 `data/raw/`，处理后的异常检测数据放在 `data/anomaly/`。
- 按实际刀具划分训练、验证和测试，同一把刀具的连拍、裁剪、增强图归入同一组。
- PatchCore 训练集仅包含正常图；验证集用于调整阈值；测试集用于最终评估。
- 训练与推理使用相同 ROI、缩放、补边及灰度转换流程。
- 缺陷分类目录名须来自真实标注，示例名称不代表已确认类别。
- 图片、权重、检测结果、本机虚拟环境不提交到 Git。
- 不自动打开相机、修改网络配置或结束 GalaxyView 进程。用户明确运行采集命令后才控制相机。

## 实现与验证

- 保持命令行入口简洁，优先使用 Anomalib、Ultralytics 和厂商 SDK 的现有 API。
- 错误应清楚暴露，不静默切换 CPU、不自动下载替代数据、不生成虚构结果。
- 修改图像预处理后运行 `uv run python -m unittest discover -s tests -v`。
- 修改依赖或模型入口后运行 `uv run python check_env.py` 及相关入口的 `--help`。
- 相机枚举、单张采集、模型训练和真实缺陷效果分别报告，不能相互替代。
- 无样本时可完成环境与代码验证，明确记录训练和检测效果尚未验证。

## 文档与提交

- 沟通、README、项目说明及新增注释使用简体中文，命令和第三方命名除外。
- 提交信息使用 Conventional Commits，描述用中文，例如 `feat: 搭建刀具缺陷检测实验项目`。
- 修改命令参数或目录约定时同步更新 README 中的示例。
