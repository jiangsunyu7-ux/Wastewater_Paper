"""Register actual Stage3F content commit and waiting state, not a new experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
VERSION='stage3f_evidence_gate_v1'
REPORT=ROOT/'reports'/VERSION

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(path):return json.loads(Path(path).read_text())
def save(path,data):Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source-commit',required=True)
    args=parser.parse_args();now=datetime.now(timezone.utc).isoformat()
    original=load(REPORT/'PRESERVATION_BEFORE.json');changed=[]
    for record in original['files']:
        p=ROOT/record['path']
        if not p.is_file() or p.stat().st_size!=record['bytes'] or sha(p)!=record['sha256']:changed.append(record['path'])
    assert not changed,changed
    save(REPORT/'PRESERVATION_AFTER.json',dict(status='PASSED_BYTES_ONLY_NO_SCIENTIFIC_RERUN',
        files_checked=len(original['files']),bytes_checked=original['bytes'],changed_files=changed,
        before_manifest_sha256=sha(REPORT/'PRESERVATION_BEFORE.json'),checked_utc=now))
    py=sorted(set(REPORT.rglob('*.py'))|{ROOT/'scripts/package_stage3f.py',ROOT/'scripts/finalize_stage3f.py'})
    selected=py+[ROOT/'STAGE3F_PROTOCOL.md',ROOT/'configs'/VERSION/'full.json']
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in selected}
    for name,h in hashes.items():
        blob=subprocess.check_output(['git','cat-file','blob',args.source_commit+':'+name],cwd=ROOT)
        assert hashlib.sha256(blob).hexdigest()==h,name
    inputs=load(REPORT/'external_inputs/NEW_EXTERNAL_INPUT_STATUS.json')
    assert inputs['input_status']=='WAITING_FOR_EXTERNAL_EVIDENCE'
    assert not any(inputs[k] for k in ['new_provider_reply_found_in_scanned_inputs','new_supervisor_journal_confirmation_found_in_scanned_inputs','new_historical_facility_mapping_found_in_scanned_inputs','new_daily_time_dictionary_found_in_scanned_inputs'])
    gates=load(REPORT/'requests/REQUEST_SCOPE_CHECK.json');lit=load(REPORT/'literature_delta/LITERATURE_DELTA_STATUS.json')
    save(REPORT/'CODE_VERSION.json',dict(version=VERSION,source_commit=args.source_commit,
        source_commit_is_real_content_not_base_HEAD=True,committed_files_sha256=hashes,
        actual_Git_blob_contents_verified=True,
        original_science_commit_and_member_reference='delivery_chain/CODE_CONTENT_AND_COMMIT.json',
        old_Stage3E_commit='d7eda982a91084a3b875e351de1e91dae0e5cacf',
        old_Stage3C2_commit='f33e38a8d28bf3206989794240cc35e63d62f017',
        base_checkout_HEAD_not_a_complete_scientific_version=True,
        source_config_sha256=sha(ROOT/'configs'/VERSION/'full.json')))
    save(REPORT/'RUN_STATUS.json',dict(version=VERSION,status='WAITING_FOR_EXTERNAL_EVIDENCE',
        local_preparation_completed=True,prepared_utc=now,python=platform.python_version(),dependencies='Python standard library',
        new_provider_reply_received=False,new_supervisor_decision_received=False,new_historical_mapping_received=False,
        physical_mapping_verified=False,verified_real_time=False,new_prediction_performance_computed=False,
        new_models_trained=0,old_models_retrained=0,old_Stage3E_scientific_workflows_rerun=0,
        final_or_protected_performance_computed=False,emails_or_forms_sent=False,
        independent_validation_protocol_created=False,next_validation_execute_allowed=False,
        independent_physical_retrospective_gate='NOT_VERIFIED',real_time_gate='NOT_VERIFIED',
        history_saving_engineering_gate='NOT_ESTABLISHED',novelty_gate='PARTIAL_LITERATURE_ONLY',target_journal='UNCONFIRMED',
        original_files_preserved=len(original['files']),old_changed_files=0,
        request_list=dict(source_ids=gates['unique_source_ids'],development_ids=gates['development_ids'],total=gates['request_ids']),
        new_legitimate_literature_requests=lit['network_requests'],new_fulltexts=lit['new_fulltexts_obtained'],
        new_official_contact_requests=len(load(REPORT/'contacts/CONTACT_ACCESS_LEDGER.json')),
        executed=['actual old delivery receipts/C2 originals located and byte-checked',
            'original container CRC/memberSHA and local committed blob equality only; no science replay',
            'finite actual received-material inventory and original paperidea read',
            'claim-specific gates and85-SiteID request scope',
            'unsent328-word English request, Chinese counterpart, minimal templates and mentor decision',
            'three-record literature delta with genuine new author leads; no new methods/fulltext'],
        not_executed=['new prediction/performance','oldE20tests/calibration/bootstrap reruns','real new facility relationship check without new crosswalk',
            'independent/final testing','contacting anyone','new models/sources/gamma/weather/rolling calibration/paper/App'],
        failures_preserved=['initial new finalizer py_compile syntax error before execution; helper corrected, failed source retained',
            'new contact/author-methods tunnel403 responses with no official page body',
            'first new supplement rejected undeclared nested checksum member; manifest fixed, failed archive retained'],
        original_external_E_review='user-reported already-completed review, original reviewer attachment not received here',
        runtime_guard_scope='Existing Stage3E small single-process only; natural nineRUNNING cause remains unknown',
        unique_current_action='User sends minimal evidence request and returns dated replies/templates/mentor decisions',STOP=True,
        source_code_commit=args.source_commit,packaging_validation='Separate real STAGE3F_PACKAGE_CHECKS.json, not scientific claims'))
    print(json.dumps(dict(status='WAITING_FOR_EXTERNAL_EVIDENCE',local_preparation_completed=True,
        preserved_files=len(original['files']),source_commit=args.source_commit,new_models=0),indent=2))

if __name__=='__main__':main()
