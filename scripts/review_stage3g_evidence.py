#!/usr/bin/env python3
"""Independent saved-row risk-metric review and concise Chinese G analysis.

No model fit or parameter selection; imports no wastewater scientific code.
Report numbers come only from completed, saved development outputs.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
VERSION='stage3g_transfer_reliability_v1'
MAIN='similarity_residual_ridge_bias_selected'
POOL='order20261012_K30'
RESULTS=ROOT/'reports'/VERSION/'results'
REPORT=ROOT/'reports'/VERSION
KEYS=['pool_id','budget','horizon','risk_method']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def auc(event,score):
    event=np.asarray(event,float);score=np.asarray(score,float)
    mask=np.isfinite(event)&np.isfinite(score);e=event[mask];s=score[mask]
    n1=int((e==1).sum());n0=int((e==0).sum())
    if n1==0 or n0==0:return np.nan
    ranks=pd.Series(s).rank(method='average').to_numpy()
    return float((ranks[e==1].sum()-n1*(n1+1)/2)/(n1*n0))


def risk_recheck():
    data=pd.read_csv(ROOT/'runs'/VERSION/'full/reliability/target_risk_predictions.csv.gz',dtype={'site_id':str},float_precision='round_trip')
    rows=[]
    for key,g in data.groupby(KEYS+['site_id','episode']):
        base=dict(zip(KEYS+['site_id','episode'],key))
        e=g.large_error_event.to_numpy(float);s=g.risk_score.to_numpy(float);error=g.absolute_error_m3.to_numpy(float)
        for percentage in [10,20]:
            f=g[f'review_{percentage}pct'].to_numpy(float)
            valid=np.isfinite(e)&np.isfinite(s)&np.isfinite(error)&np.isfinite(f)
            ev=e[valid].astype(bool);flag=f[valid].astype(bool);events=int(ev.sum());n=int(valid.sum());nf=int(flag.sum());hits=int((ev&flag).sum())
            flags_available=np.isfinite(f)
            rows.append(dict(base,flag_budget_pct=percentage,within_auc=auc(e,s),event_count=events,evaluable_dates=n,
                actual_flag_fraction=nf/n if n else np.nan,flag_precision=hits/nf if nf else np.nan,
                missed_event_fraction=int((ev&~flag).sum())/events if events else np.nan,
                retained_mae_m3=float(error[valid][~flag].mean()) if (~flag).any() else np.nan,
                all_dates_mae_m3=float(error[valid].mean()) if n else np.nan,
                planned_dates=len(g),planned_flags_available=int(flags_available.sum()),
                flagged_all_available_dates=int(f[flags_available].sum()),
                actual_flag_fraction_all_available=float(f[flags_available].mean()) if flags_available.any() else np.nan))
    condition=pd.DataFrame(rows);condition.to_csv(REPORT/'audit/INDEPENDENT_RISK_BY_CONDITION.csv',index=False)
    recorded=pd.read_csv(RESULTS/'reliability_summary.csv');check=[]
    for key,g in condition.groupby(KEYS+['flag_budget_pct']):
        base=dict(zip(KEYS+['flag_budget_pct'],key));subset=recorded
        for k,v in base.items():subset=subset[subset[k].eq(v)]
        if len(subset)!=1:raise AssertionError('Missing/duplicated saved risk summary')
        expected=subset.iloc[0]
        macro=g.groupby('site_id')[['within_auc','actual_flag_fraction','flag_precision','missed_event_fraction','retained_mae_m3','all_dates_mae_m3','actual_flag_fraction_all_available']].mean().mean()
        mappings={'within_auc':'macro_within_site_window_auc', 'actual_flag_fraction':'macro_actual_flag_fraction',
            'flag_precision':'macro_flag_precision','missed_event_fraction':'macro_missed_event_fraction',
            'retained_mae_m3':'macro_retained_mae_m3','all_dates_mae_m3':'macro_all_dates_mae_m3'}
        for source,target in mappings.items():
            if not np.isclose(macro[source],expected[target],atol=1e-10,rtol=1e-12,equal_nan=True):
                raise AssertionError('Independent macro risk metric differs: '+target)
        check.append(dict(base,**{'independent_'+target:macro[source] for source,target in mappings.items()},
            actual_flag_fraction_all_available=macro['actual_flag_fraction_all_available'],
            all_planned_dates=int(g.planned_dates.sum()),all_flags_available=int(g.planned_flags_available.sum()),
            flags_all_available_dates=int(g.flagged_all_available_dates.sum()),event_count=int(g.event_count.sum()),
            evaluable_dates=int(g.evaluable_dates.sum()),passed=True))
    pd.DataFrame(check).to_csv(REPORT/'audit/INDEPENDENT_RISK_METRIC_RECHECK.csv',index=False)
    return recorded,condition,pd.DataFrame(check),data


def percent(value):return 'NA' if pd.isna(value) else f'{value*100:+.2f}%'
def plain_percent(value):return 'NA' if pd.isna(value) else f'{value*100:.2f}%'
def number(value,digits=3):return 'NA' if pd.isna(value) else f'{value:.{digits}f}'
def table(header,rows):return '| '+' | '.join(header)+' |\n| '+' | '.join(['---']*len(header))+' |\n'+'\n'.join('| '+' | '.join(map(str,r))+' |' for r in rows)


def main():
    status=json.loads((RESULTS/'evaluation_validation.json').read_text())
    if status['status']!='COMPLETED':raise ValueError('Cannot review an incomplete G round')
    risk,conditions,ind_risk,risk_rows=risk_recheck()
    intervals=pd.read_csv(RESULTS/'paired_block_intervals.csv');pairs=pd.read_csv(RESULTS/'paired_comparisons_by_station.csv',dtype={'site_id':str})
    primary=intervals[(intervals.constraint=='raw')&(intervals.subset=='all_dates')&(intervals.block_days==14)&intervals.co_primary]
    metrics=pd.read_csv(RESULTS/'metrics_by_station.csv',dtype={'site_id':str});summary=pd.read_csv(RESULTS/'summary.csv')
    choices=pd.read_csv(RESULTS/'parameter_choices.csv');weights=pd.read_csv(RESULTS/'weighting_diagnostics_summary.csv')
    fallbacks=pd.read_csv(RESULTS/'lambda_fallback.csv');high=pd.read_csv(RESULTS/'high_volume_summary.csv')
    cross=intervals[(intervals.pool_id==POOL)&(intervals.constraint=='raw')&(intervals.subset=='all_dates')&(intervals.block_days==14)&(intervals.kind=='history_budget_comparison')]
    primary_rows=[]
    for row in primary.itertuples():
        label='Persistence' if row.reference=='persistence' else '匹配均匀共享+bias'
        primary_rows.append([row.horizon,label,percent(row.mean_station_skill),f'[{percent(row.lower_ci)}, {percent(row.upper_ci)}]',f'{row.winning_stations}/{row.negative_transfer_stations}'])
    negative=[]
    for h in [1,3]:
        for reference in ['persistence','local_residual_ridge_selected']:
            q=pairs[(pairs.pool_id==POOL)&(pairs.model==MAIN)&(pairs.budget==30)&(pairs.reference_budget==30)&(pairs.horizon==h)&(pairs.reference==reference)&(pairs.constraint=='raw')]
            ids=', '.join(q.loc[q.skill < -1e-12,'site_id'])
            negative.append(f'- h={h}相对{"Persistence" if reference=="persistence" else "同预算本地残差Ridge"}：{ids or "无"}。')
    cross_rows=[[int(r.budget),int(r.reference_budget),int(r.horizon),percent(r.mean_station_skill),f'[{percent(r.lower_ci)}, {percent(r.upper_ci)}]',number(r.equal_station_absolute_mae_difference_m3,2)] for r in cross.itertuples()]
    comp=summary[(summary.constraint=='raw')&(summary.model==MAIN)]
    comp_rows=[]
    for budget,horizon in [(30,1),(30,3),(90,1),(90,3),(180,1),(180,3)]:
        row=[budget,horizon]
        for pool in ['order20261012_K30','order20261013_K30','order20261014_K30']:
            q=comp[(comp.pool_id==pool)&(comp.budget==budget)&(comp.horizon==horizon)]
            row.append(percent(q.iloc[0].mean_skill))
        comp_rows.append(row)
    risk_sub=risk[(risk.pool_id==POOL)&(risk.budget==30)];risk_table=[]
    names={'logistic':'Logistic','random':'随机','missing_rate':'缺失率','prediction_persistence_difference':'预测差幅规则'}
    for row in risk_sub.itertuples():
        risk_table.append([row.horizon,names[row.risk_method],row.flag_budget_pct,number(row.macro_within_site_window_auc),
            plain_percent(row.macro_actual_flag_fraction),plain_percent(row.macro_flag_precision),plain_percent(row.macro_missed_event_fraction)])
    main_metrics=metrics[(metrics.constraint=='raw')&(metrics.pool_id==POOL)&(metrics.model==MAIN)&(metrics.budget==30)]
    dimension_rows=[]
    for h in [1,3]:
        q=main_metrics[main_metrics.horizon==h]
        dimension_rows.append([h,number(q.paired_mae_m3_vs_persistence.mean(),2),number(q.persistence_mae_m3.mean(),2),number(q.rmse_m3.mean(),2),f'{q.paired_dates_vs_persistence.min()}–{q.paired_dates_vs_persistence.max()}'])
    high_rows=[]
    for row in high[(high.constraint=='raw')&(high.pool_id==POOL)&(high.model==MAIN)&(high.budget==30)].itertuples():
        high_rows.append([row.horizon,percent(row.mean_skill),row.winning_stations,row.worse_stations,f'{row.min_dates}–{row.max_dates}'])
    calibration=risk_rows[(risk_rows.budget==30)&(risk_rows.risk_method=='logistic')][['site_id','episode','horizon','threshold_error_samples']].drop_duplicates()
    calibration.to_csv(REPORT/'audit/B30_INITIAL_ERROR_CALIBRATION_COUNTS.csv',index=False)
    ntext='；'.join(f'h={h}：{int(q.threshold_error_samples.min())}–{int(q.threshold_error_samples.max())}' for h,q in calibration.groupby('horizon'))
    sensitivity=intervals[(intervals.constraint=='raw')&(intervals.subset=='all_dates')&(intervals.reference=='persistence')&intervals.co_primary]
    sensitivity_rows=[[r.horizon,r.block_days,percent(r.mean_station_skill),f'[{percent(r.lower_ci)}, {percent(r.upper_ci)}]'] for r in sensitivity.itertuples()]
    fallback=weights[(weights.pool_id==POOL)&(weights.model==MAIN)&(weights.budget==30)]
    lf=fallbacks[(fallbacks.pool_id==POOL)&(fallbacks.model==MAIN)&(fallbacks.budget==30)]
    point=pd.read_csv(REPORT/'audit/INDEPENDENT_PRIMARY_POINT_METRICS.csv',dtype={'site_id':str})
    # This independent table is a separate row-level reconstruction, not the
    # same evaluator's saved pass flag. Compare its per-SiteID matched metrics.
    for h in [1,3]:
        actual=point[(point.reference=='persistence')&(point.horizon==h)].set_index('site_id')
        expected=main_metrics[main_metrics.horizon==h].set_index('site_id').reindex(actual.index)
        if not np.allclose(actual.skill,expected.skill_vs_persistence,atol=1e-12,rtol=1e-12,equal_nan=True):raise AssertionError('Independent point skills differ')
    text=f'''# Stage3G中文证据分析

本轮预定开发矩阵真实完成：300个目标条件，432000条八方法点预测及18000条固定权重打乱预测；216000条四规则风险评分；三池719280条源侧候选成绩、45360条分角色源预测及60480条外层风险OOF评分均保留。计算完成与科学收益成立分别判断。没有新GRU、天气、区间、最终2024—2025/保护池性能或论文/App。

## 主要点预测问题没有获得支持

主池order20261012_K30、B30、未裁零、逐SiteID先算技能再等权平均；14天窗口内同步日历块与SiteID层重采样5000次，四主要比较Bonferroni后98.75%区间：

{table(['h','参考','平均逐SiteID技能','98.75%区间','获胜/负技能测点数'],primary_rows)}

区间跨0表示不确定，不能宣布稳定收益，也不能据此证明所有共享方法均无效。这里的均匀对照[0,0]来自预测逐条相同的数学退化；不是通过统计检验证明两个不同方法等效。

预先规定7/28天块敏感性同样完整保留，相对Persistence结果如下；h3的28天块调整区间为负，不能因它不利而只展示跨0的14天主区间，也不能事后换成最有利块长：

{table(['h','块长/天','平均逐SiteID技能','98.75%区间'],sensitivity_rows)}

{table(['h','主候选匹配日期MAE/m³','Persistence匹配日期MAE/m³','主候选等权RMSE/m³','每SiteID配对日期数'],dimension_rows)}

原单位均值与相对技能是不同估计量，不能用合并总水量MAE比冒充平均设施技能。10个SiteID共每h2970个可评分日期，仍不是2970座厂；余下预定日期及原因在availability/paired_date_index保留。B30初始Persistence误差校准实际样本{ntext}，名义30天不是30个完整训练或校准样本。

## 新权重机制与公平对照

源侧合法验证在主B30两时距均选择eta=0：源权重全为1/30，有效源数30、最大权重3.33%，描述不足回退0%。这仍是均匀共享，不是退回Persistence。h1选alpha=.0001、lambda=.5，h3选alpha=.0001、lambda=1；主候选lambda=0比例两者均0%。匹配均匀+bias选参相同，预测逐条相同。三固定seed的权重打乱已实际执行并完整保存，但均匀权重被打乱仍一样，因此消融无辨识度，不能证明相似源匹配机制。种子均值只是损失均值；不组成预测集成，也不是充分的置换显著性检验。

G全部共享预算使用同一源侧选参方案；本地B90/180用预算内顺序验证，本地B30/不足条件使用主K30源辅助选参。与C2共享B90/180的内部验证规则不同，旧结果保留为历史参考，不把新旧差解释成权重效应。对相同骨干的均匀共享做匹配比较，不能把新增网格自由度全部归因相似性。主候选对本地直接Ridge的B30平均技能h1+32.50%、h3+25.77%，但对强本地残差h1−0.31%、h3−6.93%；超过较弱direct不能证明优于Persistence或存在工程价值。

三既定源组成全部报告，以下为主候选对Persistence技能；后两池不是可替换主池的选择集：

{table(['初始B','h','主20261012','敏感性20261013','敏感性20261014'],comp_rows)}

较长预算的部分敏感性配置有探索性正收益，与源组成有关；不能升级为预定B30主要成功。权重集中度及每任务alpha/lambda/bias、回退均见parameter_choices、weighting_diagnostics_summary和source_weights_all。

## 负迁移与历史需求

主B30正式评价保留全部SiteID。相对不同参考的负迁移名单必须分开：

{chr(10).join(negative)}

跨预算比较均按同起点/目标日期配对，使用原单位MAE再计算逐SiteID收益。下面95%区间属于次要探索分析，m³差为共享减本地：

{table(['共享B','本地残差B','h','平均逐SiteID收益','95%区间','等权MAE差/m³'],cross_rows)}

目前没有结果之前确定的工程非劣/等效界限；这些区间跨0不能作等效、非劣或已节省历史结论。共享短历史未稳定超过Persistence，因此最多描述模型相对的跨预算表现。

## 风险模块识别的是条件差异，日内识别没有成立

来源关联组隔离的五外折中，基础拟合/上游选择12组、风险训练6组、操作校准6组、评价6组分开；外层评价组未参与任何上游步骤。所有风险概率和操作阈值先在源侧冻结；目标部署误差仅用于评分。源2021 OOF是允许源年结束后为2022部署构建的回顾组隔离证据，不能称2021年1月已在线运行。源风险训练6组→最终30组、基础12组→目标30组及14天源伪部署→60天目标部署的分布变化仍是局限。

主B30日内AUC宏平均是先同SiteID/窗口，再等权SiteID；仅包含有两类事件的条件，单类情况保留NA并报告。50个SiteID×窗口条件中h1有7个、h3有9个单类，不能当成满额50个有效AUC。Logistic日内AUC h1=.481、h3=.452；全部日期混合AUC却.587/.692，跨SiteID/窗口平均风险—事件率Spearman=.546/.697。这说明条件整体难度的分离不能替代同一设施窗口内危险日识别，也不能解释为物理原因。

{table(['h','规则','源预期标记%','同SiteID/窗口宏AUC','目标实际标记%','标记精确率','大误差漏报%'],risk_table)}

表中工作量与精确率采用既定可评分日期口径；精确率只在已标记条件定义，无标记条件为NA，不填0，宏平均对应的有效条件分母不同，应结合by_site_window中的precision_denominator/no_flags列读取。独立audit/INDEPENDENT_RISK_METRIC_RECHECK另报全部预定/flag可用日期的操作计数，区分未来真值缺失日期。Logistic源10%阈值实际只标记约3–4%，并漏掉约95–96%的大误差；源20%阈值实标约13–16%，漏报仍约83–85%。在每h的3000个预定日期中有2999个flag可用，h1两个阈值共标记99/475次，h3为117/379次。它没有优于简单规则的稳定日内证据。预测差幅规则在h1日内AUC=.609，但10/20%源阈值在目标需要约27%/41%复核，不能忽略代价，也不能据开发标签回调阈值。全部风险规则不会修复或更改预测。

大误差是超过各任务初始允许历史Persistence误差Q90，不是工程故障、许可或容量阈值。风险—保留曲线是离线描述，不把事后最优点变成可部署阈值。该模块保持点预测原样；未把旧D区间直接移植到G。

## 高体积、核验与允许主张

高体积阈值统一来自各窗口初始最后30天合法历史Q90，仅用未来真值做事后条件评分：

{table(['h','主B30高体积技能','获胜SiteID','负技能SiteID','每SiteID子集日期'],high_rows)}

该子集不取代全部日期主要分析，不称容量/溢流。raw与全方法max(0,pred)均保留，未选择性裁零；7/28天块区间、全部源组成/预算/窗口、失败或缺失日期均在CSV。未来性能未读取；日观测与QA真实到达仍未证实，物理分组仍provisional。

关键点预测逐条独立重算见audit/INDEPENDENT_PRIMARY_POINT_METRICS.csv；风险概率/源训练变换/864源阈值与flag逐条独立核验见INDEPENDENT_RISK_CHECK_FULL.json；风险AUC用独立秩统计及宏平均重算，见INDEPENDENT_RISK_METRIC_RECHECK.csv。无量纲1e−12、m³1e−8绝对/1e−12相对是数值容差核验，不叫逐位相同。首个独立审计将无量纲容差误用于m³的失败日志保留，修复仅影响审计器，不改冻结科学文件。软件通过不等于核心创新成立。

当前可保留研究问题、严格预算/信息边界、强Persistence公平基准、负迁移和适用边界的SiteID级回顾证据；不能宣称新算法创新、稳定共享提升、一般历史节省、逐厂危险日预警有效、独立物理水厂外部验证或实时工程收益。既有GRU/区间负结果与局部正结果原样保留；本轮Ridge失败不能否定全部共享/深度方法。

## 唯一下一行动与停止

优先取得提供方的稳定历史设施—SiteID—正常处理后出水测点分组及日期/观测/QA可用性说明，并由导师明确一个预测使用场景与有意义的误差/复核代价。以此判断是否值得开展明确限定的独立回顾验证；这是一项工程证据补齐行动，不是新调参轮次。没有稳定加权或日内风险收益的当前证据，不支持自动加GRU、雨量、源池或滚动校准。精确坐标不是本轮无空间输入回顾验证的必需门槛。

Stage3G预定矩阵完成后STOP，等待审查。最终或保护集合仍封存，任何后续方案execute_allowed=false；补齐元数据不会自动提高分数或证明原正向假设。
'''
    (REPORT/'ANALYSIS_ZH.md').write_text(text)
    (REPORT/'NEXT_ACTION.md').write_text('''# Stage3G唯一下一行动\n\nSTOP_FOR_REVIEW；execute_allowed=false。\n\n取得并审查外部工程证据：提供方给出有有效期的稳定（可匿名）物理设施—SiteID—正常处理后出水测点分组/关联关系及日体积日期含义、观测与QA到达时点；导师确认一个具体使用场景和有意义误差/复核负担。复用Stage3F未发送请求，不自动联系。\n\n理由：主B30源验证选择eta=0；点预测未超过Persistence，Logistic没有优于简单规则的同SiteID/窗口日内识别，历史节省没有工程界限或稳定证据。部分次要配置的正收益不足以支持继续无界搜索或自动GRU扩展。\n\n收到资料后先检查关联泄漏、证据强度及研究使用边界，再决定是否冻结一个独立回顾验证草案；本轮不打开2024—2025或保护池性能。无法取得资料则保留SiteID级回顾基准/负迁移证据，重新评估工程价值与期刊匹配，不冒充独立水厂验证。\n\n停止条件：本轮交付后等待用户审查及新的明确授权。取得元数据不构成自动执行最终验证的许可，也不自动证明共享收益。\n''')
    claims=[
        ('G1','相似性加权改善主B30预测','NOT_SUPPORTED','paired_block_intervals.csv','h1 −0.312%; h3 −7.576%; adjusted intervals cross0','主两时距eta=0;同均匀逐条相同','当前开发结果未证明加权稳定收益'),
        ('G2','相似源匹配机制','NOT_ESTABLISHED','weighting_diagnostics_summary.csv;shuffle_mechanism_block_intervals.csv','主权重全部均匀，三seed消融同值','次要非均匀条件未做充分机制确认','固定四描述下主源选择未支持非均匀权重'),
        ('G3','共享减少初始历史','NOT_ESTABLISHED','cross_budget_intervals.csv','主跨预算CI跨0;部分点估计不利','无工程等效/非劣界;未稳定超过Persistence','报告跨预算表现，不宣称已节省历史'),
        ('G4','预测前识别同厂危险日','NOT_SUPPORTED','reliability_summary.csv;reliability_by_site_window.csv','主日内宏AUC .481/.452;漏报高','源→目标分布迁移;单类/少事件条件','未证明固定Logistic优于简单日内规则'),
        ('G5','识别整体较难部署条件','EXPLORATORY_LIMITED','reliability_summary.csv','between-condition Spearman .546/.697; pooled AUC .587/.692','非日内识别;仅已用10SiteID开发;非物理因果','来源交叉拟合风险分数与开发条件事件率存在关联'),
        ('G6','所有共享学习无效','NOT_ALLOWED','summary.csv;Stage2/3A archives','若干源组成/长预算有正收益，其他骨干仍有边界','本轮仅固定Ridge方向，不能穷尽模型','当前固定设计未证明稳定共享收益'),
        ('G7','独立物理设施泛化','NOT_VERIFIED','configs/stage3g_transfer_reliability_v1/full.json;Stage3F EVIDENCE_GATES.csv','physical_mapping_verified=false','尚缺有有效期的正式关联关系','SiteID级回顾探索结果'),
        ('G8','实时部署和工程收益','NOT_VERIFIED','STAGE3G_PROTOCOL.md;Stage3F evidence','released-Good QA理想化;不调整预测','实际观测/QA到达、使用场景及复核成本未知','发布后QA回顾实验，不称实时工程验证'),
    ]
    pd.DataFrame(claims,columns=['claim_id','proposed_claim','evidence_status','result_source','observed_evidence_or_counterexample','limitations_or_missing_evidence','allowed_wording']).to_csv(REPORT/'CLAIM_EVIDENCE_MATRIX.csv',index=False)
    sources=[RESULTS/x for x in ['paired_block_intervals.csv','paired_comparisons_by_station.csv','metrics_by_station.csv','summary.csv','reliability_summary.csv','weighting_diagnostics_summary.csv','high_volume_summary.csv']]
    receipt=dict(status='PASSED',new_model_fits=0,script_sha256=sha(Path(__file__)),sources_sha256={str(x.relative_to(ROOT)):sha(x) for x in sources},
        point_metrics_independent_rows=80,risk_macro_comparisons_checked=len(ind_risk),risk_saved_rows_checked=len(risk_rows),
        scientific_files_changed=False,decisions_from_completed_development_only=True,final_or_protected_performance_used=False)
    (REPORT/'audit/REPORT_EVIDENCE_REVIEW.json').write_text(json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps(dict(status='PASSED',reports=['ANALYSIS_ZH.md','NEXT_ACTION.md','CLAIM_EVIDENCE_MATRIX.csv'],risk_macro_rechecked=len(ind_risk)),ensure_ascii=False))


if __name__=='__main__':main()
