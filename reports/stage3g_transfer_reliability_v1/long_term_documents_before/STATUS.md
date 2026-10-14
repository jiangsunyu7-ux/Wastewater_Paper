# 项目进度

**最新状态（2026-10-13）：Stage3E运行防护、既有结果独立重算和论文证据审查已完成；交付复核另列PACKAGE_CHECKS。未训练新预测模型，未计算最终2024—2025或保护测点性能。两项主要区间评分调整区间仍跨零。唯一下一行动C：NEEDS_DATA；本轮完成后停止。后续内容保留历史。**

**最新状态（2026-10-09，收到拆分包后）：已完成真实数据导入核验、独立审计及首批开发基线。当前不支持共享收益结论；正式设施映射、历史时点、共享/区间和最终测试仍待完成。详情见末尾续跑记录及 reports/development_20261009/RESULTS.md。**

## 2026-10-09：最初启动阶段（以下保留历史记录）

**阶段状态：部分完成，真实数据实验被附件传输限制阻塞。当前没有科研结果，不可判断是否值得继续跨厂实验。**

### 已查证

- 当前仓库原始 main 只有 README.md，起始 HEAD e6a4fc628d8aae0412cb83a81c528b43d6662fea。未找到原有 AGENTS/研究/协议/状态文件；新建这些文件以保留总需求。
- Linux x86_64，Python 3.12.14，5 CPU，约 32 GiB 可用内存；未检测到 GPU 设备或 nvidia-smi。numpy 2.3.5、pandas 2.2.3、scipy 1.17.0、scikit-learn 1.8.0、matplotlib 3.10.8 已可导入；pdflatex 为 TeX Live 2025/dev。当前任务不需要 GPU 或安装复杂工具。
- 附件下载工具返回 `file exceeds the executor transfer limit of 32 MiB`。附件未读取/解压/计算 SHA256；无法核对实际表头、数据行数或 plan 2.0 内容。
- Crossref 三 DOI 和 IWA 两候选期刊 About/Author_Guidelines 请求均为 tunnel 403。只是网络访问失败，不能解释为论文/DOI/期刊不存在。
- 已将 api.crossref.org、api.openalex.org、doi.org、www.sciencedirect.com、onlinelibrary.wiley.com、iwaponline.com 保存到环境配置网络草稿。保存不代表当前网络已应用或环境已发布。

### 本阶段交付与边界

- 长期规范、研究方案和未冻结最小协议；审计主张表、工程用途边界、停止/收缩判据。
- 文献证据表中只放用户提供的标题/DOI和未核实状态，不填猜测的实验方法或发现。无前作可比较。
- 数据审计及明确开发集基线入口、关键程序测试；测试夹具不是污水实验，不输出科研结果图或完整论文。
- 运行结果与验证记录将追加到本文件；尚无首批真实持续性/季节持续性/岭回归结果。

### 需要的材料与操作

1. 将附件拆为各 <32 MiB 的独立 ZIP，或分别上传计划、数据说明/审计表和 Wessex 文件；也可提供可访问的直接下载链接。不要拆成工具无法独立读取的仅有二进制卷而不提供重组说明。
2. 在环境设置中检查、保存配置草稿并发布环境。Crossref/OpenAlex 后续请求已成功，IWA 指南和其他出版社请求仍被拒；不要求重复添加已保存域名，也不请求尚未证实必要的新密钥。若用户提供论文全文/当前作者指南可先离线核查。
3. 到达后保留原件/算 hash，读取文档/原脚本；对照用户审计数值并明确来源许可、出水语义、设施身份及发布时间。
4. 先运行完整审计，再人工确认 development 清单与信息时点约定，实际运行三个基线，回填真实结果/可行性决策；不选最终测试模型。

### 尚未完成

数据审计复核、全文/摘要核实、最新相关文献、官方作者指南、独立物理设施映射、真实开发基线、跨厂收益判断、冻结、最终实验、真实论文图件、英文完整初稿、Overleaf ZIP。pdflatex 可用不等于论文已编译。

### 程序验证记录（不属于科研实验）

已在当前机器执行 `bash scripts/refresh_environment.sh`，现有固定版本依赖足够，无需新增安装。`bash scripts/check_environment.sh` 实际执行 21 项 unittest，全部通过；日志保存在 validation/software_checks.txt。

测试涵盖：保留缺失日、预算左边界、horizon/延迟训练标签、未来数据不改拟合、训练不使用事后 QA、周季节日期、缺失目标排除、共同日期与手算指标、零误差基线相对改善未定义、持续性陈旧观测限制、训练缩放、Good 负值/Missing 非零/冲突/重复、无效数值、最终配置和未审核映射拒绝、开发子集读入。

