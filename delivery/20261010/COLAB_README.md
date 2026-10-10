# Wessex 第二阶段 Colab 续跑

`Wessex_Shared_Development_v3.ipynb` 是与当前 QA v3 代码配套的 CPU 运行入口。它不会访问 2024–2025 年评价目标，不会创建正式 App，也不自动上传、公开或投稿。该 notebook 的非 Drive 核心流程已在本地临时项目中验证；没有声称已在真实 Colab/Drive 账号上运行。

## 准备

1. 将本轮交付的代码、派生数据和所需运行/源检查点分包保存到自己的 Google Drive；不需要再次上传全量原始 Wessex CSV。
2. 在 Colab 打开 notebook。先手动挂载 Drive，将 `ROOT` 设为 Drive 内的项目文件夹。该目录必须包含 `src/`、`configs/shared_v3_20261009/`、v3 canonical CSV 及其 manifest、设施映射、历史队列 JSON 和 2016–2021 覆盖率 CSV。
3. 已有完整项目可跳过 ZIP 导入。ZIP 导入只接受相对路径、验证 ZIP CRC 与包内 `SHA256SUMS`（若提供）、拒绝路径越界和符号链接，并且不会覆盖已有但内容不同的文件。每个包的校验清单验证后不写入 `ROOT`，因此不同分包的不同清单不会相互冲突；原项目已存在的清单也保留。分包在同一个 `ROOT` 合并。
4. 依赖与原 CPU 运行对齐：Python 3.12、torch 2.8.0+cpu、numpy 2.3.5、pandas 2.2.3、scipy 1.17.0、scikit-learn 1.8.0、matplotlib 3.10.8。首次使用可开启依赖安装单元；安装后按 Colab 提示重启运行时。无 GPU 也能执行本轮规模，GPU 运行未实现或验证。

## 执行顺序

先运行环境与文件预检，然后执行两个既定开发测点的 `smoke.json`，种子为 20261009。完整流程检查包括两个 SiteID、四个起点、三个历史预算、两个时距、五个基线及三种 GRU 训练方式。随后运行 `full.json` 的种子 20261009，最后用完整三个种子入口补 20261010、20261011；已有首种子目标任务读取缓存，来源诊断保留三个种子。每个配置的种子必须来自已保存配置，禁止临时增加不同种子或更换开发测点。

`run_logged()` 的参数 `max_jobs=2` 可用于接口连通检查；程序以完整 baseline+GRU 任务组为边界，因此此参数是停止上限提示。它只产生部分完成状态，不能当完整实验结果。完整 smoke 应有 96 个任务；完整三种子开发应有 960 个任务。重复执行相同配置会校验已有任务的 SHA256 并读取完成缓存，而非重复拟合已完成的目标任务；源 Ridge 的轻量重新拟合不影响保存目标结果。

## 断点与保存

- 项目 `ROOT` 位于 Drive 时，`runs/shared_v3_20261009/source/` 和 `smoke/`、`full/` 的输出都直接持久保存。每个 GRU epoch 以临时文件替换保存 checkpoint；重连后再次运行同一配置恢复剩余 epoch。
- `runs/colab_logs/` 保存逐次命令日志和 JSON 调用完成记录。实验任务内部还有 `status.json`、`diagnostics.json`、模型 checkpoint、`failure_attempt_*.txt`，失败不删除。Notebook 状态检查区分 completed、partial、failed、running，不能根据进度条把 partial 报为 completed。
- 更改代码、数据、设施映射、训练设置或 torch 版本后，原源模型签名及目标任务指纹会拒绝混跑。若有合理的新方案，复制项目到新版本目录，并给新配置指定新的 `source_output` 和 `output`；保留旧文件与失败日志。只改目录名称不等于允许忽略配置校验。
- Drive 网络连接异常可能使文件保存失败；恢复挂载后检查 `status.json` 和 checkpoint，再重试相同配置。不要手动把失败状态改成 completed，也不要删除旧任务以追求更好的成绩。

## 核查与结果

源训练只使用 2016–2021。开发沿用 2022–2023 的原四个 60 日窗口；3 天表示第 3 天当天体积。发布后 Good QA 仅支持历史回顾，实时质量标记可用性未核实。13 个 SiteID 的物理设施/排口关系尚有未解决项目，输出不能表述为 13 座独立水厂。

Notebook 完成后调用已有 `scripts/validate_stage2.py` 检查保存预测的时间、预算、共同输入和评价真值，再调用 `scripts/summarize_shared_v3.py` 生成结果。这些步骤须在完整任务完成后运行；三种子误差汇总不把种子当独立设施。原始负预测与统一非负次分析均须保留。

本地 notebook 核心验证命令（不在原科学输出目录写入）：

```bash
PYTHONPATH=src .venv-stage2/bin/python scripts/validate_stage2_notebook.py \
  --project-root . --output validation/notebook_core_validation.json
```

验证报告的临时接口预测和合成 checkpoint 测试只验证可续跑性，均排除在科学汇总之外。
