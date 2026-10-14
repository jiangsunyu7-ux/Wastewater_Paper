# 研究方案（合并起点，2026-10-09）

最新完成状态（2026-10-14）：Stage3G stage3g_transfer_reliability_v1 预定CPU开发矩阵已完成300条件、450000点预测及216000风险记录，全部原任务与独立重算通过；43项软件测试与干净目录12条件复现另列范围。主要B30相对Persistence平均技能h1−0.31%/h3−7.58%，98.75%区间均跨零；源侧主B30选eta=0，与匹配均匀共享完全同，权重消融不支持匹配机制。日内可靠性宏AUC .481/.452，不能用混合日期AUC冒称逐厂日内预警；历史节省未证实。全部旧6505科学文件原SHA保留，设施独立性/实时QA仍false，未用最终2024—2025或保护性能。完成后STOP等待审查，唯一下一行动是取得历史设施关系、日体积/到达含义与具体工程用途证据，复用未发送请求；不自动扩模/GRU、调参、最终验证、论文/App。详见新协议及reports/stage3g_transfer_reliability_v1/ANALYSIS_ZH.md、RUN_STATUS.json、NEXT_ACTION.md。下文旧阶段记录保留为历史。


## 范围与阶段

仓库原有内容只有 README.md。大附件最初受32 MiB工具限制；后来收到三个拆分包，2026-10-09已读取原计划、中文说明、原始/派生表、旧审计和脚本，58原文件全部hash核验通过。本文件保留启动方案并追加实际证据，不静默覆盖原DOCX（其JWPE、神经模型和原队列建议为历史版本，用户后续总需求优先）。未收到导师回复或前作；原proposal对教授的提问不是教授的反馈。

主问题：未参与共享训练的既有污水厂，仅有 30/90/180 天初始本地建模历史时，共享学习是否改善未来 1/3 天处理后日排放体积预测，并减少达到相近误差所需的历史？

次问题：①预算、水量波动和输入缺失如何影响迁移及负迁移；②90/180 天预算下预测区间覆盖、宽度和区间评分的权衡。

## 工程意义与可行性门槛

日排放体积预测可提供出水量预期和短期运行计划的数量参考。当前数据没有支持污染负荷、水质合规、溢流或节能的证据，不声称可带来这些收益。必须确认记录是处理后出水的日体积，非进水、瞬时流率、许可限值或统计估算；单位换算不能替代语义核实。

预测时点设为日 t 结束且允许的最近观测实际到达后，预测 t+1/t+3 的日体积。若 t 日数据只在事后年报获得，本研究只能称回顾性可预测性实验，不能声称已验证在线部署；需另设可证实的延迟情景。

既有厂历史不足模拟的是可用建模记录不足。季节、雨量等因果解释需要附加有时点保证的数据；仅出水滞后和日历变量时，不进行机理因果推断。

## 待复核审计与工程证据缺口

| 用户前期记录（未核实） | 本次应核对的证据 | 决策风险 |
|---|---|---|
| Wessex 968,794 行，2016—2025 | 原始字节 hash、表头、日期解析、计数是否含空行/重复 | 数据版本错配 |
| WATER RECYCLING CENTRE 936,637 行、261 编号 | 名称筛选规则、大小写/空格、唯一 ID、厂址/测点清单 | 261 ID 不是 261 厂 |
| Good 下负值；Missing 下非零 | 各标签全频表和逐条异常文件 | 负值隔离；Missing 非零不能作真值 |
| 同厂同日冲突 | 站点层和物理设施映射后分别核查，保留行号 | 不能平均冲突值或重复计权 |
| 50 站演示候选 | 原脚本、选站理由、完整候选覆盖 | 不继承为正式队列 |
| 香港数据已下载 | 文件、来源许可、测点是进水/出水、日/月粒度、工艺组 | 未解决则不混池、不作外部验证 |
| Thames 链接已定位、403 | URL 和实际响应；原始文件是否存在 | 当前不计入拥有的数据 |