CLI 集成测试用临时人工夹具跑通审计→三基线→逐设施/等权指标，检查原件 hash 不变、结果 hash、重复预测一致与失败状态留存。临时夹具不作为实测保存或展示；保留测试日志。本阶段没有真实预测文件、误差数值、科研曲线或统计显著性。

额外修正并验证：CSV nullable 字符串的缺失数值须转为浮点 NaN 再做有限性判断，否则可能漏记异常。审计使用批量分组判断同站同日冲突，避免对接近百万日组逐一建立 DataFrame。开发 manifest 继承审计 raw/config/code chain，并验证派生数据 hash；人工编辑派生数据后必须重新审计。

### 后续来源核查和配置保存

- 通过实际 HTTP 200 读取 Crossref/OpenAlex，核实三个指定 DOI 与四个新增原始研究的书目元数据；总计四个出版社登记摘要已读、零全文。两篇指定的 Elsevier 2024 论文尚未取得摘要。EVIDENCE_TABLE.csv 记录层级，不填未知方法。
- 最接近的新发现：2024 年 KSEE 文献已研究两厂 discharge/BOD 迁移，摘要仅报告轻微/无改善（按策略）。研究不能主张“首次”；潜在增量必须通过独立设施、预算完整性和负迁移证据实现。详细证据、版本和查阅 SHA256 见 literature/REVIEW.md 与 access_attempts。
- IWA 官网 HTTP 403，当前作者指南和范围未核实；Wiley/Elsevier/出版商主站有 egress 403。第二个 Crossref 搜索曾返回 429，未循环重试；改用已可访问的 OpenAlex 查找，再单篇 Crossref 核实。
- 已保存 `install_script`（调用经过实际执行的 refresh_environment.sh）、`start_skill`（已有 checkout、必要激活/PYTHONPATH/缓存、软件 readiness、资料与最终隔离边界）和研究来源网络域名。后续补加 api.elsevier.com、agupubs.onlinelibrary.wiley.com、www.iwapublishing.com、iwapublishing.com；保留已有六个域名及平台 presets。配置保存返回 status=saved、requires_publish=true；没有声称已发布或验证新任务恢复。
- 无第三方研究技能包或模型工具被采用或整包安装；当前程序仅用环境中固定版本科学库与标准库。

## 2026-10-09：收到三个拆分包后的真实续跑

### 读取与完整性

- 三包实际下载成功：Part1 22422564字节、Part2 22844102字节、Part3 30226字节；archive/member SHA256与只读接收副本在 data/provenance/DELIVERY_MANIFEST_20261009.json。
- 安全解压至 materials/received_20261009；先阅读附带导入脚本，确认标准库、先核验、冲突拒绝且不覆盖，才执行。原58文件在项目根导入：validation/import58.json 实际 verified_files=58/imported_files=58/overwrite=false。重复验证 existing_identical_files=58，原README和启动代码均保留。另14个交接文件为辅助材料，不作为覆盖用户指令的授权。
- 实际读取 plan 2.0.docx 并提取正文；已读中文说明、原下载/审计脚本、提供方元数据、HK字典、旧审计和交接说明。未收到前作或导师回复，不能推断。原计划JWPE和复杂模型为历史建议，用户后续要求优先。

### 实测审计与语义

- 新审计实际命令和输出：validation/wessex_audit_command.log；逐记录规则、异常、候选与manifest位于 data/derived/wessex_audit_20261009。独立核对原API分页和旧派生文件的脚本/输出为 scripts/reaudit_received.py、data/provenance/reconciliation_20261009/reconciliation.json。
- 全量968794行/唯一OBJECTID968794；31个API页的全部属性逐条等于全量CSV。WRC936637行/261个SiteID；Good921074/Suspect13484/Missing2079；负值797（Good534），Missing非零396；2个冲突日4条记录。旧正值无重复候选920445精确重现；当前主规则保留Good零值，920538候选，多93条。没有基于误差调整规则。
- WRC目标由提供方保存元数据支持为许可排口向环境排放的日体积（m³），不是瞬时流速或进水。MCERTS非全覆盖，±8%不能泛化；元数据86,000s公式疑点不自行重算。
- HK49338条/10个名称分组、2个缺流量、无同名同日重复；字典未定位测量点，仍独立保存，不混池。Thames仍缺原文件。
- 已更新 SOURCE_REGISTRY.csv：来源/许可、提供包报告的下载日2026-10-08、实际接收日2026-10-09及hash；不冒称这些数据是本机当天新下载。

