# Wessex Stage3E — 2026-10-13

**本目录是新增 Stage3E 可靠性与证据审查，不是旧 Stage3D ZIP 改名。**

版本：`stage3e_evidence_review_v1`。所有新包通过 CRC、成员 SHA 和干净目录软件复现；
旧 D 科学结果、源池、gamma 与原始区间不变。完整大 D 预测只按原 SHA 关联，不重复打包。

[中文分析](ANALYSIS_ZH.md) · [唯一下一行动](NEXT_STAGE_DECISION.md) · [相对 D 的变化](DELTA_FROM_STAGE3D.md) · [复现命令](REPRODUCE.md)

| 新 Stage3E 包 | MiB |
|---|---:|
| [Wessex_Stage3E_Quick_Review_20261013.zip](Wessex_Stage3E_Quick_Review_20261013.zip?raw=true) | 6.38 |
| [Wessex_Stage3E_Code_and_Reproduce_20261013.zip](Wessex_Stage3E_Code_and_Reproduce_20261013.zip?raw=true) | 20.33 |
| [Wessex_Stage3E_Diagnostics_20261013_Part01.zip](Wessex_Stage3E_Diagnostics_20261013_Part01.zip?raw=true) | 4.73 |

将所有新 E 包解压到同一新目录。Code 包可独立执行有限软件修复检查；
完整新诊断重算另需原 D 逐条输入，路径和 SHA 见 INPUT_MANIFEST 与 REPRODUCE。

**另附旧 C2 原件，以下两包不是新 E 结果：**

- [Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part01_Reissued_20261013.zip](Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part01_Reissued_20261013.zip?raw=true) — 原字节、21.99 MiB
- [Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part02_Reissued_20261013.zip](Wessex_Stage3C2_Original_Predictions_and_Diagnostics_Part02_Reissued_20261013.zip?raw=true) — 原字节、20.93 MiB

[ARTIFACT_INDEX.json](ARTIFACT_INDEX.json) 保存阶段/配置/代码/每包及成员 SHA；
[PACKAGE_CHECKS.json](PACKAGE_CHECKS.json) 保存实际复现范围；
[SHA256SUMS](SHA256SUMS) 包含其余交付文件的校验值。

自然九 RUNNING 异常未复现、根因未知；受控故障防护不冒充自然复现。
结论仍为未证明稳定共享获益；物理设施独立性和实时时点未知。
本轮完成后停止，唯一下一行动为 NEEDS_DATA，未自动开最终测试或新训练。
