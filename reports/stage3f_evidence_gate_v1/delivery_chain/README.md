# Stage3E 原交付链补件（Stage3F，只读核对）

本补件对应已经完成的 `stage3e_evidence_review_v1`，原交付提交为 **d7eda982a91084a3b875e351de1e91dae0e5cacf**。不是新的区间实验，也没有重生成旧科学结果、旧预测或旧ZIP。Stage3F仅补交付链与资料门槛。

用户指出的缺件在仓库中真实存在：原 `ARTIFACT_INDEX.json`、**完整实际交付** `PACKAGE_CHECKS.json`、`POST_PACKAGE_PRESERVATION.json` 当时位于三个ZIP以外，因此只收到三个ZIP无法看到它们。本包 `original_stage3e_receipts/` 保存它们的**逐字节原件**、原SHA清单、原完成记录、原代码版本及四份真实干净重放日志。`ORIGINAL_COPIES.json` 给出原路径、SHA和可用的不可变提交链接。这里不将受控夹具 `PACKAGING_HELPER_CHECK.json` 当作全部实际交付的检查。

此次只读核对实际检查原三个E包、原C2 Part01/02的容器SHA、CRC和全部成员SHA，并与本地实际Git提交对象字节比较。代码版本同时登记内容SHA、真实交付提交、该提交中的Code ZIP及具体成员路径；基础 `work` HEAD并不包含全部未跟踪科学文件，不能单独表示完整代码版本。详见 `DELIVERY_CHAIN_CHECK.json`、`CODE_CONTENT_AND_COMMIT.json`。这些检查不会重做20项软件测试、12条件冷启动或任何bootstrap。它们引用的既有干净重放日志来自原Stage3E，而不是本阶段重新运行。

外部复核的数量和结果是用户提供的参考，不是本程序的通过判据。当前仓库中的原件已只读核实；外部尚未收到的C2容器仍不能声称已经被外部独立审查。带`(1)`的外部重复ZIP及原Reviewer Evidence ZIP不在当前项目内。补件中的不可变Git地址是实际本地提交对应的地址，本轮没有重新测试远端HTTP下载。

## 外部缺少的原C2 Part01/02

原件未变、未重生成。直接下载原C2交付提交中的容器：

| 原文件 | 字节数 / MiB | SHA256 |
|---|---:|---|
| `Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part01.zip` | 23057568 / 21.9894 | `396662672038a7221f062c1f1e43aa56a26770379244db788a13a2cf1f0226a8` |
| `Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part02.zip` | 21943829 / 20.9273 | `4a81e3b7d7413008754f3d286606c51980700163830ee104f6027a13a2fbf805` |

[原Part01](https://github.com/jiangsunyu7-ux/Wastewater_Paper/raw/f33e38a8d28bf3206989794240cc35e63d62f017/delivery/20261012_stage3c2/Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part01.zip)

[原Part02](https://github.com/jiangsunyu7-ux/Wastewater_Paper/raw/f33e38a8d28bf3206989794240cc35e63d62f017/delivery/20261012_stage3c2/Wastewater_Stage3C2_Predictions_and_Diagnostics_20261012_Part02.zip)

`ORIGINAL_C2_MISSING_EXTERNAL_PARTS.csv` 同时列出d7eda982提交中**完全相同容器字节**的替代下载地址。本小包不重复装入两个大ZIP。不能将小补件本身称为包含完整C2预测。

## 完整复现依赖的边界

`IMMUTABLE_DOWNLOADS.csv`列出原E交付、实际检查凭证、原C2五个包及原D五个包的大小、SHA和实际提交下载地址，并逐项区分本轮检查范围。

原C2完整审查需原Quick/Code和三个Predictions分包，不能只取Part01/02。原C2 Code包含小规模训练和指标验证的必要已清理输入；从零重建186候选资格另需原73,570,225字节全量CSV，SHA256为`22f494e2b96fe6fa9550c68971d50c752ddd291793fdc60334d64b2ef089f518`及历史登记，未放入本小包。参见未改写的 `original_dependencies/STAGE3C2_REPRODUCE.md`。

全部Stage3E诊断从原D预测重算，依赖原D三个预测诊断分包中的逐条预测、损失和300任务校准记录。`STAGE3E_FILE_DEPENDENCIES.csv`及原样保存的 `original_dependencies/STAGE3E_original_D_INPUT_MANIFEST.json`逐文件列出624项输入SHA。没有这些输入时可以读现有表和验证本补件，但不能声称全量独立复现。此阶段不执行上述旧科研复现命令。

## 核验命令

无需科学依赖，只用Python标准库。解压补件后，检查下载的实际ZIP：

```bash
python verify_supplement.py /path/to/Wessex_Stage3E_Delivery_Supplement_20261013.zip \
  --expected-sha256 <STAGE3E_SUPPLEMENT_PACKAGE_CHECK.json中的sha256>
```

已有完整本地仓库和原容器时，可将只读核对输出写到独立新文件：

```bash
python verify_delivery_chain.py --repo-root /path/to/Wastewater_Paper \
  --output /tmp/stage3f_delivery_chain_recheck.json
```

这两条命令都不训练、校准、评价预测性能或访问最终数据。本包的实际容器CRC/成员SHA检查记录另附 `STAGE3E_SUPPLEMENT_PACKAGE_CHECK.json`，不会与旧实际PACKAGE_CHECKS或夹具记录混淆。
