# Stage3B 核查、复现与续跑

本交付针对 `stage3b_20261011_v1`，并补齐 `stage3a_20261010_v3` 的外部证据。Quick_Review 只用于快速阅读；独立重算需要完整 Predictions_and_Diagnostics 和 Code_and_Reproduce。每个 ZIP 独立可解压、严格小于24MiB；同一类别若有多个 Part，需全部下载。使用仓库当前可见性；私人仓库下载需要已获授权的 GitHub 登录。不得将外部审查过 Quick_Review 写成已经复现全部训练。

## 导入与完整性

将所有本轮 ZIP、外层 SHA256SUMS 放入同一目录。先从 Code_and_Reproduce ZIP 取出 `scripts/import_stage3b_delivery.py`，再向一个**新的**目录导入：

```bash
python scripts/import_stage3b_delivery.py --destination /tmp/wessex_stage3b_review --sha256sums /path/to/packages/SHA256SUMS /path/to/packages/Wastewater_Stage3B_*.zip
cd /tmp/wessex_stage3b_review
python -m venv .venv-stage2
.venv-stage2/bin/python -m pip install -r requirements.txt
export PYTHONPATH=src
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
```

导入器实际检查 ZIP 大小、CRC、每个文件 SHA256、清单完整性和路径。重复导入只接受相同内容，拒绝不同内容覆盖。大型 Stage3A CSV 在包中以 `.csv.gz` 保存；导入器核验压缩文件及解压后原始 CSV 的 SHA256，恢复历史脚本所需原路径。每个 ZIP 的清单位于 `.stage3b_package_manifests/<ZIP名>/`，不会互相覆盖。只需阅读时可以普通解压 Quick_Review；复现使用上述校验导入器。

## 从逐条预测重算

以下命令不训练新模型、不读取2024–2025、不写入已有结果目录：

```bash
.venv-stage2/bin/python scripts/recalculate_stage3a_delivery.py --output outputs/recomputed_stage3a
.venv-stage2/bin/python scripts/summarize_stage3b.py --config configs/stage3b_20261011_v1/full.json --predictions reports/stage3b_20261011_v1/results/predictions_all.csv.gz --output outputs/recomputed_stage3b
.venv-stage2/bin/python scripts/check_stage3b_results.py --arithmetic-only --output outputs/STAGE3B_ARITHMETIC_CHECK.json
```

Stage3A 第一个命令独立重建共同日期掩码、逐日损失及1800项逐 SiteID 指标，比较容差为绝对1e-8、相对1e-12；不声称逐位一致。GRU 的三个种子先平均同一日期的绝对/平方损失，**不**把预测均值作为集成。完整旧 bootstrap 重算实现也包含于 `scripts/check_stage3a_evidence_stage3b.py`，在有该脚本需要的环境时运行：

```bash
.venv-stage2/bin/python scripts/check_stage3a_evidence_stage3b.py --arithmetic-only --skip-history --output outputs/stage3a_full_arithmetic
```

部分历史代码仍依赖 PyTorch；若当前脚本导入提示缺少 torch，在独立审查环境安装 `torch==2.8.0+cpu`，使用官方 CPU wheel 索引 `https://download.pytorch.org/whl/cpu`。新 Stage3B Ridge 与上述第一项 Stage3A 指标重算不需要 PyTorch。

## 新 Ridge 的实际训练与续跑

小规模检查和全轮准确命令：

```bash
.venv-stage2/bin/python -m unittest discover -s tests -p 'test_stage3b*.py' -v
.venv-stage2/bin/python -m wastewater.stage3b_experiment --config configs/stage3b_20261011_v1/full.json --workers 2 --smoke
.venv-stage2/bin/python -m wastewater.stage3b_experiment --config configs/stage3b_20261011_v1/full.json --workers 2
```

原两个烟雾 SiteID 为13013/13015；首个窗口、三预算、两时距，共12条件。全轮是10 SiteID ×5窗口 ×3预算 ×2时距，共300条件；每条件保存11条模型策略，每策略60日起点。源训练止于2021；合法验证代理止于2020；第五窗口为经过历史使用核验并事前冻结的2023-10-01，不代表新设施外部验证。

导入全证据包后，这些命令验证已完成缓存并续跑未完成任务。数据、配置、科学代码及版本不匹配时拒绝复用；修改模型须新版本，不能修改本轮冻结文件绕过检查。任务状态与失败日志在 `runs/stage3b_20261011_v1/{source,smoke,full}`。已有完整缓存不会重新拟合。续跑入口会记录本次调用元数据；对原工作区只读审查请仅运行重算命令。

