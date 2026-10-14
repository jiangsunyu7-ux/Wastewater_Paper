"""Source-only risk fit/freeze followed by frozen target scoring; no point refit."""
from __future__ import annotations
import argparse
import gzip
import io
import json
from pathlib import Path
import time
import traceback

import pandas as pd

from wastewater.common import sha256, utc_now
from wastewater.stage3e_runtime import atomic_bytes, atomic_json, append_event
from wastewater.stage3g_reliability import fit_source_crossfit, score_target_risk, read_bundle
from wastewater.stage3g_experiment import load_config, group_mapping, expected_tasks, task_key, validate_target, MODELS
from wastewater.stage3g_source import validate_cache, digest


ROOT = Path(__file__).resolve().parents[1]


def dataframe_bytes(frame):
    buffer=io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as handle:
        handle.write(frame.to_csv(index=False, lineterminator='\n').encode())
    return buffer.getvalue()


def fingerprint(config, inputs):
    code=[Path(__file__).resolve(), ROOT/'src/wastewater/stage3g_reliability.py',
          ROOT/'src/wastewater/stage3e_runtime.py', ROOT/'src/wastewater/common.py']
    return dict(config_sha256=sha256(config),
        input_sha256={str(path.relative_to(ROOT)):sha256(path) for path in inputs},
        code_sha256={str(path.relative_to(ROOT)):sha256(path) for path in code})