### 真实开发实验（不是最终测试）

- 在任何模型误差输出前保存 DEVELOPMENT_SELECTION_20261009.json 和全部配置。仅2016–2021各年≥95%有效日覆盖、单一名称，199候选排序；前3个来源候选未训练，后10个SiteID开发。物理身份未核实，mapping_reviewed=false、station:ID键，未伪造facility_id。
- 两站真实冒烟完成后按已保存的10站/4起点/3延迟批量运行；12完整运行全completed，逐运行参数、边界、code/data hash、预测、指标和日志保留。首个冒烟与对应完整运行两站结果严格相同，未重复并入主汇总。
- 固定起点2022/2023-01-01和07-01，各60日末origin；B30/90/180、h1/3、d0/1/2、alpha10。预测文件记录origin/issue/target/latest-input/budget-start/fit-end/last-train-label/calibration-end。初始参数固定，部署新观测只更新输入；预算不向前借数据。
- 129600逐模型预测；保存于 reports/development_20261009/predictions_all.csv（含全部负面/不可评价行）。每站每条件共同合法目标227–240/240日，三个模型在所有合法真值日都有预测；不把条件100%覆盖写成日历无缺失。三预算共同日期已核验一致。
- d=0、90日预算：本地岭h1/h3等站skill相对持续性为−31.88%/−33.88%，10/10站都变差；180日为−19.92%/−17.59%，9/10及8/10站变差。所有延迟/预算条件平均skill均负，保留687条岭负体积预测且未裁零。共享未跑，所以这不是负迁移率。
- 27项必要软件测试通过；真实结果独立检查日期、预算、输入延迟、拟合标签、数据hash、共同评价及原始合法真值匹配，通过记录在 validation.json。没有把日/episode/随机种子当独立厂的统计显著性，无总体结论或覆盖保证。
- 方法和配置修订已合并 EXPERIMENT_PROTOCOL v0.2，未冻结最终方案。2024–2025曾参加全量描述审计，但未进入模型性能/调参/选站；入口拒绝该期评价label且模型加载截断≤2023。

### 当前交付及下一步决策

- 真实结果说明 reports/development_20261009/RESULTS.md；预算/延迟PDF/SVG图来自真实指标；可编辑.drawio只画实际执行流程，其PDF/SVG由同节点图Python导出，没有冒称draw.io Desktop导出。PNG已视觉检查，PDF嵌入DejaVuSans字体，未裁切坐标或隐藏负结果。
- 值得做有限共享岭开发试验，验证共享估计能否改善短窗不稳定；不支持立刻上复杂模型或最终实验。持续性为当前强对照，不能只比弱周季节线。需要设施/许可映射才能正式物理厂划分；先共享岭/预算内偏差、再决定是否冻结。未跑共享、区间或最终测试。
- 文献8篇元数据/4登记摘要/零独立全文；收到笔记的COD、TrAdaBoost、2.5h及IWA指南为外部声称，未升级为独立核实。KSEE两厂discharge/BOD文章准确定位，采样/步长/分割仍unknown。新增请求日志与层级差异在 literature/HANDOFF_EVIDENCE_DIFF.md。期刊仍未定。
- 环境start_skill已更新，删除“拆分材料未读”的过时启动阻塞，保留隔离/时点/真实结果边界；网络增列jksee.or.kr及www.jksee.or.kr。工具status=saved/requires_publish=true，未声称环境发布或新任务恢复成功。
- 本阶段可提供真实开发技术稿和可编译Overleaf源；它不是共享/最终结果完整论文。实际编译及打包记录继续追加。

### 已验证的论文和交付包

- 英文开发技术稿只写实际三个基线与核查结果，作者/机构/期刊待定，共享、区间和最终实验明确待完成。初次LaTeX生成错误已修复，原失败日志保留。
- 实际Overleaf ZIP已解压到新临时目录，用pdfLaTeX→BibTeX→pdfLaTeX两次编译通过，6页，无最终未定义引用或Overfull；源包不含原始数据，未同步账号、公开或投稿。核验/命令见 validation/overleaf_zip_checks.json 和 overleaf_zip_compile_*.txt。
- 正文数字来自已核验结果的自动宏/表，claim_traceability.csv将定量结论关联原件、规则、运行、结果、图和正文；所有模型与配置文件在实测后保持相同hash。
- KSEE官方HTML恢复HTTP200后，实际读取正文1–4节及表1–4，已补核日采样、出水点、7:3比例及删行；单位/步长/分割实现/完整预算仍未明确。当前8元数据、4摘要、1篇选定全文章节，见 literature/KSEE_FULLTEXT_REVIEW.md；此前零全文为历史记录。
- deliverables 中阶段结果包包含源程序、配置、全部13次真实运行（冒烟单列）、汇总预测/负结果、日志、来源链、英文开发稿与draw.io/PDF/SVG。为减小传输，不重复原数据；daily_candidates及提供方元数据放入阶段包，完整逐记录审计另有可选审计ZIP；全套原件保留云目录，可用原Part1/2和包内导入脚本重新生成。ZIP内含逐文件SHA256；外部压缩包校验见 validation/package_checks.json。

