# Stage3C2：有限源池规模开发实验交付

本轮已实际完成固定10个开发SiteID、五个已使用窗口、三预算及两时距的300条件；七源池、17策略，共306,000逐预测。37个临时保护组未参与拟合、调参或性能评价。物理映射与实时信息可得性仍未核实。

预定K30+bias/B30主候选对Persistence技能为h1 +0.7044%（调整区间−1.2046%至+2.0687%）、h3 −0.1888%（−8.3090%至+5.3770%）；六项主要比较均未满足14日调整区间下界大于零的联合成功标准。全部组成、负迁移与负面结果保留。该阶段停止，等待审查。

[中文分析](ANALYSIS_ZH.md) · [实验协议](STAGE3C2_PROTOCOL.md) · [完成记录](RUN_STATUS.json) · [重算说明](REPRODUCE.md) · [独立核验](INDEPENDENT_CHECK.json) · [打包与干净重放](PACKAGE_CHECKS.json) · [SHA256](SHA256SUMS)

每个ZIP均小于24 MiB；预测诊断共有三卷，每卷都是可单独解压的ZIP，完整复核须把全部五包解压到同一个**新目录**。允许同SHA重叠，拒绝同名不同SHA。分析引用结果表在包内`reports/stage3c2_source_scale_v1/results/`。

| 文件 | 大小（MiB） |
|---|---:|
| [Wastewater_Stage3C2_Quick_Review_20261012.zip](Wastewater_Stage3C2_Quick_Review_20261012.zip?raw=true) | 3.380 |
| [Wastewater_Stage3C2_Code_and_Reproduce_20261012.zip](Wastewater_Stage3C2_Code_and_Reproduce_20261012.zip?raw=true) | 11.300 |
| [Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part01.zip](Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part01.zip?raw=true) | 21.989 |
| [Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part02.zip](Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part02.zip?raw=true) | 20.927 |
| [Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part03.zip](Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part03.zip?raw=true) | 2.849 |

全部ZIP已经过CRC、所有成员SHA和干净解压检查。代码包单独冷运行了K3全300条件并与原Stage3B逐条比较，再实际训练七源银行/12个smoke条件；其12,240条预测与选参一致，最大归一化数值差为0。随后另一个新根合并五包，验证并跳过300个完整缓存任务、重算21张评价表及全部7/14/28日5000重采样区间，最后独立重构源正规方程、验证分数、5,100策略预测与18项主要区间，均通过。上述是数值容差范围的复现，不笼统声称文件逐位相同；全扩源300条件没有在打包时重复冷训练。

以下为仅从代码包开始的冷重放顺序。评价写至配置指定结果路径，使后续独立核验能读到它；不要在已有完整交付目录覆盖结果。合并全部包后，先采用resume并把指标复算输出改为`verification/results`，独立核验读取原交付结果。

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-stage3c2.txt
export PYTHONPATH="$PWD/src"
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MPLCONFIGDIR="$PWD/.mpl-cache"
.venv/bin/python scripts/verify_stage3c2_data.py --root "$PWD" --output verification/data_check.json
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode k3-check --workers 2
.venv/bin/python scripts/check_stage3c2_k3.py
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode smoke --workers 2
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode full --workers 2
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode resume --workers 2
.venv/bin/python scripts/summarize_stage3c2.py --config configs/stage3c2_source_scale_v1/full.json --run runs/stage3c2_source_scale_v1/full --output reports/stage3c2_source_scale_v1/results
.venv/bin/python scripts/check_stage3c2_results.py --root "$PWD" --output verification/independent_check.json
```

从头执行上面完整顺序用代码包即可（包含必要canonical、raw excerpt及原Stage3B五策略逐条参考）。合并所有包后直接full/resume会校验并复用保存缓存；这不是重新训练。独立核验默认读取配置指定的保存结果目录，需完整预测诊断包或先评价至协议指定目录，详见REPRODUCE。

完整186候选资格与历史扫描的从零重建仍依赖原73,570,225字节CSV（SHA256 `22f494e2b96fe6fa9550c68971d50c752ddd291793fdc60334d64b2ef089f518`）及原配置/运行清单，本小包省略这些不必要的大历史输入。模型输入QA、保护/排序算术、K3/smoke训练及保存预测指标可自包含核验。不得把临时保护池称已认证独立水厂最终测试集。

实际训练命令29.15秒，评价41.04秒；包装创建/成员核验33.53秒、全部包装与清根复算总203.21秒。并行全进程树峰值内存未可靠测得，单进程评价观测约716 MiB。没有GPU、付费资源、降雨/GRU新训练、预测区间模型、2024—2025性能、论文或App。
