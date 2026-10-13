# Stage3E：修复、诊断与交付复核

版本为 `stage3e_evidence_review_v1`；本阶段不训练新预测模型。原 Stage3D 科学文件与参数保持原冻结 SHA。新增统计分析是事后探索诊断，不是新的独立确认实验。

## 环境与解压

将所有新 Stage3E 包解压到同一个新目录；禁止覆盖已有不同 SHA 文件。各包均有 `PACKAGE_*_MANIFEST.json` 和 `PACKAGE_*_SHA256SUMS`，外层 `ARTIFACT_INDEX.json` 列出包 SHA、阶段、配置、结果路径及真实状态，`SHA256SUMS` 覆盖其余交付文件。原 C2 Part01/02 是另附原件，勿将其混解为新 E 数据。

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-stage3d.txt
export PYTHONPATH="$PWD/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLCONFIGDIR="$PWD/.mpl-cache"
```

原数值版本参与冻结配置指纹；更改依赖后不能冒用已有缓存。新 Code 包包括旧 D 冻结清单中的原文件、清理数据、三个既定源误差库和原十二 smoke 条件输出，它们均是只读复现依赖，不是本轮新源库拟合。

## 有界的软件可靠性复算

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_stage3e*.py' -v
.venv/bin/python -m wastewater.stage3e_runtime --mode smoke
.venv/bin/python scripts/check_stage3e_runtime.py --scope smoke
.venv/bin/python -m wastewater.stage3e_runtime --mode resume
```

该范围为原两个测点 13013/13015、首窗口、所有预算与时距，共十二个条件。重新计算同一冻结数学规则的历史校准与区间，只验证状态修复不会改变三个科学文件；不重新选择 gamma、不重训 Ridge/GRU、不重跑三百条件。`smoke` 和 `resume` 都验证磁盘证据；重复运行应校验后复用，而非按状态字符串盲目跳过。

函数返回成功与磁盘证据完成分别记录。原子文件写入不等于跨文件事务；独立持久化完成凭证只有在文件存在、指纹、行数、键、时间边界和 SHA 全部通过后才提交。`--max-jobs 1` 在新运行目录应返回 PARTIAL 和退出码 3；不能把 `failed=0` 当作完成。

`check_stage3e_runtime.py --scope smoke` 包含受控陈旧 RUNNING、缺失输出、损坏缓存、写入中断和错误指纹等软件夹具及重复 resume。故障注入不代表复现了外部自然异常。原外部九个 RUNNING 问题未自然复现，根因仍未确认；已有原三百条件只读审计记录与新防护分开保存。

## 全部事后诊断重算

完整诊断依赖既有 D 原预测/损失与三百任务的校准、诊断文件；为了避免再次发送大体积旧预测，新 E 包没有将这些全部重复打包。先取回并核验原 Stage3D 三个 Predictions and Diagnostics 分包，按原目录补齐到新目录（旧 Code/Quick 包仅用于缺失旧依赖时）。原 D 包仍在固定提交：

https://github.com/jiangsunyu7-ux/Wastewater_Paper/tree/551f1fc38478e828e3640916fd2d7e709c7247e3/delivery/20261012_stage3d

具体必要原文件、大小与 SHA 以 `reports/stage3e_evidence_review_v1/results/INPUT_MANIFEST.json` 为准。不用重新生成旧预测来代替核验原件；不能将本说明称为完全无需外部输入的全量复现。

```bash
.venv/bin/python scripts/run_stage3e_diagnostics.py \
  --config configs/stage3e_evidence_review_v1/diagnostics.json \
  --output verification/stage3e_results
```

此命令只读取既有记录，重新计算评分、分布、时段和同步时间块统计，不拟合或选择模型。原默认结果目录为 `reports/stage3e_evidence_review_v1/results`；外部复算应使用新的 `verification/stage3e_results`，保留原表。已完成缓存按输入和代码指纹校验；不使用 `--force` 绕过不明缓存。

主要两项区间从保存逐条区间评分重算，而非读旧通过标记。14 天块为主，7/28 天敏感性，5000 次，两个主要比较各 97.5% 调整区间。新的分布量仅有描述性加权 KS，不给未经证明的显著性解释。源/目标/部署误差差异和逐一移除测点只供解释，不回流到任何选择或部署规则。

## 结果与图件读取

所有新增逐测点、窗口、时间段、分布、尺度贡献、跨预算及高体积表在 `reports/stage3e_evidence_review_v1/results`。图件目录为 `figures/stage3e_evidence_review_v1`，每张图关联真实 CSV 与绘图代码；图中的“留一测点”是影响诊断，正式评价仍保留全部十个测点。

```bash
.venv/bin/python scripts/plot_stage3e.py \
  --results reports/stage3e_evidence_review_v1/results \
  --stage3d-results reports/stage3d_interval_v1/results \
  --output verification/stage3e_figures
```

实际绘图命令及输入 SHA 写入图件来源记录。没有将部署误差用于选源、gamma 或后验回退。没有新的 2024—2025/保护设施性能，不使用滚动再校准。

## 旧交付、未知与停止

原 C2 Part01/02 本轮按原 ZIP 字节复制，另附 SHA 与成员清单，未重新生成旧预测。用户提供方原审查 ZIP 及带 `(1)` 的重复附件未收到；外部重复 SHA 与九任务异常仅能按用户报告引用，仓库原文件和本轮修复可独立核验。

设施历史身份、正常出水测点、日界线、首次观测与 QA 发布时间仍未获提供方认证。代码包中的站点分组只是探索性 provisional group，不是独立物理水厂证明。中英文资料请求为未发送草稿。

本轮结束后停止；下一行动须依据 `NEXT_STAGE_DECISION.md`，不得自动开展最终测试、模型扩展、源池扩展、App 或整篇论文。