- 阶段ZIP真实重跑核验：解压到全新临时目录后，用包内代码、daily_candidates和元数据直接执行两站smoke；预测CSV字节与原冒烟严格一致。核验运行保留于validation/stage_zip_smoke_run，不并入科学汇总。

## 2026-10-09：下载中断后的原样重新交付

核对四个交付文件仍存在；SHA256全部与原package_checks.json一致，三个ZIP的CRC/内部SHA256均通过，PDF为6页并可解析。未重跑实验、未重新编译或重算图表；原文件及原结果不变。复制到/workspace/exports/wastewater_redelivery_20261009生成新命名副本，各ZIP小于24 MiB。当前工具无单独附件上传/发布接口；/mnt/data导出尝试遇到操作系统PermissionError（不是自动审批拒绝），未在该位置生成文件。重新提供现有能力支持的文件链接，不声称已验证用户端下载。检查记录在validation/redelivery_integrity_20261009.json及导出目录的Checks/SHA256SUMS。

## 2026-10-09：重新链接仍无法读取，准备替代交付

用户截图显示聊天文件预览提示无法读取所在计算机；云端文件正常、原样副本仍完整。当前工具无独立附件注册/上传接口，不能继续把sandbox工作区链接称为已成功交付附件。已检查原仓库native git读取和git push --dry-run成功（dry-run没有创建远程分支）；gh/API访问拒绝、未认证GitHub网页404，未据此断定库可见性。四文件及checksums已就绪，拟专用delivery/wastewater-20261009分支供逐文件下载。因为可能公开未发表稿件和结果，已请求用户确认实际上传，尚未上传、不更改main、不重跑实验。准备记录validation/git_delivery_prepared_20261009.json。

## 2026-10-09：用户确认后的GitHub交付完成

用户明确同意四个交付文件上传并沿用仓库当前可见性。已推送专用分支delivery/wastewater-20261009，提交155d608bf0a69dd23e36067387bf4f22fa6e5bbd；native git远程ref核对一致，main仍为原e6a4fc628d8aae0412cb83a81c528b43d6662fea。四文件的Git blob SHA256与原交付完全一致，各ZIP仍小于24 MiB。只新增交付文件、README和SHA256SUMS，工作分支work及原index未切换/改动，未重跑实验。下载地址为GitHub真实commit对应blob raw链接，私有权限需用户登录其有权限账号；未冒称在未认证浏览器验证私有下载。详见validation/git_delivery_commit_20261009.json。

## 2026-10-09：v0.3共享与GRU开发推进中

- 新paper idea.docx已原样保存/提取，hash记录；旧四交付包和已保存预测/指标hash全部未变。
- QA-v3新版本只保存三个预选源ID（2016–2021）和原十开发ID（≤2023），共35796记录、35518有效Good目标；排除Missing（其中37编码零、2非零）、Suspect、19 Good负值，保留14 Good零。与v0.2相比249原值输入被屏蔽。
- 提供方非空间表缺少许可号/排口/坐标关系；13个名称无标准化同名跨区冲突，但不能据此证明独立物理厂。设施映射及403访问记录已保存。网络草稿增列官方ArcGIS和EA元数据域名，保存不代表已发布或访问成功。
- 独立.venv-stage2安装torch2.8.0+cpu，旧依赖不变；37项软件测试通过。五种简单/Ridge及三种GRU方案实现，共用7日序列信息。数据/代码/config改变会拒绝旧输出续跑；模型epoch和任务状态保存。
- 原2测点单种子96任务完成，23040预测，912/960共同站点-episode-horizon-origin有效；实测独立预算/标签/输入/真值/哈希检查通过。11个负预测保留。该smoke不并入主结果。
- 源站2016–2020训练/2021验证搜索已完成，h1/h3 alpha0.0001/0.01，hidden均8；本地/共享40epochs，冻结GRU编码器适应线性头10epochs。原10站单种子正在运行，尚未形成三种子最终开发结论。

## 2026-10-10：v0.3三种子开发实际完成

