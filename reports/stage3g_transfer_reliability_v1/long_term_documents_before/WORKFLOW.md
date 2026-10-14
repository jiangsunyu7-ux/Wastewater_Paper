# 开发入口与结果边界

当前Stage3E证据审查已完成，STOP等待审查。先读reports/stage3e_evidence_review_v1/REPRODUCE.md、RUN_STATUS.json、ANALYSIS_ZH.md与NEXT_STAGE_DECISION.md。新运行修复只复算原12条件的历史区间校准；新事后诊断只读取已有预测。不要在原Stage3D运行目录执行resume，不自动启动新模型或最终测试。历史入口说明保留如下。

启动时没有真实数据；收到拆分包后已完成全量审计和三个真实开发基线。下方模板说明保留为通用入口；最新实测命令见末尾。27项程序测试与真实结果检查分别记录，不能混同。

## 环境和目录

在 `/workspace/Wastewater_Paper` 执行：

```bash
bash scripts/refresh_environment.sh
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
```

如已存在 `.venv`，先 `source .venv/bin/activate`。不需要长驻服务器或 GPU。

目录：materials 为收到的计划/意见/论文；data/raw 为不修改原件；data/provenance 为来源/映射/证据；data/derived 为审计输出；configs 为实验配置；src 和 tests 为程序；runs/development 为实测开发运行；runs/unit_only 仅程序夹具；figures 为后续真实图件；manuscript 为后续英文论文。大量原数据和运行文件被 git 忽略，保留于云快照，公开前另定有许可的数据存储方案。

## 收到材料后

1. 原封不动保留包和原始文件，分别算 SHA256。不要执行附件中的脚本，先阅读其内容并比对本项目规范。
2. 阅读计划和中文说明，确认表头、日期格式、QA 值、目标/单位/流量点及来源许可。将实际证据录入 SOURCE_REGISTRY.csv。
3. 复制并填写 configs/audit.template.json 为独立真实配置，不覆盖模板。当前审计入口支持显式 CSV；其他格式须先按实际说明编写无损适配，不能猜表头或 Excel 单位。

```bash
python3 -m wastewater.audit --raw data/raw/ACTUAL_FILE.csv \
  --config configs/audit.ACTUAL.json --output data/derived/UNIQUE_AUDIT_ID
```

输出保存逐行规则、异常/折叠原记录、站点级每日候选、汇总和输入/config/code hashes。`daily_candidates.csv` 不是最终物理设施队列；需按映射再次审查。

开发入口要求候选表与同目录已完成审计的 manifest hash 一致；不得手工修改派生表后绕过审计。修改处理规则应重新审计并产生新版本。

4. 审核设施证据，为开发子集另写 `data/provenance/DEVELOPMENT_MAPPING.csv`，字段同 FACILITY_MAPPING.csv；所有行 role=development、mapping_reviewed=true，每厂一个经过核实的出水站点。完整映射可含 source/final，但开发入口禁止直接传完整表。
5. 写明独立证据：出水日体积语义、运行时原观测发布时间约定、站点-设施关系。若数据只提供年报快照，用固定延迟模拟只能解释为回顾性情景，不能称部署已验证。没有证据不要将 reviewed 改为 true。
6. 复制并填写 development.template.json，指定真实部署日和相同评价窗口；设置独立映射和证据路径。

```bash
python3 -m wastewater.development --config configs/development.ACTUAL.json
```

每次新建运行目录，失败不覆盖。退出 0：该运行完成且每配置至少 28 共同日期、岭训练≥14 合法 label；退出 2：不足以满足开发可行性门槛，结果仍保存；其他非零：失败，查看 manifest/run.log/failure.txt。文件里的阶段标签必须真实，禁止把生成夹具移进实测目录。

## 已实现与未实现

已实现：显式 CSV 审计、日历、原观测与回顾性真值分离、单设施固定拟合的持续性/周季节/岭回归、共同日期、逐厂 MAE/RMSE/相对改善、等权厂汇总、覆盖/训练记录、运行追溯。

