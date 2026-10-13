# 最小实验协议（v0.1 初稿保留；v0.2 开发执行修订，尚未最终冻结）

状态：开发入口已设计；真实文件未读取，设施映射、队列和日期仍待审计。下列选择是前瞻的工作默认值，不冒充已冻结或已执行的最终研究方案。最终测试不得由本次入口执行。

上段为拆分包到达前的历史状态。**当前状态：真实审计和三个开发基线已执行；末尾 v0.2 记录采用的站点探索/时间方案。物理设施划分、共享/区间和最终方案仍未冻结。**

## 1. 数据契约与审计

原始数据存 data/raw，来源和接收日志存 data/provenance；从不覆写。记录 SHA256、下载日期/版本/许可（未知记 unknown）。逐条规则：日期/数值解析失败、非有限数、负值、非可接受 QA、同站同日不同记录均隔离。同日完全相同的数值和 QA 可折叠，但保留原行及折叠原因。Missing 下非零仍不是可评价真值；Good 下负值仍不合格。

审计先输出站点级候选日表，**不代表物理设施映射已解决**。按日历重新索引；填补只供模型输入，不供评价。站点输出的 observed_input 是无事后 QA 过滤的有限非负原值；冲突日不使用。QA 仅定义回顾性可接受目标，因此两者可不同。若无法确定原数值当时可读/是否被回填，必须停止部署能力主张。

当前开发 runner 只接受明示的可信目标语义、人工审核的开发设施表、单一测点每厂映射和明示输入发布时间约定。多测点厂需另建有证据的聚合并重新审计；不得自动合并。许可未知时审计可本地执行，正式公开和最终研究待许可核实。

## 2. 划分与盲区

本次只从明确标记 development 的设施读取模型样本；不自动用演示 50 站，亦不自动指定测试厂。本次来源/测试配置不得提供给 runner，遇见非 development 项直接报错。仅为建表做全量原始审计不构成模型选择，但不能计算最终厂性能、波动分组或选择典型最终厂。

后续共享来源、开发目标、最终目标应按物理设施互斥。先以设施证据/数据可用性制定队列；共享来源与开发的日期不晚于部署切点，最终厂不进入任何拟合/缩放/超参数或区间设计。厂级清单和依据独立记录。共享来源比例、最终厂数量及季节/时间窗在读到实际可用性前不虚构。

## 3. 时间与本地预算

以 deployment_date=T 为第一个预测 origin（当天结束）。预算 B∈{30,90,180} 是 [T−B, T−1] 的连续日历历史，含缺失日。初始训练样本 origin ≤T−1，标签日期 origin+h ≤T−1；越过初始窗口的标签排除。任何 lag、缩放、适应或校准都不能从 T−B 之前读取。

预测步长 h=1/3，t 日末发出对 t+h 日体积的点预测。开发默认输入发布时间约定待证实；可在配置明示固定观测延迟 d 天，仅用日期≤t−d 的原值。默认不得启用该约定，需证据路径和 reviewed=true。文件接收日期不等于运行时可用日期。

同一到达约定也约束初始训练标签：target_date+d≤T−1。初始拟合使用当时已到达的有限非负原观测作为训练 label，不用后来 QA 标签筛选训练日期；最终评价另用事后 QA 合格真值。两者要分开报告。若 Missing 下非零值是后来估算/填补，而非当时观测，应通过来源证据隔离，不可把此时点假设设成已核查。

部署期间可读取在 origin 时已到达的新观测用于滞后；本次岭回归参数、缩放和缺失填补器在初始窗口拟合后固定，不增量训练。报告初始历史和在线新增观测，避免误称全程只见 B 天。自然缺失保留；事后 QA 不决定输入遮蔽。

## 4. 三个开发基线

- 持续性：最新允许读取日的值。该日缺失则从允许历史向过去找最近合法观测，最多 7 天，记录观测年龄；不跨预算左边界。若无值则不可预测。
- 周季节持续性：目标日期的上一周，即 t+h−7。若该日尚未可读或缺失，不填造它；该模型当日不可预测。h=1/3 均是已过去日期。
- 本地岭：同一每日特征定义，在每个预算/步长单独拟合；原值 lag 0/1/2/3/6/7 相对允许读取的最新日期；过去 7 日已到达观测均值；预测目标日期星期的 sin/cos。缺失中位数和缺失指标只在训练 fit；连续变量缩放只在训练 fit；标签不填补。固定 alpha=10 作为调试默认值，不声称最优。