完整续跑入口还会由缓存逐条预测重建原始聚合 `predictions_all.csv.gz`，其科学预测值不变，但统计步骤添加的共同日期/可用性等派生列会被移除。因此在**新导入的审查目录**续跑后，再运行下列命令重建派生指标到另一个目录；不要将聚合文件列数或调用元数据变化误解为重新训练或模型结果变化。

```bash
.venv-stage2/bin/python scripts/summarize_stage3b.py --config configs/stage3b_20261011_v1/full.json --predictions reports/stage3b_20261011_v1/results/predictions_all.csv.gz --output outputs/recomputed_stage3b_after_resume
```

源、每条件参数与全部验证网格的收集脚本也包含：`PYTHONPATH=src .venv-stage2/bin/python scripts/collect_stage3b_diagnostics.py --config configs/stage3b_20261011_v1/full.json`。它核验300条件及源缓存、收集2700参数策略行/18408验证网格，并匹配归档直接模型；不重新训练。该命令将更新派生诊断表，适合已导入完整证据的新审查目录。Code-only 从零跑完后的新任务诊断已在每条件目录中；完整归档对比还需 Predictions_and_Diagnostics 中的 Stage3A 预测。

若要真正从零训练，另建新目录并仅导入 Code_and_Reproduce。该包包含 QA-v3、设施映射、2016–2021覆盖证据、冻结协议/配置/历史窗口资格、Stage3A源选择 JSON 及全部必要代码；无需旧 GRU 权重。保留完整版已保存预测作为比较依据，不删除或覆盖它们。先运行12条件检查，再按同一命令运行全部300条件。Ridge 为确定性程序，不人为重复三种子；随机种子用于 block bootstrap，原 GRU 三种子仅作归档。

## 材料覆盖与省略项

提供 Stage3A 全部388800条主预测、daily_losses、固定轮数端点预测、全部目标训练/验证曲线、源训练/验证曲线、240条件选择/诊断/状态记录与关键代码/配置。提供 Stage3B 全部预测、逐日损失、配对日期索引、各站指标、区间、参数选择、源模型及每条件小型参数文件、日志和完成记录。包含当前真实数据子集，不包含全量百万行原始 CSV 或虚拟环境。

部分 Stage3A 优化器/每轮权重及全部原 Stage2 运行文件未复制进本轮包。新 Ridge 重训、全部已保存指标重算不依赖它们；历史 GRU 全训练/端点复放则需要旧 Runs 等包。`reports/stage3b_20261011_v1/OMITTED_DEPENDENCIES.json` 列出原文件 SHA256、历史 Git commit 下载地址和影响。完整历史重放应在另一个干净目录，按原交付要求导入原 Stage3A/Stage2 包，不向新项目覆盖旧文档。不能将本轮算术复核声称为全训练独立复现。

为减少重复下载，仅从 ZIP 省略审查脚本重新生成的三个 `daily_losses_recomputed.csv.gz` 副本；工作区原文件保留，原始完整 Stage3A daily_losses 与所有负面预测照常包含。省略项的路径、字节数、SHA256 和准确重算命令列于同一 OMITTED_DEPENDENCIES.json；其 JSON 检查记录、逐站指标及代码均包含。省略这些可再生成的算术副本不是删除实验负结果。

QA-v3 的实验 CSV 可直接重训。新 provenance 还提供原选中记录 `selected_raw_records.csv.gz`、排除记录、规则、官方证据及计数，可审查所用13测点的清理。全量 QA 重建依赖用户原始上传包内 `wastewater_data/raw/wessex_all_2016_2025.csv`，SHA256 `22f494e2b96fe6fa9550c68971d50c752ddd291793fdc60334d64b2ef089f518`。原始全库包含最终年份，不在本轮模型重训包中。

## Colab 与停止点

`notebooks/Wessex_Stage3B_CPU.ipynb` 提供依赖安装、Drive 路径、ZIP/数据/协议/代码校验、任务续跑、失败日志及结果导出。默认 `review_cached` 核验完整缓存；`fresh_smoke` 在另一个新目录仅导入代码包，实际训练12条件。关键代码在本地运行核验；未登录测试真实 Colab/Drive，不能称其已经云端认证。

公开 QA 筛选是回顾性情景；物理设施和排口映射仍未确认。只报告 treated effluent volume forecasting，不推断污染物、容量、溢流、节能或经济收益。完成冻结轮次后停止；本包不授权源扩充、额外深度模型、区间模型、最终期选模、集成或 App。