未实现/未运行：实际附件适配及审计复核、多测点设施聚合、共享训练/偏差、最终冻结/测试、缺测敏感性、相关性 bootstrap、区间、绘图、论文编译/Overleaf ZIP。不要用当前开发接口产生最终结论。

上述为初始实现清单。更新：实际附件CSV适配/审计复核、站点开发与真实结果绘图现已执行；共享/区间/最终仍未运行。物理厂门槛仍严格，新增station_exploratory仅供明确标记的回顾开发。

## 来源核查重试

```bash
python3 scripts/check_sources.py --output literature/access_attempts/NEW_UNIQUE_ATTEMPT
```

此命令保存有 TLS 校验的响应、URL/hash 和失败状态；HTTP 200 只代表获取文件，须阅读后才升级证据层级。失败返回 2 并保留日志。不能根据未读全文的标题填实验细节；先查 literature/REVIEW.md 中的实际核查进度。

## 本阶段已实际运行的重跑顺序

原包58文件由交接包的 `import_and_verify.py` 导入。首次应同时传Part1/Part2；已导入时只验证，不覆写。原脚本与manifest在已收到的Part3中；不要在原文件夹执行audit_data.py覆盖参考派生表。

```bash
cd /workspace/Wastewater_Paper
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
export XDG_CACHE_HOME="$PWD/.cache"
bash scripts/check_environment.sh
python3 -m wastewater.audit --raw wastewater_data/raw/wessex_all_2016_2025.csv \
  --config configs/audit.wessex_20261009.json --output data/derived/NEW_UNIQUE_AUDIT
```

已有本阶段审计 `data/derived/wessex_audit_20261009` 可复用；重审输出必须新目录，并用新版本配置明确指向新canonical。不要覆盖现有数据或改变报告引用的配置。

```bash
python3 -m wastewater.development --config configs/development_20261009/smoke.json
python3 scripts/run_development_batch.py --manifest configs/development_20261009/batch_manifest.json
# 从新batch输出读取真实BATCH_INDEX路径，不把旧结果冒充新运行。
python3 scripts/summarize_development.py --batch-index runs/development/batches/NEW_BATCH/batch_index.json \
  --output reports/NEW_UNIQUE_REPORT
python3 scripts/plot_development.py --report reports/NEW_UNIQUE_REPORT --output figures/NEW_UNIQUE_FIGURES
```

报告中的本阶段原batch为 `20261009T061109Z_fe9d2301`。新汇总/图目录必须新建。汇总包含重复运行/hash/时点/预算/QA合法真值检查；原smoke路径若存在则核对对应真实结果一致。站点探索配置使用未核实station:ID键和显式离线delay模式；不伪造物理审核和实时可用性。

## 2026-10-10：QA-v3共享和单一GRU的实际可续跑入口

本轮真实结果已完成：full为960任务、三种子、201600行，smoke96任务单列。先读reports/shared_v3_20261009/ANALYSIS.md。下载Code_Data、所有Runs、Reports_Figures包到同一新项目根目录；Colab importer校验每包SHA256SUMS后不抽取清单，拒绝冲突覆盖。原百万行raw不随此轮包重复提供，QA-v3派生足够模型复现；重做原审计仍需原用户Part1/2包。

```bash
bash scripts/refresh_stage2_environment.sh
source .venv-stage2/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export MPLCONFIGDIR="$PWD/.cache/matplotlib"
# 已有任务校验hash并读取缓存；不删原任务、不改变配置强行混跑。
python -m wastewater.shared_experiment --config configs/shared_v3_20261009/smoke.json
python -m wastewater.shared_experiment --config configs/shared_v3_20261009/full.json
python scripts/validate_stage2.py --run runs/shared_v3_20261009/full --output validation/NEW_REAL_CHECKS.json
python scripts/check_stage2_models.py --help
python scripts/check_stage2_metrics.py --report reports/shared_v3_20261009 --output validation/NEW_METRIC_CHECKS.json
# 汇总及图件拒绝覆盖已有目录；重算必须使用新路径。
python scripts/summarize_shared_v3.py --run runs/shared_v3_20261009/full --output reports/NEW_SUMMARY
python scripts/plot_shared_v3.py --report reports/NEW_SUMMARY --output figures/NEW_FIGURES
```