共同评价：原始目标合法且三模型均能给出预测的同一 origin/target 日期。另报各模型有效率及共同覆盖率，以免掩盖缺失造成的选择。origin 日目标缺失不强制删除样本，未来真值缺失不能插值。

训练至少 14 个合法 label；共同评价至少 28 天为后续可行性门槛，本次不足时直接报告不足，不扩展挑窗。不同预算最好同一部署与评价窗口，避免预算和季节混淆。

## 5. 后续共享及冻结条件

共享岭保持相同特征/正则化定义；仅来源厂训练，不包含目标设施。共享输入/标签的厂级尺度如使用，必须是每厂在其允许初始历史内估计的稳健尺度，源和目标规则一致。禁止共享模型利用目标全期均值。开发阶段比较原量纲 vs 合法局部尺度；最终冻结一种。

共享岭+偏差：模型本体不动，仅用目标训练子窗口内的 (真实值−共享预测) 均值校正；标签必须在初始预算内，校准子窗口不得兼作偏差训练。报告偏差估计有效 label 数。源训练和目标适应的原始记录不能超出切点。

必要时固定一套梯度提升树结构进行本地/共享对照；神经模型不是必选项。若选择岭 alpha，范围预定 {0.1,1,10,100}，在来源/开发内以时间前进验证选取，验证标签不能越界；最终厂不选 alpha。

冻结产物：设施映射及依据、源/开发/最终列表、时间窗/步长/预算、输入到达规则、清洗/冲突、缩放/适应/缺失、参数、统计和判据的配置及 SHA256。状态更改为 frozen 前须存在冻结清单和实际可运行命令。最终测试后全部改动在探索日志注明。

## 6. 指标与不确定性

每设施/预算/步长：MAE、RMSE（m³/day 的日体积记录）、有效日期数、覆盖率、与持续性和周季节持续性的误差差和相对改善。基线误差为零时相对改善记 undefined，不加 epsilon 改写它。

主汇总：每厂相对周季节持续性的 MAE 改善等权平均；同时给原量纲逐厂误差和等权差值。共享 vs 本地的迁移效果单独比较；负迁移定义同预算共享 MAE 大于本地 MAE（严格>，同时报差值和分布）。不得以共同日期计数权重代替等权厂汇总。

共享贡献拟议成立标准（最终前可基于开发证据调整并冻结）：90 天、h=1/3 两个共同主终点共享 vs 本地的等权相对 MAE 改善同时为正，且相关性稳健区间排除 0；考虑两个主终点的同时区间/多重性。工程效果门槛拟议为 ≥5% 改善，属于需业务方确认的研究阈值，不是普适工程定律。未超过 5% 的统计差异不冒称显著工程收益。

预算减少：共享 B=30/90 vs 本地 B=90/180，在相同目标日期下逐厂误差比差，拟议等效界为 5%，需单侧区间支持不劣于界限；点估计接近不等于等效。失败：主终点不支持改善、工程门槛未达、负迁移普遍（拟议>25%需明确报告）、可评价厂不足或设施/信息时点无法确认。不同失败性质分别报告，不改数据追求结论。

不确定性：在共同日历上以 14 日连续块为默认，所有厂同时抽相同日期块以保留同日期相关；设施按整厂重采样，可实现两维重采样。7/28 日块为预定敏感性；厂数少、窗口短或季节非平稳时注明局限。不得将日或重复随机种子视为独立厂。首批单站开发数值不做总体显著性结论。

## 7. 区间及缺失（后续，当前未运行）

90/180 天预算为主，最后 30 日历天为校准窗，之前为模型训练/偏差适应；窗口之间按 h 截断训练 label，校准 origin 的 label 也须≤T−1。若有效校准残差少于 20 则报告该配置不可估计，不从预算外取数据。点实验与区间实验训练容量不同，需分别报告，不用更小训练窗的区间点误差替代主点实验。