- 先保留两个测点smoke，再10测点首种子独立校验，从相同配置缓存续跑另外两个固定种子。full960/960完成、失败0、201600行预测；smoke96任务/23040行单列。4713/4800站点—窗口—步长—起点共同有效，真实缺目标不填补；主结果38条负预测未裁，统一非负次分析单列。
- 37软件测试和新的bootstrap环境脚本实际通过；完整真实时间/预算/标签/输入尺度/QA掩码/真值/所有任务SHA校验通过。独立重算960指标行和72比较点，平均种子损失而非集成或独立厂；6源+720本地+720适应checkpoint及冻结encoder逐张量核对通过。源每次1040步、本地40步、适应10步；计算步数差明确披露。
- 全预算等站共享技能仍未超过Persistence。B90共享偏差Ridge h1/h3为−3.90%/−3.28%（各4/10获胜）；共享B30相对本地Ridge B90为+15.25%/+17.75%（各10/10），只能支持对匹配弱本地对照的历史节省。负迁移尤其B180 h3 Shared Ridge6/10、Shared GRU7/10；全部失败测点和负结果保留。
- 7/14/28日同步日历块+整SiteID探索区间、预算比较、历史Q90高体积、逐种子敏感性实际生成。四张真实统计图PDF/SVG/PNG与英文图注已导出并视觉/字体核查。中文分析为reports/shared_v3_20261009/ANALYSIS.md，逐结论原数据—处理—配置—结果—图—正文链在claim_traceability_v3.csv。
- notebook及CPU代码支持Drive持久目录、签名核验、epoch/任务缓存、失败日志；非Drive核心在隔离临时项目真实验证。原smoke缓存与中断恢复验证不并入科学汇总。首次软件验证目录遗漏已修复且失败记录保留；真实Colab账号/Drive挂载/GPU未认证。
- 全部设施映射仍未知、发布后QA到达仍未知；本地对照使用来源选定超参数，源/目标优化步数未匹配。2024–2025未计算预测性能。区间预测、模型组合、App、独立物理厂最终实验、本轮论文重写均未运行。
- cloud-environment-onboarding:setup复用配置已保存新的CPU启动/install脚本（保存返回saved/requires_publish=true），原网络设置保留。保存是草稿，需用户在环境设置保存并发布后才应用；没有声称已发布或全新任务恢复验证。

## Stage 3A started (2026-10-10)

Stage 2 preservation manifest covers 5040 files, with independent ZIP copies. The read-only audit verifies 1450 checkpoints and 240 local Ridge designs. No new Stage 3A prediction-window results exist at protocol registration. STAGE3A_PROTOCOL.md and configs/stage3a_20261010/full.json define the limited experiments. CPU environment is reused; training and verification are pending.

## Stage 3A completed and STOP (2026-10-10)

Accepted scientific version: stage3a_20261010_v3, config configs/stage3a_20261010/full.json. Stage 2 5040-file preservation check passed with zero changed files. Initial preflight versions and errors remain under runs/stage3a_20261010 and _v2; implementation/numeric reproducibility corrections are recorded, not hidden.

41 tests passed; original two-SiteID smoke completed 12 conditions/5040 rows. Full 240 conditions with original three seeds completed on CPU, zero failed scientific conditions. Primary comparison contains 388800 rows (15 policies including all Stage 2 comparators); another 388800 fixed-endpoint rows are diagnostic only. 4713/4800 common date groups; independent validation checked 1800 station metrics and 2160 frozen encoders.

Legal source validation chose shared GRU40 at both horizons. Budget-internal validation often rejects300: 133/160 target CV conditions have worse MAE at300 than40. Some strengthened local baselines improve, but every learning-policy/budget/horizon mean skill remains below Persistence. B90 shared compact Ridge+bias improves against compact local Ridge by12.12%/17.54%, with0/10 negative transfer at both horizons; this does not prove usable quality. Shared compact Ridge B30 vs local compact Ridge B90 improves9.92%/14.84% (10/10) with positive conditional block intervals, while still worse than Persistence. Unadapted GRU negative transfer persists at B90; IDs and all other budgets are in the saved tables.

Chinese interpretation: reports/stage3a_20261010/ANALYSIS_ZH.md. All results: reports/stage3a_20261010/results/. Source/local/head curves and fingerprints: runs/stage3a_20261010_v3 and reports/stage3a_20261010/trajectory_index.csv. Five vector figure groups: figures/stage3a_20261010/. Device CPU; target full run5.81min wall time, measured summed accepted fit timers27.83min inclsmoke, roughly1.6GiB process RSS. No GPU/paid resources.