需建立 SOURCE_REGISTRY.csv、来源说明和 FACILITY_MAPPING.csv。设施映射应使用厂名、位置、许可/排口或官方设施证据并人工复核，不依据预测误差选映射。任何无法识别独立物理设施的站点不能支持厂级独立泛化结论。

## 最小路线

1. 入库、只读原件、来源与许可登记、审计脚本对照旧审计；验证目标和记录发布时间。
2. 只用明确指定的开发站点；跑持续性、周季节持续性、本地岭回归。先评价模型能否可靠构造样本及误差是否有量纲意义。
3. 映射/共享来源可行后，在开发厂隔离下比较本地岭、共享岭、共享岭加本地偏差。结构/输入一致，超参数只用来源/开发资料。
4. 满足门槛才冻结厂/时间/处理/判据，再一次最终测试。无需先增加深度模型。只有开发资料显示线性模型显著欠拟合且简单特征修正无效，才考虑同种梯度提升树的本地/共享版本。
5. 以已核查结果制作图件、英文背景/方法/结果和可编译 Overleaf 项目。

## 是否继续的判据

当前结论已更新为：**数据足以运行站点级回顾性基线；值得继续有限共享岭的开发试验，但共享学习效益仍无法判断。** 真实数据已取得，初始固定岭明显弱于持续性，不能作为有益迁移证据。当前未运行共享、区间或最终测试。

继续条件：目标语义与许可可确认；物理设施可稳定映射；开发与来源队列有足够互不重叠的设施及有效训练/评价日；30 天预算可构造至少 14 个合法训练标签；朴素基线与岭回归能在相同日期运行；数据不只由填补目标支撑。若 30 天普遍不足，保留此失败发现，不悄悄改成按有效记录取 30 行。

暂停或收缩：出水/单位不确定、冲突/缺失造成大量不可评价日、设施不可分辨、发布时间不足以支持规定信息时点。可收缩为数据可用性/回顾性站点研究，不能延续厂级部署主张。

开发基线跑通本身不证明跨厂收益。预算收益必须直接比较共享短预算与本地较长预算，报告差值及不确定性；不得仅凭平均曲线下降作结论。

新证据：独立复核全量968794、WRC936637/261 SiteID、Good负值534/Missing非零396及2个冲突日。提供方描述和m3字段确认WRC许可排口日体积；仪表认证不普遍、首次到达与修订历史未知。香港49338条/10分组仍不可比，Thames仍没有原始文件。

开发结果见 reports/development_20261009/RESULTS.md：10个先选SiteID、4起点、12完整运行；d=0时本地岭90日预算的h1/h3等站MAE skill分别−31.88%/−33.88%，180日仍−19.92%/−17.59%。全部延迟/预算组合平均skill为负，30日出现687条负预测，未裁零修饰。可把短窗参数不稳定/漂移作为待查解释，不能当作证实机理。持续性应是下一阶段强对照，不以周季节弱对照获得正面叙事。

下一步仅采用已有固定SiteID来源候选、同结构共享岭及预算内偏差修正；正式物理厂迁移前先落实设施/许可分组。若不能超过强朴素基线，收缩研究为可靠性/失败边界报告，而非堆叠神经模型。来源ID互斥不等于厂级互斥。最终2024–2025未做模型选择，但已参与描述性审计，不能绝对称数据从未接触。

## 文献、期刊与前作

见 literature/EVIDENCE_TABLE.csv 和 literature/REVIEW.md。当前8篇元数据、4个独立读取登记摘要，零独立读取全文。收到交接笔记后新增核实BEJ 2023 DOI；其两厂水质/TrAdaBoost内容只为外部笔记声称，未升级为独立核实。KSEE discharge/BOD论文已经准确定位，其采样/步长/分割仍unknown，不与BEJ水质论文混淆。IWA官方页面仍403，外部检索指南摘要保留出处和二手级别。未知厂数、输入和预算保持unknown。

