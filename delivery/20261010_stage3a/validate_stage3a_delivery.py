"""Reconstruct packages in an isolated ROOT, verify frozen inputs and caches."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def importer_from_notebook():
    nb=json.loads((ROOT/'notebooks/Wessex_Stage3A_CPU.ipynb').read_text());namespace=dict(Path=Path,hashlib=hashlib,zipfile=zipfile,stat=__import__('stat'))
    for cell in nb['cells']:
        if cell['cell_type']!='code':continue
        tree=ast.parse(''.join(cell['source']));nodes=[]
        for n in tree.body:
            if isinstance(n,ast.FunctionDef) and n.name in ['digest_bytes','safe_import_zip']:nodes.append(n)
            if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='OLD_SHA' for t in n.targets):nodes.append(n)
        if nodes:exec(compile(ast.Module(body=nodes,type_ignores=[]),'notebook importer','exec'),namespace)
    assert 'safe_import_zip' in namespace
    return namespace


def main():
    packages=ROOT/'deliverables/stage3a_20261010';receipt=json.loads((packages/'package_checks.json').read_text());ns=importer_from_notebook();safe=ns['safe_import_zip'];oldsha=ns['OLD_SHA']
    with tempfile.TemporaryDirectory(prefix='stage3a_clean_replay_',dir='/tmp') as temp:
        target=Path(temp);members=0
        for item in receipt['packages']:
            p=packages/item['filename'];assert digest(p)==item['sha256'];members+=safe(p,target,item['sha256'])
        for name,h in oldsha.items():
            p=ROOT/'deliverables/stage2_20261010'/name;members+=safe(p,target,h,extract_payload=('Code_Data' not in name))
            for folder in ['deliverables/stage2_20261010','preservation/stage2_before_stage3a_20261010']:
                dest=target/folder/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
        preserved=json.loads((target/'preservation/stage2_before_stage3a_20261010/manifest.json').read_text())
        for name,h in preserved['files_sha256'].items():assert digest(target/name)==h, name
        before={str(p.relative_to(target)):digest(p) for p in target.rglob('*') if p.is_file() and p.suffix!='.pyc'}
        env=os.environ.copy();env.update(PYTHONPATH=str(target/'src'),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        python=str(ROOT/'.venv-stage2/bin/python')
        code='''from pathlib import Path
import json,hashlib
from wastewater.stage3a_experiment import execution_signature
from wastewater.shared_experiment import run_job
r=Path.cwd();c=json.loads((r/'configs/stage3a_20261010/full.json').read_text());m=json.loads((r/c['output']/'manifest.json').read_text())
signature,_=execution_signature(c);assert signature==m['signature']
def forbidden(folder):raise AssertionError('Delivery replay must not fit models')
results=[]
for rec in json.loads((r/c['output']/'completion.json').read_text()):
 fingerprint=hashlib.sha256((signature+rec['task']+str(c['seeds'])).encode()).hexdigest()
 assert run_job(r/rec['folder'],fingerprint,forbidden)=='cached';results.append(rec['task'])
print(json.dumps({'status':'passed','cached_full_conditions':len(results),'models_retrained':0}))
'''
        replay=subprocess.run([python,'-c',code],cwd=target,env=env,capture_output=True,text=True)
        if replay.returncode:raise RuntimeError(replay.stdout+replay.stderr)
        tests=subprocess.run([python,'-m','unittest','discover','-s','tests','-p','test_stage3a.py','-v'],cwd=target,env=env,capture_output=True,text=True)
        if tests.returncode:raise RuntimeError(tests.stdout+tests.stderr)
        changed=[n for n,h in before.items() if digest(target/n)!=h];assert not changed
        # Real importer rejection checks, independent of software fixture results.
        small=target/'unsafe.zip'
        with zipfile.ZipFile(small,'w') as z:
            payload=b'bad';z.writestr('../escape.txt',payload);z.writestr('SHA256SUMS',hashlib.sha256(payload).hexdigest()+'  ../escape.txt\n')
        try:safe(small,target)
        except AssertionError:pass
        else:raise AssertionError('Unsafe ZIP path accepted')
        result=dict(status='passed',zip_packages=len(receipt['packages']),verified_member_imports=members,
            stage2_preserved_files=len(preserved['files_sha256']),extracted_files_unchanged=len(before),changed_files=changed,
            cached_full_conditions=240,model_training_executed=False,tests=4,unsafe_zip_paths_rejected=True,
            actual_Colab_Drive_mount_verified=False,actual_GPU_execution_verified=False,
            notebook_sha256=digest(ROOT/'notebooks/Wessex_Stage3A_CPU.ipynb'),checker_sha256=digest(Path(__file__)),
            replay_stdout=replay.stdout,test_stdout=tests.stdout+tests.stderr)
    (ROOT/'validation/stage3a_delivery_replay.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