每步长分别用 absolute-residual split calibration（经验 90% 区间）作为简单方法。有限样本 quantile 用 ceil((n+1)*0.9)，超出样本时不可给有限区间。时间序列交换性不成立，不声称分布无关覆盖保证。报告每厂经验覆盖、平均宽度和 interval score；非负端点裁切若采用应预先固定并重新评价。

人工缺测仅遮蔽 origin 当时输入，目标真值完全保留；预设随机种子 20261009，独立遮蔽率 10/30% 和 3/7 日块仅作开发候选，机制冻结后最终使用。与自然缺失分开。每次 origin 输入的掩码全模型一致；不能删行或随模型变更评价目标。

## 8. 输出、失败与图件

每次运行 runs/development/<唯一ID>/ 存 predictions.csv（保留失败预测、年龄/共同比较标记）、metrics_by_facility.csv、equal_weight_summary.csv、availability.csv、manifest.json 和 run.log。初始化后失败也留 manifest.status=failed；原始/配置/代码/依赖版本完整。runs/unit_only 是程序夹具，不是实验结果。

定量结论表 claim_traceability.csv 只有核查结果后填数值；无结果时不生成论文图。计划图件：数据划分、预算误差、每厂改善/负迁移、区间可靠性、按预先规则选典型/失败案例。图的结果来源必须可追踪；不画尚未执行的共享模型。

## v0.2：收到材料后的开发执行修订（先记录配置，再运行，2026-10-09）

变更理由：提供方快照支持 WRC 许可排口每日体积语义，但仍没有物理设施身份和历史首次到达/修订日志。原设施级门槛保留；新增显式站点探索入口，避免伪造审核字段，也避免把可运行的离线基线全部阻塞。不是最终协议冻结。

输入：`wastewater_data/raw/wessex_all_2016_2025.csv`，hash `22f494e2b96fe6fa9550c68971d50c752ddd291793fdc60334d64b2ef089f518`；单位 m³ 日累计，非瞬时流率。原件/派生参考文件均保持字节不变。独立审计目录 `data/derived/wessex_audit_20261009`；Good 非负且无冲突是主候选规则，延续 v0.1。原包 Good 正值/无重复的920445行另行精确复核，主规则多保留93个Good零值。没有以误差选择清洗规则。当前开发共同真值没有零值，不能用它证明所有Good零值可信。

站点候选：仅 2016–2021 各年 Good 非负无重复覆盖≥95%、单一提供名称，得到199个SiteID；数值排序前3个13006/13008/13012只保留为未来来源候选（未训练共享），随后10个13013/13015/13016/13017/13022/13024/13025/13028/13029/13031是开发子集。不是旧演示50站，不是最终队列，不保证物理独立或代表性。

全部配置与选站时间保存在 `configs/development_20261009/` 和 `DEVELOPMENT_SELECTION_20261009.json`，在查看首个真实误差前写定。4个episode第一日末origin：2022-01-01、2022-07-01、2023-01-01、2023-07-01；每个60日历origin，与最初配置默认60天一致，不采用交接建议的30天。B=30/90/180、h=1/3、额外d=0/1/2，alpha=10，初始拟合后不更新参数；未做调参。episode之间允许重叠初始历史，但不把它们当作独立设施重复。

日末origin o 等价于次日早晨issue_date t=o+1，预测Y[t]/Y[t+2]，非三日累计。原budget窗口 [T−B,T−1] 不变；初始fit_end=T−1，标签≤T−1−d，首次origin T期间新增已假定到达观测可更新lag。预测文件记录所有边界；训练 label 是原数值而非事后QA筛选真值。原快照的Missing零值可能进入该原值情景；未知历史修订和真正到达时间仍限制在线解释。

开发入口对任何analysis_unit都拒绝跨入2024–2025的评价label，模型加载时截断日期≤2023-12-31。全量描述性审计曾读取最终年份，明确披露；没有最终年份模型性能或选择结果。两站冒烟独立保存但不并入10站主汇总。