No residual model, source expansion, prediction interval, final-period evaluation or software application executed. Paper idea's practical-quality and unreliability-signaling claims remain hypotheses. STOP at Stage 3A and await review before Stage 3B. Packaging/replay checks and dedicated delivery branch are recorded separately; original main/old deliverables must remain unchanged.

## 2026-10-11: Stage3A evidence audit and Stage3B authorized

The user authorized actual Stage3B execution after the evidence audit. Preservation snapshot includes preexisting scientific files and copied global documents at preservation/stage3a_before_stage3b_20261011/. Accepted Stage3A v3 and all prior outputs stay read-only. CPU environment inspected: Python3.12.14, five logical CPUs, Torch2.8.0+cpu, noCUDA. New protocol drafted before new deployment scores; audit, history-use decision, freeze and model implementation are in progress. No Stage3B scientific result is claimed yet.

## Stage3B completed and STOP (2026-10-11)

Acceptednewversionstage3b_20261011_v1. Stage3A independent audit recomputed424170daily losses/1800station metrics/612+612block intervals, independentlyrefit960Ridge predictions andforward2160selectedGRU policies/check2160frozenencoders. No conclusion-changing error found; fullGRU reoptimization notclaimed.

Stage3B smoke12/7920rows andfull300/198000rows complete,0scientificfailure. Original240conditions thenfixedextra60 executed after history/freeze checks. 4713/4800original and1180/1200extra matched date groups. Independent2640metric/388938loss/2700learned-policy reconstruction/120source normal-equation checks passed;12480lambda0 rows exactPersistence. 72000archiveddirect/controlrows match within frozen tolerance. Raw6negativeforecastrows retained;uniformnonnegative sensitivityreported. Fullcachedresume300tasks0fits,2416source/jobmembers unchanged.

PrimaryB30 h1=Persistence;h3 original−4.17% (97.5%individualBonferroniCI−16.27,+2.82%),extra+5.04% (−6.35,+10.61%). Main criterionfailed. Benefits overdirectlocalRidge do not uniformly persistagainstlocalresidual. Mapping/QA realtimeunverified; extraOct2023nowused,no2024–2025performance. Figuresandeditableflowactualgenerated; fullscientific/externalreviewmaterials beingpackagedwithseparate receipts. NoApp/interval/GRUexpansion/manuscriptrewrite. STOP foruserreview.

## Stage3B交付完成（2026-10-11）

8个ZIP已实际生成并经CRC、成员SHA256、干净目录导入校验，最大20.111MiB。独立新目录完成Stage3A/Stage3B指标及全部Stage3B统计表重算；Code-only源拟合+两站12条件重训通过，7920预测一致，再次12条件全部缓存。原科学文件未重跑或改写，55项环境测试通过。

按既有授权上传专用分支delivery/wastewater-stage3b-20261011，commit f9fed85ecec4989019236498e4637d7b1fe9efa6，37个交付文件的Git对象与本地SHA核对通过；main与先前交付refs、当前HEAD/branch/default index保持原样。下载入口 https://github.com/jiangsunyu7-ux/Wastewater_Paper/tree/f9fed85ecec4989019236498e4637d7b1fe9efa6/delivery/20261011_stage3b/README.md 。包内STATUS/CODE_VERSION是包装时快照；此段与validation/STAGE3B_GITHUB_DELIVERY.json为包装后的交付记录，不改变冻结模型/配置/实验结果。用户端浏览器下载未登录代验。云环境start_skill已保存更新草稿，未发布。固定Stage3B已完成并停止，等待用户审查。


## Stage3C.1 可行性核查完成并停止（2026-10-12）

输出版本沿用启动日期：stage3c1_20261011_v1。实际复用19个官方响应并逐SHA核验，新增25次有限请求（19成功、6失败，保留失败）。9条EA Hydrology历史Qualified系列下载7天/6048条/1784003字节；Good且Complete4704、Suspect1344。10开发SiteID连接演示的70日中56日有效，13022/13025失败系列不更换；0/10正式设施连接。

官方名称候选多边形有效期2025-01-27至2025-11-10，不能证明2022—2023污水集水区。正常出水测点、厂址及历史物理分组均未确认。所有样本时间戳无显式时区、区间端点/TDV日界线/逐值首次发布时间未知；120条机械时序检查通过的是明示假设，不是实时可得性。Flood与Hydrology限制已区分，HadUK/UKCEH访问失败保留，停止重复查询。

186源候选仅2016—2021复核，407712条原记录、404492有效；互斥排除Suspect2496、Missing671、Good负49、冲突4。原Missing673包含2条冲突记录，不能重复计数。全部年覆盖≥95%，但已核实物理组0；先独立目标保留后扩源，无新ID/训练。

