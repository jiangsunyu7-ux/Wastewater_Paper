"""Independently recompute Stage3G point/risk metrics from verified disk outputs.

This command reads all frozen tasks, verifies their disk fingerprints/checksums,
and never calls a model fitting or parameter-selection function. Completion is
based on disk evidence rather than function-return success counts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from wastewater.common import sha256
from wastewater.stage3g_evaluation import MODELS, SHUFFLE, summarize


def verify_run(root,config_path,run):
    from wastewater.stage3g_experiment import load_config,expected_tasks,task_key,validate_target
    from wastewater.stage3g_source import digest
    cfg,signature=load_config(config_path)
    state=json.loads((run/'RUN_STATUS.json').read_text())
    tasks=expected_tasks(cfg,'full')
    if state.get('status')!='COMPLETED' or state.get('signature')!=signature:
        raise ValueError('Frozen full run is not completed or signature differs')
    if state.get('expected')!=len(tasks) or state.get('disk_verified_completed')!=len(tasks):
        raise ValueError('A partial disk task set cannot be declared complete')
    registry=json.loads((run/'EXPECTED_TASKS.json').read_text())
    if registry.get('signature')!=signature or registry.get('tasks')!=[task_key(t) for t in tasks]:
        raise ValueError('Expected task registry/fingerprint differs')
    rows=[];members={}
    for task in tasks:
        folder=run/'jobs'/task_key(task);expected_rows=60*3*8+(180 if task[2]==30 else 0)
        fingerprint=digest(dict(signature=signature,task=task))
        if not validate_target(folder,fingerprint,expected_rows):
            raise ValueError('Incomplete/damaged/stale task: '+task_key(task))
        members[str((folder/'status.json').relative_to(root))]=sha256(folder/'status.json')
        job=json.loads((folder/'status.json').read_text())
        for name,expected_sha in job['outputs_sha256'].items():
            actual=sha256(folder/name)
            if actual!=expected_sha:raise ValueError('Job output SHA mismatch: '+task_key(task)+'/'+name)
            members[str((folder/name).relative_to(root))]=actual
        rows.append(pd.read_csv(folder/'predictions.csv',dtype={'site_id':str,'pool_id':str},low_memory=False))
    frame=pd.concat(rows,ignore_index=True)
    expected_primary=len(tasks)*60*3*len(MODELS)
    expected_shuffle=sum(t[2]==30 for t in tasks)*180
    point=frame[frame.model.isin(MODELS)].copy();shuffle=frame[frame.model.eq(SHUFFLE)].copy()
    if len(frame)!=expected_primary+expected_shuffle or len(point)!=expected_primary or len(shuffle)!=expected_shuffle:
        raise ValueError('Wrong point/ablation row count or unregistered model')
    integrity=dict(status='VERIFIED',all_expected_tasks_verified=True,expected_tasks=len(tasks),verified_tasks=len(tasks),
        expected_primary_prediction_rows=expected_primary,expected_shuffle_prediction_rows=expected_shuffle,
        config_sha256=sha256(root/config_path),run_status_sha256=sha256(run/'RUN_STATUS.json'),run_signature=signature,
        job_members_sha256=members,aggregate_origin='read verified original task CSVs; no re-fitting or old-stage regeneration')
    return cfg,point,shuffle,integrity


def verify_risk_receipt(root,directory,config):
    """Check actual target/source risk files and all recorded upstream hashes."""
    receipt=directory/'RUN_STATUS.json'
    state=json.loads(receipt.read_text())
    if state.get('status')!='COMPLETED':raise ValueError('Risk disk receipt is incomplete: '+str(receipt))
    fingerprint=state.get('fingerprint',{})
    if fingerprint.get('config_sha256')!=sha256(config):raise ValueError('Risk config SHA differs')
    for section in ['input_sha256','code_sha256']:
        if not fingerprint.get(section):raise ValueError('Risk receipt lacks '+section)
        for filename,expected in fingerprint[section].items():
            file=root/filename
            if not file.is_file() or sha256(file)!=expected:raise ValueError('Risk upstream/code SHA differs: '+filename)
    for filename,expected in state.get('members',{}).items():
        path=directory/filename
        if not path.is_file() or sha256(path)!=expected:raise ValueError('Risk member SHA differs: '+str(path))
    for filename,expected in state.get('row_counts',{}).items():
        if len(pd.read_csv(directory/filename))!=expected:raise ValueError('Risk row-count differs: '+filename)
    return dict(receipt_sha256=sha256(receipt),fingerprint=fingerprint,members=state['members'],row_counts=state['row_counts'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='configs/stage3g_transfer_reliability_v1/full.json')
    parser.add_argument('--run',help='Defaults to config output')
    parser.add_argument('--output',help='Defaults to config report_output')
    parser.add_argument('--risk',help='Defaults to RUN/reliability/target_risk_predictions.csv.gz')
    parser.add_argument('--point-only',action='store_true',help='Point results can be examined, but final full-stage completion remains PARTIAL')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    resolve=lambda p:Path(p) if Path(p).is_absolute() else root/p
    cfg0=json.loads(resolve(args.config).read_text());run=resolve(args.run or cfg0['output'])
    config_path=str(resolve(args.config).resolve().relative_to(root.resolve()))
    cfg,point,shuffle,integrity=verify_run(root,config_path,run)
    risk_path=resolve(args.risk) if args.risk else run/'reliability'/'target_risk_predictions.csv.gz'
    risk=None
    if not args.point_only:
        if not risk_path.is_file():raise FileNotFoundError('Full point+risk evaluation needs '+str(risk_path))
        integrity['source_risk_evidence']=verify_risk_receipt(root,resolve(cfg['source_output'])/'reliability',resolve(args.config))
        integrity['target_risk_evidence']=verify_risk_receipt(root,risk_path.parent,resolve(args.config))
        risk=pd.read_csv(risk_path,dtype={'site_id':str,'pool_id':str},low_memory=False)
        integrity['risk_predictions_sha256']=sha256(risk_path)
    else:
        integrity['all_expected_tasks_verified']=False
        integrity['reliability_status']='NOT_EVALUATED_POINT_ONLY_MODE'
    out=resolve(args.output or cfg['report_output'])
    out.mkdir(parents=True,exist_ok=True)
    from wastewater.stage3e_runtime import atomic_json
    atomic_json(out/'INPUT_EVIDENCE.json',integrity)
    from wastewater.stage3g_source import atomic_csv
    weight_paths=sorted((run/'jobs').glob('*/source_weights.csv'))
    weights=pd.concat([pd.read_csv(path,dtype={'site_id':str,'source_site_id':str}) for path in weight_paths],ignore_index=True)
    weights['seed']=weights['seed'].fillna(0).astype(int)
    keys=['site_id','episode','budget','horizon','pool_id','model','seed']
    totals=weights.groupby(keys).weight.sum()
    import numpy as np
    if not np.allclose(totals,1.,atol=1e-12,rtol=1e-12):raise ValueError('Saved source weights do not sum to one')
    atomic_csv(out/'source_weights_all.csv.gz',weights)
    status=summarize(point,cfg,out,integrity,shuffle=shuffle,risk=risk)
    print(json.dumps(status,ensure_ascii=False,indent=2))
    return 0 if status['status']=='COMPLETED' else 3


if __name__=='__main__':raise SystemExit(main())
