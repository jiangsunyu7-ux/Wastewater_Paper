# Wessex Stage3D verified delivery

本交付包含**新Stage3D**与**原Stage3C2字节重交**两组文件，外层名称不同。

Stage3D已完成300条件、324,000条经验区间；三套原K30源组合、三预算、两时距、80%/90%均保留。所有中心为原Persistence，不是新的点预测模型。

B30主MIXTURE相对LOCAL技能为h1 +2.64%（调整97.5%区间−2.23%至+7.35%）、h3 +2.12%（−4.65%至+9.36%）。两项区间均跨零；覆盖改善伴随宽度成本，不支持稳定区间创新或普遍历史节省。详见[中文分析](ANALYSIS_ZH.md)。

## 新Stage3D下载

| 文件 | MiB | SHA256 |
|---|---:|---|
| [Wessex_Stage3D_Quick_Review_20261012.zip](Wessex_Stage3D_Quick_Review_20261012.zip?raw=true) | 8.40 | `a23f50ac2714b10741156fbafe39ab70f89be6b133d5fe638ab92ae57efab8c2` |
| [Wessex_Stage3D_Code_and_Reproduce_20261012.zip](Wessex_Stage3D_Code_and_Reproduce_20261012.zip?raw=true) | 6.62 | `7ef5c0dcb15e0bf63b37f9ab3e7687ecea711a6c8b7db6aac2b130d4481422c7` |
| [Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part01.zip](Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part01.zip?raw=true) | 22.00 | `e72c5e7cafde1a11b7abac50dc71fc9f7efa85f91a657db8a203d7c3b3f4a0e4` |
| [Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part02.zip](Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part02.zip?raw=true) | 19.55 | `f88f6ca7de3a975ed6bf6ebd9e68c41dad0a8a79af0d5697359b91473aa9ef1e` |
| [Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part03.zip](Wessex_Stage3D_Predictions_and_Diagnostics_20261012_Part03.zip?raw=true) | 13.78 | `fff490f6f0fbdc7277fdd683b0d61dacc8e8b4ec7b9977a549718178cbd5fe74` |

完整复核需将**所有新D包（包括全部预测诊断分包）**解压到同一个新目录。Quick仅便于阅读，不能替代逐条预测。每卷是独立ZIP，不是需额外解卷工具的字节切片。每包内均有成员SHA清单；不同SHA的同名文件会被拒绝覆盖。

## 原Stage3C2重交

以下五个文件只改外层名称，容器SHA与旧包完全相同。原Part01、Part02在仓库中存在且已核验，**没有重新生成原预测**。原预测诊断仍需Part01、Part02、Part03三个包。

| 原文件的唯一重交名称 | MiB | 原容器SHA256 |
|---|---:|---|
| [Wessex_Stage3C2_Original_Quick_Review_Reissued_20261012.zip](Wessex_Stage3C2_Original_Quick_Review_Reissued_20261012.zip?raw=true) | 3.38 | `6f34f6704e78b719d10229f0431f731bfcecf768f4e9359db5441483c70d2d43` |
| [Wessex_Stage3C2_Original_Code_and_Reproduce_Reissued_20261012.zip](Wessex_Stage3C2_Original_Code_and_Reproduce_Reissued_20261012.zip?raw=true) | 11.30 | `7ad78fc45809e932a3df4fdb77dfea561b0acb3f5747c2a41ba818b41e110ab2` |
| [Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part01_Reissued_20261012.zip](Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part01_Reissued_20261012.zip?raw=true) | 21.99 | `396662672038a7221f062c1f1e43aa56a26770379244db788a13a2cf1f0226a8` |
| [Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part02_Reissued_20261012.zip](Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part02_Reissued_20261012.zip?raw=true) | 20.93 | `4a81e3b7d7413008754f3d286606c51980700163830ee104f6027a13a2fbf805` |
| [Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part03_Reissued_20261012.zip](Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part03_Reissued_20261012.zip?raw=true) | 2.85 | `1d1d101f04f0bd4f5d339aa7cbb96583c95a2b49ce6cb6e8e55e4d45e6113bd6` |

原/新名称、完整ZIP成员SHA在[C2_ORIGINAL_REISSUE_MANIFEST.json](C2_ORIGINAL_REISSUE_MANIFEST.json)；每个原包另附`.members.SHA256SUMS`。这些是旧C2内容，与新D包分开解压。

## 核验及复现

[SHA256SUMS](SHA256SUMS)列所有外层文件；[PACKAGE_CHECKS.json](PACKAGE_CHECKS.json)记录实际CRC、成员SHA、干净目录命令和范围。

Code-only已冷建三源库/1,080伪部署折/18gamma，再冷跑原两个smoke测点12条件；合并D完整包后核验300缓存任务并重算全部指标及独立CDF/区间/评分/主要Bootstrap。冷smoke与缓存全量复算是不同范围，没有声称打包阶段冷跑全部300条件。

安装与入口见[REPRODUCE.md](REPRODUCE.md)。已完成根目录可校验续跑：

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=src \
.venv/bin/python -m wastewater.stage3d_experiment \
  --config configs/stage3d_interval_v1/full.json --mode resume --workers 1
```

所有五窗是已使用开发历史；physical_mapping_verified=false，观测/QA实时到达未核实。经验区间无conformal、有限样本或条件覆盖保证。原全raw和旧186候选历史资格的完整重建属于外部依赖，SHA及范围已列明；新区间冷源/smoke和指标重算输入自包含。

2024—2025预测性能及临时保护组未启用；没有雨量、GRU扩展、模型组合、App、论文或付费GPU。本轮结束并停止，等待审查。