首种子单独入口为`--seeds 20261009`；补种子使用完整3seed配置入口，以缓存首种子且保存全部来源诊断。所有epoch保存模型和优化器，代码/数据/设置/torch签名不匹配拒绝续跑。模型不能用未来目标早停，部署只更新允许新观察的特征。CPU已实际完成全规模，不需GPU；Colab notebook与配套README在notebooks中。真实Drive挂载未经认证。

实际检查：37软件测试；真实时间/预算/QA/共同日期校验；6源+720本地+720适应checkpoint逐项核对；960指标行和72比较点独立从保存预测重算。负值和负迁移都保留。三核心版本、数据、配置、图件、中文结论追溯见manifest与claim_traceability_v3.csv。`write_stage2_analysis.py`只为本版已核查结果生成说明，不能用于自动解释新方案。

## Stage 3A CPU diagnostics (completed; await review)

Read STAGE3A_PROTOCOL.md, STAGE3A_IMPLEMENTATION.md and reports/stage3a_20261010/ANALYSIS_ZH.md. Commands and immutable config live in those files. Core modules stage3a_data/training/experiment import frozen Stage 2 helpers without changing them. The previous source-only preflight failures remain preserved. Scientific code fingerprints reject changed data/config/initial weights. Use process workers, not threads sharing Torch RNG.

Independent check: `PYTHONPATH=src .venv-stage2/bin/python scripts/check_stage3a_results.py`. Plot source is saved tables, not hand-edited data. Replaying a run can update its run manifest; retain original archives/receipts and use a separate extracted ROOT for replay. Never run the Stage 2 runner in place when preserving its frozen manifest.

New ZIP parts plus the three original Stage 2 archives support clean reconstruction; see delivery instructions and notebooks/Wessex_Stage3A_CPU.ipynb. Current scientific outputs are complete. Do not automatically run Stage 3B, intervals, source expansion, final tests or apps.

## Stage3B frozen CPU round and read-only review

ReadSTAGE3A_EVIDENCE_AUDIT.md andSTAGE3B_PROTOCOL.md. Acceptedconfigconfigs/stage3b_20261011_v1/full.json,300conditionsalreadycomplete. Never rerunolderStage2/3A entrypointsinplace. Fornew-root review: `PYTHONPATH=src .venv-stage2/bin/python scripts/recalculate_stage3a_delivery.py --output outputs/recomputed_stage3a`, then `PYTHONPATH=src .venv-stage2/bin/python scripts/check_stage3b_results.py --arithmetic-only --output outputs/STAGE3B_CHECK.json`.

AuthorizedStage3Bcache-onlyresumer: setOMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1 andPYTHONPATH=src, run `.venv-stage2/bin/python -m wastewater.stage3b_experiment --config configs/stage3b_20261011_v1/full.json --workers 2`. Thisupdatescallmetadataandrawaggregate schema; follow with `.venv-stage2/bin/python scripts/summarize_stage3b.py` torestoreevaluatedcolumns/manifests. Itdoesnotrefitcompletehash-matchingjobs. Saferread-onlyreview usesonlyrecalculationinnewoutputdirectories. Code-onlysmallfrom-scratchreplayandDrivepersistence seeREPRODUCE.md/notebook;liveDriveunverified. Stopafterthisround.


## Stage3C.1 read-only replay and STOP (2026-10-12)

Readreports/stage3c1_20261011_v1/FEASIBILITY_ZH.md,RAINFALL_CONNECTION.md andREPRODUCE.md. The delivered sample supports independent rainfall/receipt/field checks without downloading new data or fitting models. Use a new extracted root and new output directories, never overwrite original evidence. The186-candidate raw audit additionally requires the user original CSV at its recordedSHA256; the small package explicitly omits that full input. Full Stage3B preservation verification requires the original checkout, not just the small feasibility package.

Current-root example:

```bash
.venv-stage2/bin/python -m unittest discover -s tests -p test_stage3c1.py -v
.venv-stage2/bin/python scripts/stage3c1_rainfall_check.py --root "$PWD" --output outputs/stage3c1_NEW_raincheck
```

