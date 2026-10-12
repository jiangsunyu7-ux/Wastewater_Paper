# Stage3C2 读取、核验和续跑

本阶段为 `station_exploratory`；所有五窗均为已使用开发日期，`physical_mapping_verified=false`。冻结原体积六列、缺失归一化占位 **1** 和mask；不添加降雨、深度模型或2024—2025性能。本轮科学完成与软件核验的实际状态看 `RUN_STATUS.json`、`runs/.../full/manifest.json` 和交付目录 `PACKAGE_CHECKS.json`。本文件列出确定入口，不以文档存在宣称运行成功。

## 安装与解压

使用新目录。三个类别的ZIP均可单独解压；完整指标复核需把全部包合并到同一个新根。每包独立含成员SHA清单，重叠成员只能字节相同。Quick_Review用于阅读；Code_and_Reproduce用于从头训练K3和smoke；Predictions_and_Diagnostics包含完整保存预测、任务状态、源模型和诊断。必要时预测包自动分卷，各卷都是独立ZIP。

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-stage3c2.txt
export PYTHONPATH="$PWD/src"
export OPENBLAS_NUM_THREADS=1
export OMP_NUM_THREADS=1
export MPLCONFIGDIR="$PWD/.mpl-cache"
```

数值环境参与缓存指纹；安装其他numpy/pandas/sklearn版本不会被假定与旧缓存兼容。首次从 Code_and_Reproduce ZIP解压后，也可用以下检查覆盖式解包；已有同名不同SHA成员会被拒绝，不应在旧项目目录使用。

```bash
.venv/bin/python scripts/package_stage3c2.py --extract ../Wastewater_Stage3C2_Quick_Review_20261012.zip ../Wastewater_Stage3C2_Code_and_Reproduce_20261012.zip ../Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012.zip --destination ../new_stage3c2
```

实际文件名与分卷数以交付 `SHA256SUMS` 为准。`PACKAGE_<类别>_MANIFEST.json`逐成员登记路径、大小和SHA；根 `FREEZE.json`包含21个冻结科学输入及代码。压缩容器校验不能代替以下数据与运行校验。

## 自包含数据核验与测试

代码包交付原始摘录 `selected_model_raw_records.csv.gz`、未插值的清理输入 `daily_candidates.csv`、原对应gzip、数据manifest和分区证据。冻结读取的是**未压缩CSV**，不能直接替换为gzip路径；若仅保留gzip，解压后必须对CSV核对 `FREEZE.json` 的SHA。逐条QA、临时保护SHA和三套嵌套源排序可自包含重算：

```bash
.venv/bin/python scripts/verify_stage3c2_data.py --root "$PWD" --output verification/data_check.json
.venv/bin/python -m unittest discover -s tests -p 'test_stage3c2*.py' -v
```

同原始容器的完整186候选资格重建与此前历史模型使用登记扫描仍需原项目证据，不冒充代码包自包含。遗漏依赖详见下方。新训练使用交付原始摘录经核验的canonical；不得修改冻结文件或跳过K3门槛。

## 从头核验K3与smoke

代码包提供原Stage3B的300个不可变 `predictions.csv`、`selection.json`及10个源 `.npz`，支持用原核验脚本逐条比较而非只复用通过标记。Code包不附本轮源银行或smoke任务缓存，以下将实际训练K3，再训练七个源银行并跑12个smoke条件：

```bash
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode k3-check --workers 2
.venv/bin/python scripts/check_stage3c2_k3.py
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode smoke --workers 2
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode smoke --workers 2
```

第二次smoke应验证并跳过12个完整任务，不重复拟合目标模型；有缺失输出、成员SHA错误或指纹变化则拒绝混用。正常K3检查对应五策略、300条件、90,000条预测。随后smoke固定13013/13015、首窗、三预算、两时距，12条件×17策略×60起点=12,240条预测。归一化预测 `atol=1e-10, rtol=1e-10`；alpha/lambda、日期、真值和缺失位置精确核对，不能把容差重现称逐位相同。

## 完整训练、断点续跑和评价

从头只解压代码包、已通过K3和smoke之后：

```bash
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode full --workers 2
.venv/bin/python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode resume --workers 2
.venv/bin/python scripts/summarize_stage3c2.py --config configs/stage3c2_source_scale_v1/full.json --run runs/stage3c2_source_scale_v1/full --output verification/results
.venv/bin/python scripts/check_stage3c2_results.py --root "$PWD" --output verification/independent_check.json
.venv/bin/python scripts/plot_stage3c2.py --config configs/stage3c2_source_scale_v1/full.json --results verification/results --output verification/figures
```

完整训练预期300条件、5,100策略条件、306,000逐预测，17策略包括共同基线和七池两共享方法。不能由 `failed=0` 判完成；full/resume须验证全部预期任务和必要成员集合，partial退出码3。`resume`与`full`指向同一完整运行目录。

若合并完整预测诊断包，`resume`将复用经指纹/SHA验证的已完成300任务，评价命令从保存逐预测重算全部点指标、配对日期、负迁移、跨预算、历史高体积和7/14/28日各5000次区间。不得称这种“保存结果复算”重新训练了全扩源实验。评价会拒绝smoke、partial、输出缺失或指纹不符。新复算写 `verification/results`，避免覆盖交付原结果。

## 外部依赖与复现边界

- 完整原CSV `wastewater_data/raw/wessex_all_2016_2025.csv`：SHA256 `22f494e2b96fe6fa9550c68971d50c752ddd291793fdc60334d64b2ef089f518`，来自用户上传 `Wastewater_Part1_Plan_and_Raw.zip` 或项目原目录。由于保护测点和2024—2025记录不必要，本包省略完整原CSV。下载文件名不保证版本相同，必须核SHA。
- 重新从零建立186候选资格和历史使用扫描还需完整原CSV及既往4979份配置/运行/元数据清单。代码包包含准备审计登记的全部小输入，包括旧13点QA `data/derived/wessex_qa_v3_20261009/daily_candidates.csv`，SHA256 `40f6e6fdb1d09d0afa9c19ba31729b156811ca1cdbb0b317484fdf5fea1d854f`、年度覆盖、官方名称表及映射状态；这些不是本轮从canonical训练或指标复算的必要输入。打包提供结果清单、排除摘录及资格/分区算术证据，但不声称独立重建了原项目全部历史。
- Stage3B其余11策略的权重、完整轨迹和Stage3A GRU未整包复制。提供的300旧预测包含对应五策略且保持原文件字节；10源npz覆盖K3系数比较。完整旧实验仍在原交付，旧证据校验值见保留审计。
- 正式物理设施、正常出水排口、实测日体积/QA发布时间仍unknown；本轮名称关联/保护组不是已认证最终水厂测试集。需补证据清单见中文分析和协议。

独立核验脚本不导入训练器或评价器，另行实现特征、Persistence、正规方程、选参分数、逐日损失及原始块抽样。它默认核对配置中保存的`reports/.../results`，所以需要完整预测诊断包（或原完整运行），仅代码包不能凭通过标记做此项核验。

打包程序会在独立干净目录实际运行测试、数据检查、K3全条件原脚本、冷smoke与缓存smoke；另一个干净目录合并全部包后核验full缓存、重算所有评价表并运行独立模型/选参/指标/主要区间核验。实际通过情况、行数、最大误差、耗时和未执行项在 `PACKAGE_CHECKS.json`记录。本轮打包不会执行深度训练、降雨模型或最终年份性能。
