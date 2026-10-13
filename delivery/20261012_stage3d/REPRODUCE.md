# Stage3D 经验预测区间：读取、复核与续跑

本轮为在查看Stage3C2开发结果后制定的有界开发实验，版本`stage3d_interval_v1`。相同Persistence点预测中心、10个开发SiteID、五个已使用窗口、30/90/180天初始历史、h=1/3均冻结；共享仅借用三个既有K30来源组合。发布后质量标记属于回顾性情景，`physical_mapping_verified=false`，实时发布时间未验证。经验分位数不附带有限样本、条件覆盖或conformal保证。

本文件先记录可核实的接口与依赖；实际执行情况只由`RUN_STATUS.json`、完整运行manifest、独立核验和外层`PACKAGE_CHECKS.json`决定。不能由`failed=0`或文档存在判定完成。

## 两类交付不可混称

- 新Stage3D包：Quick Review、Code and Reproduce、完整Predictions and Diagnostics（可能多个独立ZIP，每包严格小于24MiB）。把同一阶段所有包解压到同一个**新目录**，重叠成员必须SHA一致。
- 原Stage3C2重交：五个原ZIP仅改外层文件名，使用`Wessex_Stage3C2_Original_*_Reissued_20261012`唯一前缀。容器字节、原成员和原预测保持不变；`C2_ORIGINAL_REISSUE_MANIFEST.json`列出原/新文件名、大小、SHA及成员校验。Part01/02是在仓库中找到并核验的原文件，不是重新生成的预测。本轮不会重训旧Ridge或GRU。

每个新ZIP内有独立`PACKAGE_*_MANIFEST.json`和`PACKAGE_*_SHA256SUMS`；交付根`SHA256SUMS`列每包SHA。ZIP自校验不代替科学重算。任何同名不同SHA文件必须拒绝覆盖。

## 最小环境和数据

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements-stage3d.txt
export PYTHONPATH="$PWD/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export MPLCONFIGDIR="$PWD/.mpl-cache"
```

代码包包含原Stage3C2 canonical清理输入、raw摘录及已有QA verifier、固定三套源池与受保护分组证据、Stage3C2共同评价日期和不可变Persistence参考。对这部分数据采用原SHA；没有为区间实验重新清洗、插值或取保护/最终年份数据。数值环境参与缓存指纹，不能把另一个依赖版本的旧缓存视为兼容。

```bash
.venv/bin/python scripts/verify_stage3c2_data.py --root "$PWD" --output verification/data_qa.json
.venv/bin/python -m unittest discover -s tests -p 'test_stage3d*.py' -v
```

源误差库建在允许的2016—2021数据。源侧留一关系组选择gamma时，其余源的误差库与尺度只用截至2020年的记录；被留出测点的两个2021伪部署各14个起点。最终γ选择按源测点及窗口等权的归一化90%interval score。目标部署使用原单位评分，不把不同预算的归一化分数混比。

## 校准与评价边界

每个目标初始历史为[T−B,T−1]，校准起点、Persistence输入和h天后标签均在预算内。至少14个有效误差，正值中位数尺度缺失即明确失败；不从更早或更晚记录补数据。尺度、经验分布及gamma在60日起点窗口中冻结。部署更新当时可见的滞后观测，不添加部署误差。

LOCAL、SHARED、MIXTURE的gamma端点、80%/90%嵌套和共同点预测中心均需要逐条核查。原始上下界为主，所有方法一致的`lower=max(0,lower)`为敏感性；全部负结果与校准不足须保留。

## 实际运行入口

以下命令对应原环境真实执行的入口；完整状态及耗时请读运行记录。原冻结`check_stage3d_smoke.py`的科学断言通过后曾因numpy整数JSON序列化失败，保留其字节及日志；`v2`只修输出类型，`v3`缓存同一源数据以避免重复读取，不改变科学结果。实际gate入口为`v3`，不是复制旧通过标记。

```bash
.venv/bin/python -m wastewater.stage3d_experiment \
  --config configs/stage3d_interval_v1/full.json --mode sources --workers 1