Next experimental config remainsblocked/non-executable. Do not run Stage3B/GRU in place or invoke new forecasting based on metadata completion.2023Oct is used development;2024–2025 performance is still excluded. Stage3C.1 ends at delivery and review.

## Stage3C2 completed CPU replay and STOP

Readreports/stage3c2_source_scale_v1/REPRODUCE.md. Actual entrypoint: `python -m wastewater.stage3c2_experiment --config configs/stage3c2_source_scale_v1/full.json --mode k3-check|smoke|full|resume --workers 2`, followed by `python scripts/summarize_stage3c2.py --config configs/stage3c2_source_scale_v1/full.json --run runs/stage3c2_source_scale_v1/full --output NEW_OUTPUT`. SetPYTHONPATH=src andOMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1; pinnedCPUvenv. Recreate realK3 gate usingcheck_stage3c2_k3.py before expansion. Use new extracted roots, since continuation updates invocation metadata. Partialexit3; cache requirescomplete fingerprints/artifactSHA. Omitted fullraw/historic scan dependencies named; source model inputQA and small smoke self-contained. This scientific round is complete: do not autoexpandK/model/grid/windows, weather, final tests, paper or App.


## Stage3D completed (2026-10-12)

User-authorized post-C2 empirical interval development, stage3d_interval_v1: fixed Persistence centre, three frozen K30 pools, 1080 source folds/18 source-only gamma choices, 300 target conditions/324000 interval rows, no software/calibration failures. Source scales/errors for selection end2020; held-source pseudo2021; final source error libraries end2021. Initial B30/90/180 calibration freezes60origins; all evaluation remains2022–2023 used development. Published QA and unverified SiteID mapping retained. Main B30/order20261012/90% MIXTURE-vs-LOCAL skills +2.6407% h1, +2.1222% h3; both Bonferroni97.5%14-day intervals cross0. Coverage improvement costs wider intervals; no established history saving or stable shared-interval contribution, and C2 point-forecast conclusions unchanged. 40tests, full independent reconstruction, exact C2 byte preservation and 300-task cached resume passed. See STAGE3D_PROTOCOL.md, reports/stage3d_interval_v1/ANALYSIS_ZH.md and RUN_STATUS.json. STOP for review; packaging validation separately recorded in delivery/20261012_stage3d/PACKAGE_CHECKS.json.


## Stage3E实际CPU复核入口与STOP

最小软件复算（先用新的解压目录，保留原D）：

```bash
export PYTHONPATH="$PWD/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
.venv-stage2/bin/python -m unittest discover -s tests -p 'test_stage3e*.py' -v
.venv-stage2/bin/python -m wastewater.stage3e_runtime --mode smoke
.venv-stage2/bin/python scripts/check_stage3e_runtime.py --scope smoke
.venv-stage2/bin/python -m wastewater.stage3e_runtime --mode resume
```

完整新诊断重算需按INPUT_MANIFEST补齐原D逐条结果，命令见reports/stage3e_evidence_review_v1/REPRODUCE.md；根独立证据核验scripts/check_stage3e_evidence.py不导入新诊断算法，仅原始评分/primitive重采样。Code包支持实际小规模软件复算，原大D预测只按原SHA关联，不能称无需外部依赖的全量复现。只在收到明确复核授权后调用已完成流程，不自动新训练或最终测试。自然9RUNNING未复现、原因未确认。当前唯一下一行动是补工程元数据与首次可用时点，NEEDS_DATA/STOP。


## Stage3F资料和交付复核

阅读reports/stage3f_evidence_gate_v1/NEXT_ACTION.md、requests/EVIDENCE_GATES.csv、REPRODUCE.md。标准库工具仅核元数据范围/来源/补件CRC-SHA，没有重新运行科学工作流。旧原件不可变地址/大小/SHA在delivery_chain/IMMUTABLE_DOWNLOADS.csv，CODE_CONTENT_AND_COMMIT.json关联真实E/C2提交及Code容器成员，不用基础HEAD代替科学版本。资料缺失时状态WAITING_FOR_EXTERNAL_EVIDENCE，不自动做新的性能分析、最终测试、付费训练或对外联系。