station_exploratory 输出 `metrics_by_station.csv` 和等站汇总；API里的facility_id字段仅是station:ID兼容键。主汇总将每站四episode共同有效日期合并算MAE/RMSE，再等站平均skill，不把原始大站流量均值当作标准化收益。真实结果验证已确认三模型及三预算共同日期一致。

27项程序测试与独立真实结果核查均通过。12次完整运行均completed，最少每episode配置28共同有效日，汇总每站227–240/240有效真值日。先前提议的贡献5%/负迁移25%门槛没有变成已验证工程阈值；共享未运行，不报告负迁移比例。无置信保证或把日当厂的显著性。完整初始负结果保持原样，后续方法修改需新版本和探索日志。

### 下一步开发门槛（根据上述结果提出，尚未执行）

共享试验必须同时报告相对本地岭和持续性的结果；只超过当前较弱本地岭不足以证明实用预测收益。限定先做同输入/结构的共享岭与预算内偏差修正，保持上述开发日期和站点，明确为开发探索。若90/180天两个步长仍无法达到持续性质量，或身份/历史信息时点无法建立可辩护边界，应停止扩大模型并转向基线/数据局限报告。复杂模型、最终冻结和最终测试仍需独立下一阶段证据；这些新门槛不冒称在初始本地结果前预注册。

## v0.3：本轮共享与GRU开发执行规范（选参前记录）

依据新用户指令及paper idea.docx建立；旧v0.2程序、预测和包不改。新原件SHA256 e698f0c07c3e73baf16c2b88d873675405443b2186dfe6746f55a50e33c818b1。附件为研究材料而非额外执行授权。本节覆盖旧协议的QA、输入特征和模型限制；不是最终测试冻结或预注册。

数据v3沿用已核验原审计的Good非负/无冲突真值，现在同一掩码用于输入和训练标签。Missing（含编码零）与Suspect均排除；Good负值/非有限值排除，冲突整日隔离；Good零保留但不是独立仪表核验。无目标插值、无未来输入填补。显式使用发布后QA进行历史回顾，在线QA和修订时点仍未知。

三个源SiteID 13006/13008/13012沿用原先模型误差前的候选，条件为2016–2021每年Good非负无重复覆盖≥95%且单一名称。10开发测点、4起点及60日窗口不变。提供方TDV表非空间表、无许可/排口ID或关系；同一标准化名称归同一分区并检查无跨区冲突。FACILITY_MAPPING_V3列出名称/证据和未知项，仍不称独立水厂。只有三个源是本轮规模限制，不能代表共享规模已充分研究。

来源选参：仅来源2016–2020训练、2021逐日验证；以等源站归一化MAE选Ridge alpha（0.0001/0.001/0.01/0.1/1）和GRU hidden（8/16），两个步长分别选择。然后源模型用2016–2021重训。全程不读目标开发误差选参，也不读2024–2025。小规模搜索不是最优模型保证。

所有学习模型取相同7日序列信息：归一化日体积、观测掩码、输入日星期sin/cos、目标日星期sin/cos。Ridge展平同一张量，GRU使用其序列形式。缺失输入填为允许训练历史正Good值中位数（归一化后1）并带缺失指示；预算外只padding，不读取旧观察。尺度：源在各训练阶段允许历史内固定中位数；目标只在[T−B,T−1]，B30/90/180，正值为空则1m³并报告。源损失先每站平均再等权，权重总和1；本地每样本1/n。因此大厂不因原量纲或样本数支配。Ridge无另一次全数据缩放。

源Ridge/GRU不含任何目标拟合数据。目标本地Ridge和GRU仅用预算内标签，最后训练标签≤T−1；实际样本数必须报告。偏差适应为预算内真实标签减共享预测的平均残差。GRU为单层8/16隐藏元、线性头、AdamW lr0.01/weight_decay0.001、梯度范数1；source/local各40epochs，256batch；适应从共享权重开始，冻结GRU只训练同一线性头10epochs、lr0.01。设置在模型误差输出前存入JSON。禁止按评价损失早停。固定三个种子20261009/10/11；先原2测点单种子完整流程，再扩展10测点单种子检查后补全另外2种子。每个任务/epoch保存checkpoint和诊断。