六项软件测试通过，独立复核实际从雨JSON和原CSV重算上述计数。Stage3B原2724文件/231092067字节逐SHA无变更。下一轮唯一雨量消融草案已生成和核验，但execute_allowed=false、映射/时间/源期覆盖门槛均未满足。CPU1—5分钟是基于Stage3B的模型与统计估计，未执行雨量性能实验。未训练新Ridge/GRU、未评价2024—2025或预留目标、未写论文/App、未用付费算力。见reports/stage3c1_20261011_v1/FEASIBILITY_ZH.md、RUN_STATUS.json及提供方问题清单；完成后等待审查。

## Stage3C2 完成并停止（2026-10-12）

stage3c2_source_scale_v1：七个源池、三套3⊂10⊂30排序；185临时关联组保护37，源并集73SiteID。原3源/10开发/五已用窗口/预算/占位1+mask保持一致。300/300条件、5100策略条件、306000预测、0训练失败，5893/6000共同日历组。K3比90000预测/900选参/14400验证得分，归一化最大差8.88e-16；17软件测试和完整独立420源正规方程/252伪部署/5100重构/18区间核验通过。300缓存resume通过，预测SHA相同；Stage3B/C1原2901文件SHA与大小不变。

主order20261012K30+bias/B30对Persistence h1+0.7044%（六比较调整区间[-1.2046,2.0687]%）、h3-0.1888%（[-8.3090,5.3770]%）。六项14日主比较均跨零；B30相对强本地各6/10负迁移。28日h3 vsK3有正区间，不能替换主分析。长预算点估计有部分收益，历史节省不能由跨零认定等效；结果组成依赖。详情ANALYSIS_ZH.md/RUN_STATUS/预测指标。无最终2024–2025、降雨/GRU扩展、区间模型、论文或App。停止等待审查。


## Stage3D completed (2026-10-12)

User-authorized post-C2 empirical interval development, stage3d_interval_v1: fixed Persistence centre, three frozen K30 pools, 1080 source folds/18 source-only gamma choices, 300 target conditions/324000 interval rows, no software/calibration failures. Source scales/errors for selection end2020; held-source pseudo2021; final source error libraries end2021. Initial B30/90/180 calibration freezes60origins; all evaluation remains2022–2023 used development. Published QA and unverified SiteID mapping retained. Main B30/order20261012/90% MIXTURE-vs-LOCAL skills +2.6407% h1, +2.1222% h3; both Bonferroni97.5%14-day intervals cross0. Coverage improvement costs wider intervals; no established history saving or stable shared-interval contribution, and C2 point-forecast conclusions unchanged. 40tests, full independent reconstruction, exact C2 byte preservation and 300-task cached resume passed. See STAGE3D_PROTOCOL.md, reports/stage3d_interval_v1/ANALYSIS_ZH.md and RUN_STATUS.json. STOP for review; packaging validation separately recorded in delivery/20261012_stage3d/PACKAGE_CHECKS.json.


## Stage3E 完成并停止（2026-10-13）

stage3e_evidence_review_v1：初始状态确认此前只有Stage3D交付、无旧Stage3E；外部重复(1)附件和ReviewerEvidence ZIP未收到，原因不能从本仓库推断。原C2 Part01/02找到并按原SHA关联。原D300任务磁盘证据只读通过；新12条件运行防护复算，36科学输出SHA与原D完全一致，重复resume12缓存。自然9 RUNNING未复现、根因未确认；8受控场景验证原子写入/flush/fsync/写后证据门槛和每次调用2次上限，不能冒充自然根因复现。20软件测试通过。

636444原日损失独立重算；两个原主要比较及7/14/28日5000次同步块区间再次核对。h1 +2.6407%（97.5%区间[-2.2270,+7.3506]%），h3 +2.1222%（[-4.6545,+9.3640]%）；科学结论不变。h3原单位均分25022.12→27448.79m³恶化，13013/13016主要贡献保留；全部10测点/5已用窗/3来源/预算/约束完整报告。部署分段未显示覆盖一致下降。原跨预算/高体积区间按SHA复用并核对点估计，不冒充全新重算。

7篇最近原始文献分级：1篇出版方选定全文章节/表格、3篇出版方存入摘要、3篇仅元数据；不能声称7篇全文核实。复用20官方响应（19原查询+C1既有样本），新官方检索0；物理设施、正常出水测点、日界线及观测/QA首次公开时间仍未知。未发送中英文资料请求已保存，目标期刊待确认。五组真实图件及来源CSV已生成并核查。旧科学6069文件逐SHA保全结果另见PRESERVATION_AFTER。

