#!/usr/bin/env python3
"""Plot saved Stage3G development evidence; never fit or select a model.

The five display families and their primary subsets are fixed before target
scoring. Each export keeps the complete input table, source SHA, and an English
caption. Undefined values remain visible as NA rather than optimistic zeros.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

os.environ.setdefault("MPLCONFIGDIR", "/tmp/wastewater-stage3g-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
VERSION = "stage3g_transfer_reliability_v1"
SITES = [str(x) for x in [13013,13015,13016,13017,13022,13024,13025,13028,13029,13031]]
POOLS = [f"order{x}_K30" for x in (20261012,20261013,20261014)]
WINDOWS = ["2022-01-01","2022-07-01","2023-01-01","2023-07-01","2023-10-01"]
NOTE = "Reused 2022–2023 development history; SiteID groups and retrospective QA; facility independence and real-time availability unverified."
COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7"]
MODEL_LABELS={"similarity_residual_ridge_bias_selected":"Similarity + bias",
              "uniform_residual_ridge_bias_selected":"Uniform + bias",
              "local_residual_ridge_selected":"Local residual"}
RISK_LABELS={"logistic":"Logistic", "random":"Random",
             "missing_rate":"Missing-rate", "prediction_persistence_difference":"|Shared − Persistence|"}


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return pd.read_csv(path, dtype={"site_id":str,"pool_id":str}, low_memory=False)


def require(frame, columns, table):
    missing = set(columns)-set(frame.columns)
    if missing:
        raise ValueError(f"{table}: missing saved columns {sorted(missing)}")


def select(frame, **conditions):
    result = frame
    for col,value in conditions.items():
        if col not in result:
            raise ValueError(f"Required selector column {col} missing")
        result = result[result[col].eq(value)]
    return result


def raw(frame):
    if "constraint" in frame:
        return select(frame,constraint="raw")
    return frame


def style(ax, zero=False):
    ax.spines[["top","right"]].set_visible(False)
    ax.grid(axis="y",color="#dddddd",linewidth=.5,zorder=0)
    if zero:
        ax.axhline(0,color="#777777",linewidth=.8)


def save(fig, output, name):
    for extension in ["png","pdf","svg"]:
        fig.savefig(output/f"{name}.{extension}",dpi=175,bbox_inches="tight")
    plt.close(fig)


def footnote(fig, extra=""):
    fig.text(.5,.017,NOTE,ha="center",fontsize=7.4)
    if extra:
        fig.text(.5,.053,extra,ha="center",fontsize=8)


def save_table(frame, output, name):
    frame.to_csv(output/f"{name}_plotting.csv",index=False)


def site_skills(metrics, pairs, output, models):
    require(metrics,["site_id","pool_id","model","budget","horizon","skill_vs_persistence"],"metrics_by_station")
    save_table(metrics,output,"site_skills_complete")
    save_table(pairs,output,"paired_negative_transfer_complete")
    data = select(raw(metrics),pool_id=POOLS[0],budget=30)
    fig,axes=plt.subplots(1,2,figsize=(12.7,5.3),sharey=True)
    y=np.arange(10)
    for ax,h in zip(axes,(1,3)):
        for index,model in enumerate(models):
            q=select(data,horizon=h,model=model).set_index("site_id")
            if q.index.duplicated().any() or not set(SITES).issubset(q.index):
                raise ValueError(f"All ten SiteID records required: {model}, h={h}")
            values=q.reindex(SITES).skill_vs_persistence.to_numpy(float)*100
            ax.scatter(values,y+(index-(len(models)-1)/2)*.16,s=30,
                       color=COLORS[index],label=MODEL_LABELS.get(model,model),zorder=3)
            for yy,x in zip(y,values):
                if not np.isfinite(x):
                    ax.text(0,yy,"NA",fontsize=7,color=COLORS[index])
        ax.axvline(0,color="#777777",lw=.8)
        ax.grid(axis="x",color="#dddddd",lw=.5)
        ax.spines[["top","right"]].set_visible(False)
        ax.set_yticks(y,SITES);ax.set_title(f"h={h}; B30; main source composition")
        ax.set_xlabel("Per-SiteID MAE skill vs Persistence (%)")
    axes[0].invert_yaxis();axes[0].set_ylabel("Development SiteID")
    axes[1].legend(loc="best",fontsize=7,frameon=False)
    fig.suptitle("Prediction skill retains all ten target SiteIDs",y=.99)
    footnote(fig,"Positive skill means lower MAE; negative values remain in the formal evaluation.")
    fig.tight_layout(rect=(0,.11,1,.94));save(fig,output,"site_skills_and_negative_transfer")


def cross_budget(table, intervals, output, main_model):
    save_table(table,output,"cross_budget_complete")
    save_table(intervals,output,"cross_budget_intervals_complete")
    require(table,["site_id","pool_id","budget","horizon","model","reference_budget","skill"],"cross_budget_by_station")
    q=select(raw(table),pool_id=POOLS[0],model=main_model)
    contrasts=[(30,90),(30,180),(90,180)]
    fig,axes=plt.subplots(1,2,figsize=(12.6,4.8),sharey=True)
    for ax,h in zip(axes,(1,3)):
        for index,(b,ref_b) in enumerate(contrasts):
            z=select(q,budget=b,reference_budget=ref_b,horizon=h)
            if "reference_model" in z:
                refnames=sorted(z.reference_model.unique())
                local=[m for m in refnames if "residual" in m.lower() and "local" in m.lower()]
                if len(local)==1:z=select(z,reference_model=local[0])
            if len(z)!=10 or set(z.site_id)!=set(SITES):
                raise ValueError("Cross-budget plot requires ten paired SiteIDs per fixed contrast")
            vals=z.set_index("site_id").reindex(SITES).skill.to_numpy(float)*100
            ax.scatter(index+np.linspace(-.13,.13,10),vals,s=23,color=COLORS[index],alpha=.7)
            finite=vals[np.isfinite(vals)]
            if len(finite):ax.plot([index-.2,index+.2],[np.mean(finite)]*2,color="black",lw=2)
        style(ax,True);ax.set_xticks(range(3),[f"Shared B{b}\nvs local B{r}" for b,r in contrasts])
        ax.set_title(f"h={h}; main source composition")
    axes[0].set_ylabel("Per-SiteID MAE skill vs longer-history local model (%)")
    fig.suptitle("Cross-budget performance is distinct from demonstrated engineering history saving",y=.99)
    footnote(fig,"Points: ten SiteIDs; black marks: equal-SiteID means. No engineering non-inferiority margin was supplied.")
    fig.tight_layout(rect=(0,.13,1,.92));save(fig,output,"cross_budget_comparison")


def weight_concentration(parameters, summary, output, main_model):
    save_table(parameters,output,"source_weight_concentration_complete")
    save_table(summary,output,"three_pool_robustness_complete")
    require(parameters,["pool_id","budget","horizon","model","effective_source_count","maximum_source_weight"],"parameter_choices")
    require(summary,["pool_id","budget","horizon","model","mean_skill"],"summary")
    param=select(parameters,model=main_model,budget=30)
    sm=select(raw(summary),model=main_model,budget=30)
    fig,axes=plt.subplots(1,3,figsize=(13.7,4.7))
    for j,pool in enumerate(POOLS):
        pq=select(param,pool_id=pool)
        for h,marker,offset in [(1,"o",-.08),(3,"s",.08)]:
            z=select(pq,horizon=h)
            vals=z.effective_source_count.to_numpy(float)
            axes[0].scatter(np.full(len(z),j+offset),vals,color=COLORS[j],marker=marker,s=17,alpha=.6)
            axes[1].scatter(np.full(len(z),j+offset),z.maximum_source_weight.to_numpy(float)*100,color=COLORS[j],marker=marker,s=17,alpha=.6)
            row=select(sm,pool_id=pool,horizon=h)
            if len(row)!=1:raise ValueError("One raw mean-skill row per pool and horizon required")
            axes[2].scatter(j+offset,float(row.iloc[0].mean_skill)*100,color=COLORS[j],marker=marker,s=65)
    axes[0].axhline(30,color="#777777",lw=.8,ls="--")
    axes[0].set_ylabel("Effective source count: 1 / Σ w²")
    axes[1].set_ylabel("Maximum source weight (%)")
    axes[2].set_ylabel("Equal-SiteID MAE skill vs Persistence (%)");style(axes[2],True)
    for ax in axes:
        style(ax);ax.set_xticks(range(3),[f"{p[5:13]}\n{'main' if i==0 else 'sensitivity'}" for i,p in enumerate(POOLS)])
    axes[0].set_title("Concentration per deployment");axes[1].set_title("Single-source dominance");axes[2].set_title("All fixed source compositions")
    fig.suptitle("Source-weight concentration and composition sensitivity: main candidate, B30",y=.99)
    footnote(fig,"Circle: h=1; square: h=3. Five windows per SiteID are repeated development conditions, not independent facilities.")
    fig.tight_layout(rect=(0,.13,1,.93));save(fig,output,"source_weights_and_composition")


def reliability(curves, burden, by_site, output):
    save_table(curves,output,"reliability_retention_complete")
    save_table(burden,output,"reliability_burden_complete")
    save_table(by_site,output,"reliability_site_discrimination_complete")
    require(curves,["pool_id","budget","horizon","risk_method","retention_fraction","retained_mae_m3"],"risk_retention_summary")
    require(burden,["pool_id","budget","horizon","risk_method","flag_budget_pct","macro_actual_flag_fraction","macro_flag_precision","macro_missed_event_fraction"],"reliability_summary")
    c=select(curves,pool_id=POOLS[0],budget=30)
    b=select(burden,pool_id=POOLS[0],budget=30)
    methods=sorted(c.risk_method.unique())
    fig,axes=plt.subplots(2,2,figsize=(12.4,8.2))
    for col,h in enumerate((1,3)):
        ax=axes[0,col]
        for index,method in enumerate(methods):
            z=select(c,horizon=h,risk_method=method).sort_values("retention_fraction")
            ax.plot(z.retention_fraction*100,z.retained_mae_m3,color=COLORS[index%4],lw=1.6,label=RISK_LABELS.get(method,method))
        style(ax);ax.set_xlabel("Predictions retained after offline ranking (%)")
        ax.set_ylabel("Macro-average retained MAE (m³)");ax.set_title(f"h={h}: offline curve, B30")
        bx=axes[1,col]
        for index,method in enumerate(methods):
            z=select(b,horizon=h,risk_method=method)
            agg=z.set_index("flag_budget_pct").sort_index()
            bx.plot(agg.macro_actual_flag_fraction*100,agg.macro_missed_event_fraction*100,marker="o",color=COLORS[index%4],label=RISK_LABELS.get(method,method))
            annotation_offsets={"logistic":(4,4),"missing_rate":(-25,-12),
                                "prediction_persistence_difference":(4,4),"random":(4,10)}
            for target,row in agg.iterrows():
                bx.annotate(f"{target}%",(row.macro_actual_flag_fraction*100,row.macro_missed_event_fraction*100),fontsize=7,xytext=annotation_offsets.get(method,(4,4)),textcoords="offset points")
        style(bx);bx.set_xlabel("Actual flag fraction (%)");bx.set_ylabel("Large-error events missed (%)")
        bx.set_title(f"h={h}: fixed source-calibrated review thresholds")
    axes[0,1].legend(fontsize=7,frameon=False);axes[1,1].legend(fontsize=7,frameon=False)
    fig.suptitle("Reliability ranking and review burden are evaluated separately",y=.99)
    footnote(fig,"Equal SiteID/window macro means. Offline curves do not choose target rules; fixed source 10/20% thresholds remain unchanged.")
    fig.tight_layout(rect=(0,.095,1,.95));save(fig,output,"reliability_retention_and_review_cost")


def high_volume(table, output, models):
    save_table(table,output,"high_volume_complete")
    require(table,["site_id","pool_id","budget","horizon","model","n_dates","skill_vs_persistence"],"high_volume_metrics_by_station")
    q=select(raw(table),pool_id=POOLS[0],budget=30)
    fig,axes=plt.subplots(1,2,figsize=(12.5,5.0),sharey=True)
    for ax,h in zip(axes,(1,3)):
        for index,model in enumerate(models):
            z=select(q,horizon=h,model=model).set_index("site_id").reindex(SITES)
            vals=z.skill_vs_persistence.to_numpy(float)*100
            ax.scatter(vals,np.arange(10)+(index-(len(models)-1)/2)*.16,s=27,color=COLORS[index],label=MODEL_LABELS.get(model,model))
        ax.axvline(0,color="#777777",lw=.8);ax.grid(axis="x",color="#dddddd",lw=.5)
        ax.spines[["top","right"]].set_visible(False);ax.set_yticks(range(10),SITES)
        ax.set_xlabel("MAE skill on historical-Q90 high-volume dates (%)");ax.set_title(f"h={h}; B30; main source composition")
    axes[0].invert_yaxis();axes[0].set_ylabel("Development SiteID");axes[1].legend(fontsize=7,frameon=False)
    fig.suptitle("High-volume subset: fixed initial-history thresholds, all ten SiteIDs",y=.99)
    footnote(fig,"Thresholds come from permitted initial history. Evaluation labels define this retrospective subset; Q90 is not capacity or overflow.")
    fig.tight_layout(rect=(0,.12,1,.93));save(fig,output,"high_volume_conditions")


def export_check(output):
    records=[]
    for svg in sorted(output.glob("*.svg")):
        if svg.stem == "editableflow":
            continue
        xml=ET.parse(svg).getroot()
        images=sum(e.tag.endswith("}image") for e in xml.iter())
        texts=sum(e.tag.endswith("}text") for e in xml.iter())
        if images:raise ValueError(f"Unexpected raster in scientific vector chart {svg.name}")
        if not texts:raise ValueError(f"No editable vector text in {svg.name}")
        record={"name":svg.stem,"raster_images":images,"svg_text_nodes":texts}
        for ext in ["png","pdf","svg"]:
            p=output/f"{svg.stem}.{ext}"
            if not p.is_file() or p.stat().st_size==0:raise ValueError(f"Missing chart {p}")
            record[ext]={"bytes":p.stat().st_size,"sha256":sha256(p)}
        records.append(record)
    if len(records)!=5:raise ValueError("Five prescribed scientific figure families must be present")
    return records


def executed_flow(results, output):
    """Create editable nodes/arrows only when the registered round completed."""
    receipt=results/"evaluation_validation.json"
    status=json.loads(receipt.read_text())
    if status.get("status")!="COMPLETED":
        raise ValueError("A partial round cannot be drawn as an executed workflow")
    # Text and geometry are shared by the .drawio source and vector preview.
    nodes=[
      ("title",20,12,1510,48,"Stage3G: executed bounded development experiment", "#ffffff"),
      ("source",30,98,255,104,"Fixed three K30 SiteID pools\nSource training: 2016–2021\nNo protected group or\n2024–2025 performance", "#e7f1fa"),
      ("past",350,98,280,104,"Source selection / cross-fitting\nBase fitting + descriptors end 2020\nPseudo-deployments: Jan/Jul 2021, 14 origins", "#e7f1fa"),
      ("roles",695,98,350,104,"Five group-isolated outer folds\nBase fit: 12 groups; risk train: 6\nThreshold calibration: 6; evaluation: 6", "#e7f1fa"),
      ("inner",1110,98,390,104,"Inner three-fold group CV on base-fit groups only\nAlpha/lambda/eta selection and descriptor scaling\nHeld-out outer groups excluded upstream", "#e7f1fa"),
      ("base",50,284,280,112,"Source base prediction is sample-out\nOnly each role's permitted initial B days\nPersistence + residual Ridge + legal local bias", "#e7f1fa"),
      ("risktrain",405,284,285,112,"Risk-training role: six groups\nFixed logistic regression, three inputs\nImputation + standardization fitted here", "#fff2d8"),
      ("riskcal",760,284,290,112,"Separate threshold-calibration role\nFixed 10% / 20% expected review budgets\nTruth-independent hash handling of score ties", "#fff2d8"),
      ("riskheld",1120,284,375,112,"Held-out risk scores: six evaluation groups\nIndependent from risk fit and threshold calibration\nRepeat across the five outer folds", "#fff2d8"),
      ("finalrisk",550,455,780,80,"Frozen target risk model: fit on source base-OOF rows; operating thresholds from honest outer risk scores\nSource-to-target calibration transfer remains a limitation; target deployment labels never flow upstream", "#fff2d8"),
      ("history",30,596,280,122,"Target initial B calendar days\n[T−B, T−1], B=30 / 90 / 180\nScale, descriptors, local training,\nvalidation and bias\nNo observations before budget left boundary", "#e7f5e8"),
      ("frozen",380,596,300,122,"Final source fit: 2016–2021 only\nUniform / similarity source weights\nScale, weights, alpha, lambda and bias freeze at T\nB30 main-pool fixed weight-shuffle ablation", "#e7f5e8"),
      ("deploy",750,596,320,122,"60 deployment origins, h=1 / h=3\nUpdate only legally arrived lag inputs\nRisk: initial distance + recent missingness/change\nNo retraining or threshold recalibration", "#e7f5e8"),
      ("outputs",1140,596,350,122,"Saved point predictions + pre-forecast risk scores\nFixed review flags; prediction remains unchanged\nRaw predictions primary; uniform nonnegative sensitivity\nh=3 predicts origin+3 daily volume", "#e7f5e8"),
      ("evaluate",210,819,1120,95,"Evaluation only: ten fixed development SiteIDs × five USED 2022–2023 windows × all budgets/horizons/pools\nMatched-date MAE/RMSE/negative transfer and history comparisons; risk within-site/window and between-condition statistics\n5000 paired synchronous calendar-block + SiteID resamples; four primary contrasts; no independent physical-facility or real-time certification", "#f0edf8"),
    ]
    edges=[("source","past"),("past","roles"),("roles","inner"),
           ("inner","base"),("base","risktrain"),("risktrain","riskcal"),("riskcal","riskheld"),
           ("riskheld","finalrisk"),("history","frozen"),("frozen","deploy"),("deploy","outputs"),
           ("finalrisk","outputs"),("outputs","evaluate")]
    mxfile=ET.Element("mxfile",{"host":"app.diagrams.net","type":"device"})
    diagram=ET.SubElement(mxfile,"diagram",{"id":"stage3g-executed","name":"Executed Stage3G"})
    graph=ET.SubElement(diagram,"mxGraphModel",{"dx":"1550","dy":"960","grid":"1","gridSize":"10","page":"1","pageWidth":"1550","pageHeight":"960"})
    root=ET.SubElement(graph,"root");ET.SubElement(root,"mxCell",{"id":"0"});ET.SubElement(root,"mxCell",{"id":"1","parent":"0"})
    by_id={node[0]:node for node in nodes}
    for key,x,y,w,h,text,color in nodes:
        value=text.replace("\n","<br>")
        cell=ET.SubElement(root,"mxCell",{"id":key,"value":value,"vertex":"1","parent":"1",
            "style":f"rounded=1;whiteSpace=wrap;html=1;fillColor={color};strokeColor=#54616b;fontFamily=Arial;fontSize={20 if key=='title' else 14};align=center;verticalAlign=middle;"})
        ET.SubElement(cell,"mxGeometry",{"x":str(x),"y":str(y),"width":str(w),"height":str(h),"as":"geometry"})
    for i,(source,target) in enumerate(edges):
        cell=ET.SubElement(root,"mxCell",{"id":f"edge{i}","edge":"1","parent":"1","source":source,"target":target,
            "style":"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;endFill=1;strokeColor=#54616b;"})
        ET.SubElement(cell,"mxGeometry",{"relative":"1","as":"geometry"})
    ET.ElementTree(mxfile).write(output/"editableflow.drawio",encoding="utf-8",xml_declaration=True)
    fig,ax=plt.subplots(figsize=(16.6,10.3));ax.set_xlim(0,1550);ax.set_ylim(960,0);ax.axis("off")
    for key,x,y,w,h,text,color in nodes:
        box=FancyBboxPatch((x,y),w,h,boxstyle="round,pad=0,rounding_size=8",linewidth=.8,edgecolor="#54616b",facecolor=color,zorder=3)
        ax.add_patch(box);ax.text(x+w/2,y+h/2,text,ha="center",va="center",fontsize=12 if key=="title" else 8.2,zorder=4)
    for source,target in edges:
        _,sx,sy,sw,sh,_,_=by_id[source];_,tx,ty,tw,th,_,_=by_id[target]
        if abs(sy-ty)<15:
            start=(sx+sw,sy+sh/2);end=(tx,ty+th/2);rad=0
        elif source=="inner":
            start=(sx+sw/2,sy+sh);end=(tx+tw/2,ty);rad=.15
        elif source=="riskheld":
            start=(sx+sw/2,sy+sh);end=(tx+tw-40,ty);rad=0
        else:
            start=(sx+sw/2,sy+sh);end=(tx+tw/2,ty);rad=0
        arrow=FancyArrowPatch(start,end,arrowstyle="-|>",mutation_scale=11,linewidth=.9,color="#54616b",connectionstyle=f"arc3,rad={rad}",zorder=2)
        ax.add_patch(arrow)
    fig.tight_layout(pad=.5);save(fig,output,"editableflow")
    (output/"FLOW_EVIDENCE.json").write_text(json.dumps({"evaluation_receipt":str(receipt.relative_to(ROOT)),"evaluation_receipt_sha256":sha256(receipt),"status":status['status'],"editable_nodes":len(nodes),"editable_arrows":len(edges),"not_a_new_model_or_app":True,"physical_mapping_verified":False,"verified_real_time":False},indent=2)+"\n")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results",default=f"reports/{VERSION}/results")
    parser.add_argument("--output",default=f"figures/{VERSION}")
    parser.add_argument("--main-model",default="similarity_residual_ridge_bias_selected")
    parser.add_argument("--uniform-model",default="uniform_residual_ridge_bias_selected")
    parser.add_argument("--local-model",default="local_residual_ridge_selected")
    args=parser.parse_args();results=ROOT/args.results;out=ROOT/args.output
    out.mkdir(parents=True,exist_ok=True)
    tables={name:read(results/f"{name}.csv") for name in ["metrics_by_station","paired_comparisons_by_station","cross_budget_by_station","cross_budget_intervals","parameter_choices","summary","risk_retention_summary","reliability_summary","reliability_by_station","high_volume_metrics_by_station"]}
    models=[args.main_model,args.uniform_model,args.local_model]
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"pdf.fonttype":42,"ps.fonttype":42,"svg.fonttype":"none","axes.unicode_minus":True})
    site_skills(tables["metrics_by_station"],tables["paired_comparisons_by_station"],out,models)
    cross_budget(tables["cross_budget_by_station"],tables["cross_budget_intervals"],out,args.main_model)
    weight_concentration(tables["parameter_choices"],tables["summary"],out,args.main_model)
    reliability(tables["risk_retention_summary"],tables["reliability_summary"],tables["reliability_by_station"],out)
    high_volume(tables["high_volume_metrics_by_station"],out,models)
    questions={"site_skills_and_negative_transfer":"Does the main weighted candidate improve matched Persistence and uniform/local comparisons across all target SiteIDs?",
      "cross_budget_comparison":"How do shared short-history predictions compare with stronger local models using longer permitted initial history?",
      "source_weights_and_composition":"Are weights concentrated, and do apparent improvements depend on one of three fixed source compositions?",
      "reliability_retention_and_review_cost":"Do source-trained pre-prediction risk scores identify large errors, and at what fixed-threshold review burden?",
      "high_volume_conditions":"How do all matched methods behave on high-volume labels defined using legal initial-history Q90?"}
    source_index={f"{name}.csv":{"sha256":sha256(results/f"{name}.csv"),"rows":len(frame)} for name,frame in tables.items()}
    captions={"stage":VERSION,"script_sha256":sha256(Path(__file__)),"source_tables":source_index,"figures":questions,"display_rules":{"primary_pool":POOLS[0],"budget":30,"horizons":[1,3],"all_sites":SITES,"source_pools":POOLS,"constraint":"raw","models":models},"limitations":NOTE}
    (out/"FIGURE_SOURCES.json").write_text(json.dumps(captions,ensure_ascii=False,indent=2)+"\n")
    captions_text="\n\n".join(f"**{name}.** {caption} All ten fixed development SiteIDs are retained; the main pool is order 20261012 and B30 unless shown otherwise. {NOTE}" for name,caption in questions.items())
    (out/"CAPTIONS_EN.md").write_text(captions_text+"\n")
    check={"status":"PASSED","figures":export_check(out),"source_tables":source_index,"manual_visual_inspection":"PENDING","no_synthetic_scientific_data":True}
    executed_flow(results,out)
    (out/"FIGURE_CHECK.json").write_text(json.dumps(check,indent=2)+"\n")
    print(json.dumps({"status":"PASSED","figure_families":5,"output":str(out),"manual_inspection":"PENDING"}))


if __name__=="__main__":main()