重要的新颖性风险：2024 年 KSEE 原始研究（10.4491/ksee.2024.46.3.111）的登记摘要已明确研究两座污水厂 discharge/BOD 的迁移，且 discharge 的改善仅轻微。因此不能声称首次跨厂排放量迁移。本项目必须以独立设施隔离、完整短历史预算、与简单基线的匹配比较、负迁移和区间证据证明具体增量；这些是待实施贡献，不是已成立发现。

条件性定位：若贡献集中在严格跨厂隔离、有限历史迁移和区间验证，可优先考察 Journal of Hydroinformatics；若贡献主要是出水量工程数据审计与运行适用性，考察 Water Science & Technology。此为定位假设，**不是已核实的当前 scope 或作者指南**。需官方页面核验后比较 article type、格式、数据/代码政策、图件要求和费用，再建议最终目标。JWPE 为旧目标，不默认沿用其模板。

## 一个月的工作目标（非结果承诺）

- 第 1 周：材料核对、设施映射、数据审计和开发基线，完成可行性决策。
- 第 2 周：开发隔离的共享基线、预算和缺失敏感性；冻结协议与 hash。
- 第 3 周：最终点预测/区间实验、不确定性与失败病例，保留全结果。
- 第 4 周：可追溯图件、英文稿和真实编译的 Overleaf ZIP。

附件和网络依赖未解决将推迟相应任务；不以排期替代真实性或证据门槛。

### KSEE原文补核（出版社域名恢复后）

已实际阅读KSEE出版社HTML正文1–4节及表1–4：两座工业园区污水厂出水监测，日观测，2018–2022，九项参数；删除缺失/3-IQR异常整行后1139/1121记录；训练测试比7:3。出水discharge物理单位、预测步长、时间分割实现、缩放拟合子集及完整本地适应预算仍未说明。不能将日观测直接认定为日积分体积，也不能推断它采用随机拆分。已有跨厂discharge研究确认；潜在增量仍需实际共享实验支持。当前独立证据为8篇元数据、4登记摘要及1篇选定全文章节核实，取代上文“零全文”的历史状态。

## v0.3 开发共享/GRU阶段（2026-10-09）

新paper idea.docx与当前用户明确指令支持受控GRU比较，取代上轮仅共享岭的拟议路线。保留旧包/预测/代码；37项程序测试通过，原两测点单种子完整检查已通过。使用已发布Good质量标记同时筛选输入/训练/评价；年度质量标记的历史可用性仍未知。源先保留上轮看误差前按覆盖率选定的3个ID，所有10开发ID不换；实际名称映射列出设施/许可/排口未知项，仅SiteID探索。官方在线ArcGIS访问被拒，已有官方快照为当前证据。

五个简单/Ridge方法和同一单层GRU本地/共享/头部适应，输入信息完全一致。源2016–2020拟合、2021验证完成有限搜索；h1/h3分别选alpha0.0001/0.01，GRU均hidden8。40个训练epoch和10个适应epoch固定，无目标评价早停。CPU PyTorch2.8.0+cpu独立环境可运行，暂不需要GPU。主实验三种子未全部完成前不写共享收益结论；后续继续评估持续性对照、同预算迁移、跨预算历史减少、高体积及相关性区间。2024–2025没有性能评价。

## 2026-10-10开发证据后的判断

三种子全部960任务已完成，201600逐条预测；同QA规则重跑五基线以及三GRU训练方式，共同评价日期与初始预算核查通过。共享Ridge B30对本地Ridge B90的h1/h3等站改善15.25%/17.75%、各10/10测点，主14日块探索区间均正。所有共享方案的等站平均技能仍低于强Persistence；不能把对弱本地模型的历史节省写成整体工程预测改善。90天共享偏差Ridge最接近Persistence（−3.90%/−3.28%），区间跨零；高体积次分析有局部收益，但不能改主指标。详细逐测点负迁移、种子变化、7/14/28日敏感性见新中文分析与CSV。