持续性与周持续性均按同一QA流重跑。新特征、尺度和正则化定义与v0.2不同；不能将新旧数值差只归因于共享或清洗。主比较仅v3相同规则/日期的8模型。主分析保留原始负输出；次分析仅统一对全部方法max(0,pred)，保留原预测，不择优报告。对所有模型、种子、预算取共同评价日期，并另报真值/模型覆盖损失。

高体积阈值为各目标episode最短30天预算内有效Good体积Q90，所有预算/模型共用，报告实际阈值样本数。这是历史高体积阈值，不是容量、许可或溢流阈值。三个种子的绝对/平方误差先按同一预测日期平均，再按站汇总，绝不当额外水厂，也不暗中构造集成预测。报告各种子和站的MAE/RMSE、持续性skill均值/中位数/获胜比例，共享/适应对本地的负迁移；负迁移是共享MAE>对应本地MAE。

跨预算直接比较共享/适应B30对本地B90及B180，B90对本地B180。主要误差比以站等权；5%为探索不劣界，不是已证工程容忍度。关键差值做7/14/28日移动块bootstrap，所有站同步抽相同日历块、4episode分层；再整站重采样。主块14日、1000次，固定seed；区间仅有限10个未核实独立SiteID的开发条件下描述性不确定性，不构成最终泛化/多重检验校正后的优越性证据。

### v0.3执行审查说明（2026-10-10）

本地Ridge/GRU也使用来源验证所选的alpha/hidden，以保持同一骨干和设置。因此这里的“本地”是仅在本地预算内拟合、采用来源选定超参数的匹配对照；不是完全没有来源先验、经本地独立优化的最优模型。源、目标信息边界不因这项说明而变化。

共同40 epochs不等于相同优化步数：约6521/6527个源样本每epoch约26个minibatches，而目标25–179标签每epoch一个minibatch。本次结果同时条件于既定训练计算方案。下一阶段若需要识别共享信息与训练计算量的作用，应在开发期增加预先规定的步数匹配对照；不得用当前结果单独断言差异全来自信息共享。

此说明来自代码执行审查，不修改已存核心代码、训练或评价规则，不追称预注册。所有2024–2025预测性能仍未计算。

## v0.4: Stage 3A finite diagnostics

See [STAGE3A_PROTOCOL.md](STAGE3A_PROTOCOL.md) for the prospective finite grid, purged budget-internal validation, disclosed source-assisted B30 tuning, causal source-proxy initialization, matched evaluation and stopping boundary. Prior versions and results are preserved. This is development exploration motivated by Stage 2, not retrospective preregistration.

## v0.5: authorized Stage3A evidence review and Stage3B

See STAGE3B_PROTOCOL.md for the prospective finite residual Ridge design, legal tuning, fallback, primary comparisons and freeze record. Historical versions above remain intact. Stage3A accepted version is stage3a_20261010_v3 and is reviewed from individual forecasts; existing source/GRU experiments are completed, not pending. New outputs use stage3b_20261011_v1.


## v0.6: Stage3C.1 metadata feasibility only (completed2026-10-12)

This phase preserved all Stage3B forecasts and fitted objects, audited the19 saved official queries and186 source candidates using onlypre2022 coverage/quality/name evidence, and downloaded a fixed7-day/9-gauge rainfall sample. The ten original development SiteIDs remain fixed; the two all-Suspect sample connections remain in outputs. There were no model fits or new forecasting scores.

The connection check explicitly treats current name-candidate polygon centroids as unverified spatial demonstrations.2025 polygon validity cannot establish historical catchments. Rainfall naive timestamps are checked under declared UTC/London and start/end scenarios; these checks prove only conditional arithmetic, not official interval/day semantics or release-time availability. Good complete true zeros are retained; missing/Suspect/incomplete intervals are not filled with zero or future data.

Independent target reservation must precede expansion and requires verified physical grouping. The next draft inconfigs/stage3c1_20261011_v1/next_experiment_draft.json isnot executable:execute_allowed=false. It declares a single rainfall feature change, legal history/normalization/CV, fixed finite grids, four primary comparisons and multiplicity handling, coverage/failure gates and a one-round stop. All five windows are used development, with window-stratified blocks. This is a review draft, not a completed rainfall experiment or retrospectively claimed preregistration. Do not auto-run it after this task.