唯一下一行动C：NEEDS_DATA，先取得提供方历史映射及首次可用记录；没有新实验自动执行草案。未训练新模型、重选gamma、扩源、降雨、2024—2025/保护性能、App或论文。交付CRC/memberSHA/干净目录复核见新delivery/20261013_stage3e/PACKAGE_CHECKS.json，Git上传记录在外层，不能混作科研训练。


## Stage3E交付复核与Git上传完成（2026-10-13）

3个新Stage3E包为6.3821/20.3335/4.7300MiB；另附C2 Part01/02原字节。全部CRC/memberSHA和干净目录20tests、12冻结校准复算/36科学SHA、故障恢复、重复resume通过；首包装动态日志SHA冲突作为失败保留并仅修正stdout位置，未改sealed科学。原6069文件SHA保全通过。已上传专用分支delivery/wastewater-stage3e-20261013，commit d7eda982a91084a3b875e351de1e91dae0e5cacf；28交付文件Git对象/本地SHA一致，远端ref实际核验通过，main/旧refs/当前HEAD/branch/defaultindex保持不变。入口 https://github.com/jiangsunyu7-ux/Wastewater_Paper/blob/d7eda982a91084a3b875e351de1e91dae0e5cacf/delivery/20261013_stage3e/README.md 。用户客户端未登录代验；上传和包验证不等于客户端已恢复下载。包内文档为包装快照，本段及validation/STAGE3E_GITHUB_DELIVERY.json是包装后交付记录，未改变冻结版本。Stage3E新启动说明已保存为环境草稿、未发布，也未声称新任务恢复验证。唯一下一行动仍C NEEDS_DATA；本轮停止。


## Stage3F资料准备与证据门槛（2026-10-13）

stage3f_evidence_gate_v1，状态WAITING_FOR_EXTERNAL_EVIDENCE，本地补件与请求已准备。扫描附件/原材料未发现新提供方回复、导师确认、历史映射或审查原附件；用户外部Stage3E核验作为已报告参考复用，不重复性能/20测试/全诊断。真实原E索引/全PACKAGE_CHECKS及原C2 Part01/02定位，补件包含原19文档与依赖下载SHas，没有重生成原容器。

16条门槛分A物理设施回顾、B内部/公开实时、C工程/历史节省及文献/期刊；稳定匿名组可接受，坐标非无空间输入实验必需；未知实时不阻止明示理想化SiteID回顾口径。85SiteID请求清单（10dev+73源并集+2疑似关联）仅metadata，真实身份未知；328词英文短邮件、中文、2模板和导师一页均未发送。文献只3条增量，没有取得新全文/方法；新增作者关系元数据不是创新证明。2新官方contact访问与2作者正文/软件线索代理403保留，不重试；邮箱按用户提供官方核验记录，未独立取回网页引文。

已支持既有SiteID发布后QA回顾基准及一般WRC/m3定义，独立物理设施/精确日界线、实时、历史节省/工程价值和新颖性核心门槛仍未过；未生成独立最终验证协议。唯一当前行动：由用户发送最小请求并提供带日期/来源回复、两模板/字典及导师全名期刊和工程场景决定。原主要正负结果不变，本轮新预测/训练0，最终/保护性能0。完成小包检查后停止等待外部资料。


## Stage3F小包交付核验完成（2026-10-13）

新F资料包697483B、SHA e128f740d94ca8ae1c5606e045e2023fe89c390f30c093eac9e463bf470b28f2；原E交付补件728923B、SHA449569498a52e0536f485ba70376f5cfa33e356d9c94dca0b4cbc0f337b6ca19。实际CRC/memberSHA及干净标准库请求/文献/补件核验通过，不认证创新或真实设施。原6416文件/913319659B SHA不变，新预测/训练0。源码真实commit3e369d86ea33c823408ffba4c22ec911d8e6d86b，交付commite8d7ecd8a4367301f749ef941ca4d72a85517116已上传专用branch；远端ref实际一致。远端main在本轮前由用户合并E为966c7c2cfa19fdce45267eac3f90b1c4d45e1eeb，内容树与原E相同，无新回复；本轮未改main/旧refs/当前HEAD/index/branch。不可变下载URL和原C2大小/SHA在新folder；用户客户端下载未代验。包中文档为包装时快照，本段与validation/STAGE3F_GITHUB_DELIVERY.json为后续交付记录。环境新启动说明只保存草稿未发布。当前仍WAITING_FOR_EXTERNAL_EVIDENCE，唯一当前行动取得最小有日期/来源的提供方/导师证据包；停止。