下一阶段先补设施/排口与历史QA到达证据、按预定质量覆盖选择更多来源，以及本地调参和优化步数匹配等小规模开发诊断。共享学习是有限历史建模稳定性的候选，而非已经证实的运行收益。暂缓模型组合和App；区间可在B90/180的强简单基线/共享偏差方法预算内开发，不预设覆盖保证。2024–2025继续保留，不开展最终性能以追求正面结果。若小规模对照仍无总体持续性收益，应收缩贡献与结论，保留真实负结果。

## Stage 3A decision (2026-10-10)

Audit training adequacy and strengthen local comparators before interpreting transfer. Test fixed finite Ridge and GRU trajectories with legal validation; preserve negative outcomes and unverified physical identities. Residual models, source expansion, intervals and final evaluation remain unexecuted proposals pending Stage 3A review.

## Stage 3A evidence-based decision (2026-10-10)

Simple feature reduction improves several short-history local Ridge conditions; longer GRU fitting is not a general cure and often worsens legal validation. Relative sharing benefits remain against strengthened matched local learning models, including some30-vs90day comparisons. All-date mean MAE skill remains below Persistence; high-volume subgroup intervals crosszero. No stable engineering-quality superiority or reliability signaling has been demonstrated.

Recommend only a proposed small Persistence-residual Ridge/shrinkage test after review, with λ=0 control and separate sharing/bias/shrinkage ablations. Facility mapping, QA arrival contracts and source representativeness still limit independent transfer claims. Source expansion, intervals, final testing and a prototype are conditional future proposals, not authorized runs. Stage 3A is complete; stop.

## 2026-10-11: controlled residual-Ridge development

The newly authorized question is whether information shared across the fixed three source SiteIDs helps predict changes relative to Persistence under frozen initial budgets. The two secondary questions are relative modeling-history requirements and negative transfer/conservative correction. Refer to STAGE3B_PROTOCOL.md; benefits remain hypotheses until actual fixed-round results. Journal selection remains unconfirmed. GRU evidence is archived rather than expanded, and published QA/physical facility identity remain unresolved deployment/extrapolation limits.

## Stage3B actual evidence and narrowed claim (2026-10-11)

Thefixed residualRidge round did not establish the prespecified B30 improvement overPersistence atbothhorizons. The h1sharedpolicyretreatedexactly toPersistence; h3 changed sign betweenreuseddevelopment andadditional2023Octoberwindowwithintervals crossing0. Strongerlocalresidualbaselines removea universalinterpretation ofhistorysavings. Keepfinite-budget/SiteID exploration andnegative-transfer findings; do notclaimindependentplantgeneralization, deployablegainornewalgorithm. Nextmostvaluableconditionalexperiment is a tightlycontrolledorigin-available rainfall/inputablation, afterfacilityandavailabilityevidence; noautomaticexecutionorGPUneed. Journalstillunconfirmed.


## Stage3C.1 feasibility decision (2026-10-12)

Official historical rainfall is technically retrievable: nine Qualified series were downloaded for a fixed seven-day sample. This does not establish source-period coverage, historical release times or spatial engineering validity. The available name-candidate boundaries are valid in2025, not proven historical2022–2023 sewer catchments. No physical facility/outfall crosswalk is verified. The study remains retrospective SiteID exploration; independent physical-facility and real-time generalization claims are unsupported.

Reserve previously unused, physically verified independent target groups before expanding sources, honouring any existing provider/user holdouts. The186 candidates satisfy archived pre2022 quality coverage but are not186 verified facilities. No target/source assignment or expansion fit was performed.