def verified_cached(directory, signature):
    receipt=directory/'RUN_STATUS.json'
    if not receipt.exists():return False
    status=json.loads(receipt.read_text())
    if status.get('fingerprint') != signature:
        raise ValueError('Reliability cache fingerprint mismatch; use a new output version')
    if status.get('status')!='COMPLETED':return False
    for member,expected in status['members'].items():
        path=directory/member
        if not path.is_file() or sha256(path)!=expected:return False
    for name,expected in status['row_counts'].items():
        if len(pd.read_csv(directory/name))!=expected:return False
    return True


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['source','target'])
    parser.add_argument('--config',default='configs/stage3g_transfer_reliability_v1/full.json')
    parser.add_argument('--mode',choices=['smoke','full'],default='full')
    parser.add_argument('--output',default=None)
    args=parser.parse_args()
    config=ROOT/args.config;cfg,science_signature=load_config(config)
    freeze=ROOT/cfg['frozen_manifest']
    if not freeze.is_file():raise ValueError('Stage3G protocol/config/code freeze must exist before risk fitting')
    source_root=ROOT/cfg['source_output']; bundlepath=source_root/'reliability'/'final_risk_bundle.json'
    if args.action=='source':
        data_inputs=[source_root/p['pool_id']/'strict_reliability_base_predictions.csv.gz' for p in cfg['pools']]
        groups=group_mapping(cfg)
        required={'selection.json','source_cv_candidates.csv.gz','source_cv_folds.json',
            'strict_reliability_base_predictions.csv.gz','strict_reliability_roles.json',
            'nested_source_cv_candidates.csv.gz','source_descriptor_windows.json','source_training_diagnostics.json'}
        for pool in cfg['pools']:
            source_fingerprint=digest(dict(signature=science_signature,pool=pool,
                groups={site:groups[site] for site in pool['site_ids']}))
            if not validate_cache(source_root/pool['pool_id'],source_fingerprint,required):
                raise ValueError('Source prediction cache is not completed and disk-verified: '+pool['pool_id'])
        inputs=data_inputs+[source_root/p['pool_id']/'status.json' for p in cfg['pools']]
        directory=ROOT/args.output if args.output else source_root/'reliability'
    else:
        source_inputs=[source_root/p['pool_id']/'strict_reliability_base_predictions.csv.gz' for p in cfg['pools']]
        source_inputs += [source_root/p['pool_id']/'status.json' for p in cfg['pools']]
        source_signature=fingerprint(config,source_inputs+[freeze])
        if not verified_cached(source_root/'reliability',source_signature):
            raise ValueError('Source risk models/thresholds are not completely disk-verified and frozen')
        run_root=ROOT/cfg['output']
        if args.mode=='smoke':run_root=run_root.parent/'smoke'
        data_inputs=sorted((run_root/'jobs').glob('*/risk_inputs.csv'))
        if not data_inputs:raise ValueError('No point-stage risk input files; no empty successful output allowed')
        tasks=expected_tasks(cfg,args.mode)
        if len(data_inputs)!=len(tasks):raise ValueError(f'Expected {len(tasks)} verified point risk inputs, found {len(data_inputs)}')
        if set(path.parent.name for path in data_inputs)!=set(task_key(task) for task in tasks):
            raise ValueError('Risk point-task set differs from the predeclared matrix')
        for task in tasks:
            expected_rows=60*len(cfg['pools'])*len(MODELS)+(180 if task[2]==30 else 0)
            point_fingerprint=digest(dict(signature=science_signature,task=task))
            if not validate_target(run_root/'jobs'/task_key(task),point_fingerprint,expected_rows):
                raise ValueError('Point cache is not completed and disk-verified: '+task_key(task))
        inputs=data_inputs+[path.parent/'status.json' for path in data_inputs]
        inputs += [bundlepath,source_root/'reliability'/'RUN_STATUS.json']
        directory=ROOT/args.output if args.output else run_root/'reliability'
    for path in inputs:
        if not path.is_file():raise FileNotFoundError(path)
    signature=fingerprint(config,inputs+[freeze]);directory.mkdir(parents=True,exist_ok=True)
    if verified_cached(directory,signature):
        print(json.dumps(dict(status='CACHED_VERIFIED',action=args.action,output=str(directory)),ensure_ascii=False),flush=True);return
    started=time.monotonic()
    previous=directory/'RUN_STATUS.json'
    if previous.is_file():
        old=json.loads(previous.read_text())
        if old.get('fingerprint')!=signature:raise ValueError('Refusing mismatched existing risk run')
        append_event(directory/'failure_events.jsonl',dict(event='recover_noncompleted_or_invalid_cache',prior_status=old.get('status')))
    atomic_json(previous,dict(status='RUNNING',started=utc_now(),action=args.action,fingerprint=signature))
    try:
        if args.action=='source':
            rows=pd.concat([pd.read_csv(path,dtype={'site_id':str,'group_id':str}) for path in data_inputs],ignore_index=True)
            bundle,scores,thresholds,models=fit_source_crossfit(rows)
            files={'final_risk_bundle.json':(json.dumps(bundle,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode(),
                   'source_risk_crossfit_scores.csv.gz':dataframe_bytes(scores),
                   'source_operating_thresholds.csv.gz':dataframe_bytes(thresholds),
                   'risk_model_diagnostics.json':(json.dumps(models,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()}
            counts={'source_risk_crossfit_scores.csv.gz':len(scores),'source_operating_thresholds.csv.gz':len(thresholds)}
            detail=dict(source_base_rows=len(rows),final_models=len(bundle),outer_models=len(models)-len(bundle),
                thresholds_from_outer_OOS_scores=True,target_rows_used=0)
        else:
            rows=pd.concat([pd.read_csv(path,dtype={'site_id':str,'group_id':str}) for path in data_inputs],ignore_index=True)
            bundle=read_bundle(bundlepath);scores=score_target_risk(bundle,rows)
            files={'target_risk_predictions.csv.gz':dataframe_bytes(scores)}
            counts={'target_risk_predictions.csv.gz':len(scores)}
            detail=dict(target_point_rows=len(rows),risk_methods=4,point_predictions_modified=False,point_refits=0)
        members={name:atomic_bytes(directory/name,content) for name,content in files.items()}
        for name,count in counts.items():
            if len(pd.read_csv(directory/name))!=count:raise IOError(f'Risk row count readback differs: {name}')
        status=dict(status='COMPLETED',action=args.action,completed=utc_now(),fingerprint=signature,members=members,
                    row_counts=counts,elapsed_seconds=time.monotonic()-started,**detail)
        atomic_json(previous,status)
        if not verified_cached(directory,signature):raise IOError('Risk final receipt validation failed')
        print(json.dumps(status,ensure_ascii=False,indent=2),flush=True)
    except Exception as error:
        append_event(directory/'failure_events.jsonl',dict(event='risk_stage_failed',error=repr(error),traceback=traceback.format_exc()))
        atomic_json(previous,dict(status='FAILED',fingerprint=signature,error=repr(error),failed=utc_now()))
        raise


if __name__=='__main__':main()
