#!/usr/bin/env python3
"""Offline Stage3G notebook syntax/import guards, using labelled byte fixtures.

This does not mount Drive, log into Colab, install dependencies, execute a model,
or claim a fabricated fixture is a scientific result.
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOK=ROOT/'notebooks/Stage3GCPU.ipynb'


def make_fixture(directory, payload=None):
    directory.mkdir(parents=True,exist_ok=True)
    payload=payload or {'fixtures/NOT_SCIENTIFIC_DATA.txt':b'labelled synthetic importer byte fixture\n'}
    archive=directory/'Wessex_Stage3G_Code_and_Reproduce_fixture.zip'
    hashes={name:hashlib.sha256(blob).hexdigest() for name,blob in payload.items()}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,blob in payload.items():z.writestr(name,blob)
        z.writestr('PACKAGE_MANIFEST.json',json.dumps({'stage':'synthetic software fixture','members_sha256':hashes}))
        z.writestr('SHA256SUMS',''.join(h+'  '+n+'\n' for n,h in hashes.items()))
    (directory/'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
    return archive


def main():
    nb=json.loads(NOTEBOOK.read_text())
    codes=[''.join(c['source']) for c in nb['cells'] if c['cell_type']=='code']
    for index,code in enumerate(codes):compile(code,f'{NOTEBOOK.name}:code{index}','exec')
    importer=[c for c in codes if 'def safe_member(name)' in c]
    if len(importer)!=1:raise ValueError('A single importer code cell is required')
    checks=[]
    with tempfile.TemporaryDirectory(prefix='stage3g_notebook_fixtures_',dir='/tmp') as temporary:
        base=Path(temporary)
        def execute(packages,project):
            project.mkdir(parents=True,exist_ok=True)
            globals_={'Path':Path,'hashlib':hashlib,'json':json,'os':os,'zipfile':zipfile,
                'tempfile':tempfile,'shutil':shutil,'PACKAGE_DIR':packages,'PROJECT_ROOT':project}
            with contextlib.redirect_stdout(io.StringIO()):exec(importer[0],globals_)
        packages=base/'valid/packages';project=base/'valid/project';make_fixture(packages)
        execute(packages,project);execute(packages,project)
        assert (project/'fixtures/NOT_SCIENTIFIC_DATA.txt').read_bytes()==b'labelled synthetic importer byte fixture\n'
        checks.append({'case':'valid_fixture_and_identical_repeat','status':'PASSED'})
        (project/'fixtures/NOT_SCIENTIFIC_DATA.txt').write_text('different pre-existing fixture\n')
        try:execute(packages,project)
        except FileExistsError:checks.append({'case':'refuse_differing_existing_payload','status':'PASSED'})
        else:raise AssertionError('Different payload was overwritten')
        packages=base/'outer/packages';project=base/'outer/project';make_fixture(packages)
        (packages/'SHA256SUMS').write_text('0'*64+'  Wessex_Stage3G_Code_and_Reproduce_fixture.zip\n')
        try:execute(packages,project)
        except ValueError:checks.append({'case':'outer_checksum_corruption','status':'PASSED'})
        else:raise AssertionError('Bad outer SHA accepted')
        packages=base/'traversal/packages';project=base/'traversal/project';make_fixture(packages,{'../escape.txt':b'forbidden fixture'})
        try:execute(packages,project)
        except ValueError:checks.append({'case':'reject_archive_path_traversal','status':'PASSED'})
        else:raise AssertionError('Path traversal accepted')
        packages=base/'member/packages';project=base/'member/project';archive=make_fixture(packages)
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('fixtures/NOT_SCIENTIFIC_DATA.txt',b'corrupt synthetic member')
            z.writestr('PACKAGE_MANIFEST.json',json.dumps({'members_sha256':{'fixtures/NOT_SCIENTIFIC_DATA.txt':'0'*64}}))
            z.writestr('SHA256SUMS','0'*64+'  fixtures/NOT_SCIENTIFIC_DATA.txt\n')
        (packages/'SHA256SUMS').write_text(hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
        try:execute(packages,project)
        except ValueError:checks.append({'case':'member_checksum_corruption','status':'PASSED'})
        else:raise AssertionError('Bad member SHA accepted')
    result={'status':'PASSED_OFFLINE_SYNTAX_AND_SYNTHETIC_IMPORTER_GUARDS_ONLY','code_cells_compiled':len(codes),
        'notebook_sha256':hashlib.sha256(NOTEBOOK.read_bytes()).hexdigest(),'checker_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'synthetic_byte_fixture_checks':checks,'live_colab_login_verified':False,'live_drive_verified':False,
        'scientific_model_executed_by_this_check':False}
    out=ROOT/'reports/stage3g_transfer_reliability_v1/NOTEBOOK_OFFLINE_CHECK.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