The sole conditional priority is a fixed-source, fixed-window volume-history versus volume-plus-lagged-rainfall ablation. All five original development windows, including October2023, are used history. The draft is blocked until facility/time/coverage evidence and user review; do not jointly expand sources, broaden tuning or seek final-period gains. Provider questions and the feasibility report are underreports/stage3c1_20261011_v1/. Stop after this audit; no manuscript or App.

## Stage3C2 source-scale evidence (2026-10-12)

The user prioritized finite SiteID source-scale exploration, archiving the disabled weather draft. All7pools/five reusedwindows were actually completed; all budgets, compositions, fallback and negatives preserved. PrimaryB30K30+bias skill vsPersistence was+0.7044%h1/−0.1888%h3; all six14-day adjusted primary intervals crosszero. Longer-budget and alternative-policy point gains remain exploratory, composition/block sensitive; no universal history saving or deployment claim. Resolve physical/normal-outfall groups and historic observation/QA release before one engineering-input experiment. Stop for review; no automaticK60, newmodels/window/finalperformance, paper or App.


## Stage3D completed (2026-10-12)

User-authorized post-C2 empirical interval development, stage3d_interval_v1: fixed Persistence centre, three frozen K30 pools, 1080 source folds/18 source-only gamma choices, 300 target conditions/324000 interval rows, no software/calibration failures. Source scales/errors for selection end2020; held-source pseudo2021; final source error libraries end2021. Initial B30/90/180 calibration freezes60origins; all evaluation remains2022–2023 used development. Published QA and unverified SiteID mapping retained. Main B30/order20261012/90% MIXTURE-vs-LOCAL skills +2.6407% h1, +2.1222% h3; both Bonferroni97.5%14-day intervals cross0. Coverage improvement costs wider intervals; no established history saving or stable shared-interval contribution, and C2 point-forecast conclusions unchanged. 40tests, full independent reconstruction, exact C2 byte preservation and 300-task cached resume passed. See STAGE3D_PROTOCOL.md, reports/stage3d_interval_v1/ANALYSIS_ZH.md and RUN_STATUS.json. STOP for review; packaging validation separately recorded in delivery/20261012_stage3d/PACKAGE_CHECKS.json.


## Stage3E证据结论与下一行动（2026-10-13）

本轮只修复运行证据持久化并对已有区间做有界事后诊断，未训练预测模型。主要技能平均虽为正，两项调整区间均跨零；不能宣称共享区间稳定增益或历史节省，也不能据此断言所有共享学习无效。h3原单位均分恶化与大体积测点评分尺度、宽度成本有关；测点影响诊断不删除正式测点。源组成gamma=0退回LOCAL的情况完整保留。

最近七篇原始研究按实际读取等级审查；已有跨设施出水/水质迁移和概率预测，当前候选贡献为透明有限初始历史开发基准、负迁移与覆盖—宽度适用边界证据，非新算法或首次。关键全文与工程映射/首次发布时间仍缺，选刊待确认。唯一下一行动C NEEDS_DATA：取得并审核历史设施—SiteID—正常出水测点及观测/QA时点，再决定是否值得制定独立验证。本轮结束后STOP，不自动开展下一模型或最终测试。


## Stage3F分级资料门槛（2026-10-13）

保留原有限初始历史共享能否改善/何时负迁移/能否省历史的问题，允许负结果。独立物理设施的回顾性主张需历史分组、正常出水对象和日期依据，匿名稳定组可以，精确坐标非必需。实时可用性另需所声称内部或公开环境的观测/QA时点，不设为全部回顾研究总开关。工程和历史节省需导师场景及评价前有依据的界限，不能从旧结果倒推。原主要收益不稳定和源组成/负迁移均保留；部署真实误差的事后诊断非提前预警规则。文献增量未取得新全文，创新仍条件化；目标期刊未定。Stage3F没有新性能。当前WAITING_FOR_EXTERNAL_EVIDENCE，唯一当前行动收集最小提供方和导师证据包，资料未到前不继续实验。