## v0.7: Stage3C2 completed finite source-scale round

STAGE3C2_PROTOCOL.md/configs/stage3c2_source_scale_v1/FREEZE.json freeze prospective code/data/config. Missing normalized volume remains1+originalmask; only source size/composition changed. Matched local source-assisted selection remainsoriginalK3; new pools3/10/30×threeorders, one commonK3,37temporaryprotectedgroups. SixB30 primary contrasts use5000 synchronous within-window blocks thenSiteID resampling,14primary/7/28sensitivity. All300conditions/17policies completed onCPU; physical mappingfalse and final periodexcluded. Actual ordering, tolerance-checker fixes and incomplete tree-memory observation are explicitly disclosed inEXECUTION_NOTES.md. Old scientificbytes unchanged; stop after review.


## Stage3D completed (2026-10-12)

User-authorized post-C2 empirical interval development, stage3d_interval_v1: fixed Persistence centre, three frozen K30 pools, 1080 source folds/18 source-only gamma choices, 300 target conditions/324000 interval rows, no software/calibration failures. Source scales/errors for selection end2020; held-source pseudo2021; final source error libraries end2021. Initial B30/90/180 calibration freezes60origins; all evaluation remains2022–2023 used development. Published QA and unverified SiteID mapping retained. Main B30/order20261012/90% MIXTURE-vs-LOCAL skills +2.6407% h1, +2.1222% h3; both Bonferroni97.5%14-day intervals cross0. Coverage improvement costs wider intervals; no established history saving or stable shared-interval contribution, and C2 point-forecast conclusions unchanged. 40tests, full independent reconstruction, exact C2 byte preservation and 300-task cached resume passed. See STAGE3D_PROTOCOL.md, reports/stage3d_interval_v1/ANALYSIS_ZH.md and RUN_STATUS.json. STOP for review; packaging validation separately recorded in delivery/20261012_stage3d/PACKAGE_CHECKS.json.


## Stage3E有限证据审查（2026-10-13，已完成）

新协议STAGE3E_PROTOCOL.md、新配置configs/stage3e_evidence_review_v1/full.json；完成时证据seal不能称预注册。沿用D初始B30/90/180、5已用窗口、h1/3、3K30、发布后QA与SiteID探索分组。局部CDF/scale/gamma60起点冻结，合法后续观测只更新Persistence。新增运行封装同目录原子替换、flush/fsync/目录同步/readback/独立完成凭证，最多2次尝试；函数返回与磁盘完成分别计数。旧科学冻结SHA未修改。

主要比较仅重新核实D原order20261012_K30/B30/90%/raw MIXTURE vs LOCAL；14日5000同步时间块后整SiteID重采样，97.5%调整区间，7/28敏感性。新增站点/窗口/原单位贡献/LOO/误差分布加权KS/1—14、15—30、31—60分段均事后探索。部署误差不回流选择。旧跨预算和Q90高体积区间明确按原SHA关联，不把未全量复跑说成新执行。全部负结果保留；physical_mapping_verified=false、verified_real_time=false。执行完成记录见RUN_STATUS，干净解压小规模复算与package检查另列。唯一下一行动C NEEDS_DATA；本轮STOP。


## Stage3F资料回合与停止（2026-10-13）

STAGE3F_PROTOCOL.md/configs/stage3f_evidence_gate_v1/full.json限定只读旧交付、接收材料盘点、分级门槛和请求、有限新合法文献线索。没有新的模型、预测、选源或选gamma；原C2/D/E科学文件保留SHA。元数据请求范围核验和小补件CRC/SHA通过不表示设施、实时或创新已核实；旧修复的测试范围仍小规模/单进程。没有新历史映射，真实关系认证未执行，也未用合成夹具冒充。状态WAITING_FOR_EXTERNAL_EVIDENCE；A门槛不足未建立独立验证协议，之后草案也必须execute_allowed=false。
