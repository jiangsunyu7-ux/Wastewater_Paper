"""Package Stage3F evidence requests and verify them; no science is executed."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'stage3f_evidence_gate_v1'
LIMIT = 24*1024**2

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path, value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def checked(command, cwd, logs, label):
    result=subprocess.run(command,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    log=logs/(label+'.log');log.write_bytes(result.stdout)
    if result.returncode:raise RuntimeError(f'{label} failed with exit{result.returncode}; see {log}')
    return dict(command=command,exit_code=result.returncode,log=log.name,sha256=sha(log),
        work='Metadata provenance/request-scope only; no performance or physical authentication')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='delivery/20261013_stage3f')
    args=parser.parse_args();output=(ROOT/args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    name='Wessex_Stage3F_Evidence_and_Requests_20261013.zip';archive=output/name
    if archive.exists():raise FileExistsError('Never overwrite a previously built F archive')
    report=ROOT/'reports'/VERSION
    status=json.loads((report/'RUN_STATUS.json').read_text())
    assert status['status']=='WAITING_FOR_EXTERNAL_EVIDENCE' and status['local_preparation_completed']
    payload={}
    # Original E receipts are supplied in the separate exact-byte supplement,
    # not repeated as new scientific output in this request package.
    for p in sorted(report.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts:continue
        relative=p.relative_to(report)
        if relative.parts[:2] in [('delivery_chain','original_stage3e_receipts'),('delivery_chain','original_dependencies')]:continue
        payload[p.relative_to(ROOT).as_posix()]=p
    for name2 in ['AGENTS.md','STATUS.md','RESEARCH_PLAN.md','EXPERIMENT_PROTOCOL.md','WORKFLOW.md',
        'STAGE3F_PROTOCOL.md',f'configs/{VERSION}/full.json','scripts/package_stage3f.py','scripts/finalize_stage3f.py',
        'validation/stage3f_finalize_compile_attempt01_failed.py.txt']:
        payload[name2]=ROOT/name2
    official='data/provenance/stage3b_20261011_v1/official_provider_catalog_response.bin'
    payload[official]=ROOT/official
    hashes={name2:sha(p) for name2,p in payload.items()}
    manifest=dict(stage='Stage3F',version=VERSION,status=status['status'],
        local_preparation_completed=True,new_prediction_performance_computed=False,
        scientific_innovation_established=False,members_sha256=hashes)
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for member,p in sorted(payload.items()):z.write(p,member)
        z.writestr('PACKAGE_MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        z.writestr('SHA256SUMS',''.join(h+'  '+n+'\n' for n,h in sorted(hashes.items())))
    assert archive.stat().st_size<LIMIT
    logs=output/'clean_metadata_checks';logs.mkdir(exist_ok=True);commands=[]
    with tempfile.TemporaryDirectory(prefix='wessex_stage3f_clean_',dir='/tmp') as temp:
        clean=Path(temp)
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None and len(z.namelist())==len(set(z.namelist()))
            assert set(z.namelist())==set(hashes)|{'PACKAGE_MANIFEST.json','SHA256SUMS'}
            for info in z.infolist():
                p=clean/info.filename
                assert p.resolve().is_relative_to(clean.resolve()),'Archive path escape'
                blob=z.read(info.filename)
                if info.filename in hashes:assert hashlib.sha256(blob).hexdigest()==hashes[info.filename]
                p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob)
        for script,label in [('requests/verify_request_scope.py','request_scope'),('literature_delta/verify_literature_delta.py','literature_provenance')]:
            commands.append(checked([sys.executable,str(clean/f'reports/{VERSION}'/script)],clean,logs,label))
        supplement=output/'Wessex_Stage3E_Delivery_Supplement_20261013.zip'
        commands.append(checked([sys.executable,str(clean/f'reports/{VERSION}/delivery_chain/verify_supplement.py'),str(supplement)],clean,logs,'original_delivery_supplement'))
    for member,h in hashes.items():assert sha(ROOT/member)==h,'Payload changed during packaging: '+member
    package=dict(file=name,bytes=archive.stat().st_size,MiB=archive.stat().st_size/1024**2,sha256=sha(archive),
        actual_status=status['status'],members=hashes)
    save(output/'STAGE3F_PACKAGE_CHECKS.json',dict(status='PASSED_ARCHIVE_AND_METADATA_ONLY',
        generated_utc=datetime.now(timezone.utc).isoformat(),package=package,CRC_and_member_SHA=True,
        clean_directory_commands=commands,no_new_predictive_models=True,
        missing_external_evidence_not_marked_passed=True,verified_real_time=False,physical_mapping_verified=False))
    for source in ['NEXT_ACTION.md','RUN_STATUS.json','CODE_VERSION.json','REPRODUCE.md']:
        (output/source).write_bytes((report/source).read_bytes())
    supplement_checks=json.loads((output/'STAGE3E_SUPPLEMENT_PACKAGE_CHECK.json').read_text())
    save(output/'ARTIFACT_INDEX.json',dict(stage='Stage3F',version=VERSION,
        generated_utc=datetime.now(timezone.utc).isoformat(),status=status['status'],local_preparation_completed=True,
        source_code_version=json.loads((report/'CODE_VERSION.json').read_text()),packages=[package],
        stage3e_original_delivery_supplement=dict(file=supplement.name,bytes=supplement.stat().st_size,sha256=sha(supplement),
            work='Original E receipts/C2 dependency list only; old scientific output not regenerated'),
        original_package_checks_file='STAGE3E_SUPPLEMENT_PACKAGE_CHECK.json',
        fixture_checks_not_used_as_delivery_checks=True,protected_or_final_performance_computed=False))
    (output/'README.md').write_text(
        '# Stage3F — evidence gates and requests\n\n'
        '**WAITING_FOR_EXTERNAL_EVIDENCE**. Local preparation finished; no new model or prediction performance.\n\n'
        '[Current single action](NEXT_ACTION.md) · [Reproduction](REPRODUCE.md) · [Hashes/index](ARTIFACT_INDEX.json)\n\n'
        f'- [{name}]({name}?raw=true) — evidence gates, unsent short email, templates, mentor note and limited literature delta.\n'
        f'- [{supplement.name}]({supplement.name}?raw=true) — original E ARTIFACT_INDEX/full PACKAGE_CHECKS and C2 immutable dependency list.\n\n'
        'The second ZIP supplies missing receipts; it is not a new Stage3E experiment. Original C2 Part01/02 are not regenerated or embedded; '
        'their exact immutable URLs, bytes and SHA are in the supplement IMMUTABLE_DOWNLOADS.csv.\n'
        'Archive/scope checks do not certify physical facility independence, real-time deployment, stable transfer benefit or innovation.\n')
    lines=[]
    for p in sorted(output.rglob('*')):
        if p.is_file() and 'failed_supplement_attempt01' not in p.parts and p.name!='SHA256SUMS':
            lines.append(sha(p)+'  '+p.relative_to(output).as_posix()+'\n')
    (output/'SHA256SUMS').write_text(''.join(lines))
    print(json.dumps(dict(status='WAITING_FOR_EXTERNAL_EVIDENCE',local_preparation_completed=True,
        package={k:v for k,v in package.items() if k!='members'},clean_metadata_checks_passed=True),indent=2))

if __name__=='__main__':main()