.venv/bin/python -m wastewater.stage3d_experiment \
  --config configs/stage3d_interval_v1/full.json --mode smoke --workers 1
.venv/bin/python scripts/check_stage3d_smoke_v3.py
.venv/bin/python -m wastewater.stage3d_experiment \
  --config configs/stage3d_interval_v1/full.json --mode full --workers 1
.venv/bin/python -m wastewater.stage3d_experiment \
  --config configs/stage3d_interval_v1/full.json --mode resume --workers 1
.venv/bin/python scripts/summarize_stage3d.py \
  --config configs/stage3d_interval_v1/full.json \
  --run runs/stage3d_interval_v1/full --output verification/results
.venv/bin/python scripts/check_stage3d_results.py \
  --root "$PWD" --output verification/independent_interval_check.json \
  --skip-original-c2-packages
.venv/bin/python scripts/plot_stage3d.py \
  --config configs/stage3d_interval_v1/full.json \
  --results verification/results --output verification/figures
```

首次仅解压Code包时，`sources`实际冷建三源库并完成1,080折/18个gamma；`smoke`实际计算原13013/13015首窗12条件，12,960区间行；随后独立核验写合法smoke gate，full才可开始。源结果、gamma、code或数据校验不符时拒绝缓存。partial退出码3，不能因为failed=0宣称完成。

合并完整Predictions包后，`resume`会校验全部300任务并跳过已完成任务；`summarize`从保存上下界重算区间评分、覆盖、宽度、配对负迁移/历史比较及7/14/28日各5,000次重采样。**这是保存区间复算，不是冷跑完整实验。** 重算写新`verification/results`，不覆盖交付原表。

独立checker不导入D训练/区间构造/评价器，重新实现合法历史、加权CDF、源γ目标、端点/中心、IS公式、逐设施相对技能及主要区间的原始同步抽样。`--skip-original-c2-packages`仅声明D-only干净复现范围；仍核验冻结C2共同日期及Persistence子集。完整旧C2容器/全部旧预测在单独重交包中按原SHA核验，没有凭该flag假称独立复现旧Ridge/GRU。

```bash
.venv/bin/python scripts/package_stage3d.py --extract \
  ../Wessex_Stage3D_Quick_Review_20261012.zip \
  ../Wessex_Stage3D_Code_and_Reproduce_20261012.zip \
  ../Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part01.zip \
  ../Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part02.zip \
  --destination ../new_stage3d
```

预测分包的实际数量以交付`SHA256SUMS`和`README.md`为准，上例展示分包模式。每个ZIP可独立解压，完整结果复核需要全部D包。不要将原C2 ZIP输入D版本的extract命令；旧重交包按原C2复现说明另建目录。

## 外部依赖与复现范围

1. 完整原CSV`wastewater_data/raw/wessex_all_2016_2025.csv`省略；SHA256：`22f494e2b96fe6fa9550c68971d50c752ddd291793fdc60334d64b2ef089f518`。来自原用户上传`Wastewater_Part1_Plan_and_Raw.zip`或现有项目。它仅用于从零重建此前186候选资格/原全量数据来源审计，不是本轮冷建源误差库、目标smoke或保存区间重算的必要输入。
2. Stage3C2全部历史使用扫描登记和旧Stage3A/GRU轨迹没有复制入新D代码包；原交付保持。新包提供源池/保护/关系证据和原共同日期，不能据此声称独立重建了旧实验全部历史。
3. 正常处理后排口、坐标、污水集水区、物理设施关系、日界线及数据/QA首次发布时间仍需提供方确认；不得以名称、厂址代理或暴雨溢流坐标替代证据。
4. 本地Code-only冷源γ选择与12条件smoke，和合并Predictions包后的300条件缓存核验/指标重算，是不同范围。打包实际通过情况、命令、耗时、容差及未执行项写入`PACKAGE_CHECKS.json`，不把缓存复算称为冷跑完整实验。

完成本轮后停止。不得自动开启2024—2025性能、独立保护池评价、降雨、深度网络、App或论文重写。
