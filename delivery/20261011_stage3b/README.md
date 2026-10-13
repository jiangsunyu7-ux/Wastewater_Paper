# Stage3A evidence audit + Stage3B delivery (2026-10-11)

已完成Stage3A独立证据核查和stage3b_20261011_v1的300/300条件；保留旧科学文件。CPU执行，无新增GRU训练、最终2024–2025性能、区间模型或App。8个ZIP均已通过CRC、逐文件SHA256、干净导入；最大20.11MiB。

## 下载

点击文件名下载。若GitHub显示预览页面，请点Download raw file；私有仓库需使用具有当前仓库权限的登录账号。

| 文件 | 大小(MiB) |
| --- | ---: |
| [Quick_Review](Wastewater_Stage3B_Quick_Review_20261011.zip?raw=true) | 3.313 |
| [Code_and_Reproduce](Wastewater_Stage3B_Code_and_Reproduce_20261011.zip?raw=true) | 1.701 |
| [Predictions_and_Diagnostics_Part01](Wastewater_Stage3B_Predictions_and_Diagnostics_20261011_Part01.zip?raw=true) | 17.299 |
| [Predictions_and_Diagnostics_Part02](Wastewater_Stage3B_Predictions_and_Diagnostics_20261011_Part02.zip?raw=true) | 8.321 |
| [Predictions_and_Diagnostics_Part03](Wastewater_Stage3B_Predictions_and_Diagnostics_20261011_Part03.zip?raw=true) | 15.330 |
| [Predictions_and_Diagnostics_Part04](Wastewater_Stage3B_Predictions_and_Diagnostics_20261011_Part04.zip?raw=true) | 20.111 |
| [Predictions_and_Diagnostics_Part05](Wastewater_Stage3B_Predictions_and_Diagnostics_20261011_Part05.zip?raw=true) | 17.338 |
| [Predictions_and_Diagnostics_Part06](Wastewater_Stage3B_Predictions_and_Diagnostics_20261011_Part06.zip?raw=true) | 3.623 |

[SHA256SUMS](SHA256SUMS?raw=true) · [包完整性检查](package_checks.json) · [中文分析](ANALYSIS_ZH.md) · [复核与续跑命令](REPRODUCE.md) · [主结果图PDF](primary_b30_persistence_intervals.pdf?raw=true)

完整复核请下载全部8包，再按REPRODUCE校验导入一个新目录。Quick_Review仅供阅读；不能用它声称独立复现全部训练。Code包含必要QA数据、来源原记录摘录、代码、测试、配置及notebook；预测/诊断6Part保留完整Stage3A预测、关键轨迹和Stage3B证据。省略的旧权重/全原始库明确列在Code包的OMITTED_DEPENDENCIES.json。

## 主要发现

预先指定B30共享残差Ridge+bias+合法验证选lambda：h1全部回退Persistence，技能0；h3原窗口-4.17%（97.5%区间-16.27至+2.82%），追加窗口+5.04%（-6.35至+10.61%）。尚无稳定超过Persistence的主要证据。相对强本地残差模型仍有负迁移，历史效率依赖参照与窗口。追加窗口是同一SiteID的时间验证，现在已使用，不是独立物理设施外部验证。

Stage3A核验未发现改变结论的错误；完整GRU优化训练未重做。公开QA、物理设施/排口身份和实时数据到达仍未验证。目标期刊未确认。固定轮次完成后停止，等待用户审查。

## 复核范围

交付版本与代码内容哈希见CODE_VERSION.json；底层Git初始HEAD不能冒充含科研源码的代码提交。环境55项测试通过，12主要区间独立重算通过。打包后独立指标重算和Code-only小规模重训记录将随本次交付提供。实际Colab/Drive登录未测试。

```bash
export PYTHONPATH=src
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
.venv-stage2/bin/python -m wastewater.stage3b_experiment --config configs/stage3b_20261011_v1/full.json --workers 2
.venv-stage2/bin/python scripts/summarize_stage3b.py --config configs/stage3b_20261011_v1/full.json --predictions reports/stage3b_20261011_v1/results/predictions_all.csv.gz --output outputs/recomputed_stage3b
```

只在新导入审查目录续跑。runner验证已完成缓存并重建原始聚合预测；后续summarize在新输出目录重算指标。不要在原工作区覆写旧结果。

## 实际外部复核记录

[干净目录指标重算](STAGE3B_CLEAN_METRIC_REPLAY.json)：388800条Stage3A与198000条Stage3B预测独立重算，全部15张Stage3B输出表逐列核验通过。

[Code-only新训练](STAGE3B_CODE_ONLY_FRESH_SMOKE.json)：源模型从零拟合，13013/13015的12条件重新训练，7920行预测归一化最大差0，alpha/lambda及选择参数逐项相同。

[缓存续跑](STAGE3B_CODE_ONLY_RESUME_CHECK.json)：12条件全部缓存，112缓存成员哈希不变，无重复拟合。[55项环境测试](environment_refresh_and_final_tests.log)、[主要区间独立复算](PRIMARY_INTERVAL_INDEPENDENT_CHECK.json)、[旧成果保留检查](PRESERVATION_CHECK.json)均通过。实际重算/新训练脚本、日志随目录提供；不宣称所有旧GRU优化训练从头重现或真实Drive登录测试。

[整个交付目录校验清单](DELIVERY_SHA256SUMS?raw=true)覆盖所有文件（自身除外）；ZIP内各有MANIFEST与SHA256SUMS。
