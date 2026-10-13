"""Finite received-material inventory; never reads forecasting values or scores.

Run from the repository root. File mtimes are deliberately not used as receipt
dates. Generated requests, API response records and previous study outputs do
not count as replies from a provider or supervisor.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    inventory = []
    received_roots = [Path('/workspace/attachments'), ROOT / 'materials']
    archive_member_inventory = []
    for directory in received_roots:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob('*')):
            if not path.is_file() or path.name == '.gitkeep':
                continue
            entry = {
                'path': str(path), 'bytes': path.stat().st_size,
                'sha256': sha(path), 'receipt_date_basis': 'project original-input record; not filesystem mtime',
                'known_receipt_date': '2026-10-09',
                'role': ('original user attachment' if directory == Path('/workspace/attachments')
                         else 'original container copy or extracted original member; not a new Stage3F provider reply'),
            }
            inventory.append(entry)
            if path.suffix.lower() == '.zip' and directory == ROOT / 'materials':
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        if member.is_dir():
                            continue
                        archive_member_inventory.append({
                            'container': str(path.relative_to(ROOT)),
                            'container_sha256': entry['sha256'],
                            'member': member.filename, 'bytes': member.file_size,
                            'crc32_from_original_container': f'{member.CRC:08x}',
                            'new_external_reply': False,
                        })
    docx = ROOT / 'materials/received_stage2_20261009/paper idea.docx'
    with zipfile.ZipFile(docx) as archive:
        tree = ET.fromstring(archive.read('word/document.xml'))
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    paragraphs = [
        ''.join(t.text or '' for t in p.findall('.//w:t', ns))
        for p in tree.findall('.//w:body/w:p', ns)
    ]
    extracted_path = OUT / 'paper_idea_read_from_original_docx.txt'
    extracted_path.write_text('\n'.join(paragraphs) + '\n', encoding='utf-8')
    # Filename discovery can reveal an unexpected received file, but cannot
    # certify a document's provenance or completeness by name alone.
    basename_hits = []
    exclude = {'.git', '.venv-stage2', '.cache', 'runs', 'figures', 'delivery',
               'deliverables', 'preservation', 'validation', '__pycache__'}
    pattern = re.compile(r'(reply|reviewer|dictionary|data.?dictionary|mentor|supervisor|guna|mapping)', re.I)
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in exclude for part in relative.parts):
            continue
        if 'stage3f_evidence_gate_v1' in relative.parts:
            continue
        if pattern.search(path.name):
            basename_hits.append(str(relative))
    status = {
        'stage': 'stage3f_evidence_gate_v1',
        'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'input_status': 'WAITING_FOR_EXTERNAL_EVIDENCE',
        'scope_limitation': 'Finite inventory of actual attachment/material roots and repository metadata/document filenames; no claim about email accounts, inaccessible external drives or documents not uploaded to this workspace.',
        'received_roots_scanned': [str(p) for p in received_roots],
        'received_file_instances': len(inventory),
        'actual_attachment_files': sum(Path(e['path']).is_relative_to('/workspace/attachments') for e in inventory),
        'repository_copies_include_extracted_original_members': True,
        'unique_received_content_sha256_count': len({e['sha256'] for e in inventory}),
        'received_files': inventory,
        'original_archive_member_inventory': archive_member_inventory,
        'repository_document_basename_hits': basename_hits,
        'new_provider_reply_found_in_scanned_inputs': False,
        'new_supervisor_journal_confirmation_found_in_scanned_inputs': False,
        'new_historical_facility_mapping_found_in_scanned_inputs': False,
        'new_daily_time_dictionary_found_in_scanned_inputs': False,
        'stage3e_external_review': {
            'user_reported_results_available_in_conversation': True,
            'reviewer_original_document_received_in_scanned_inputs': False,
            'limits': 'The user reports an external review. Its report, raw logs and checked attachment copies are not available here as new received files; do not claim an independent review of those missing originals.',
        },
        'paper_idea': {
            'original_docx': str(docx.relative_to(ROOT)), 'bytes': docx.stat().st_size,
            'sha256': sha(docx), 'paragraphs_read': len(paragraphs),
            'extracted_file': str(extracted_path.relative_to(ROOT)),
            'extracted_sha256': sha(extracted_path),
            'final_target_journal_name_present': False,
            'read_findings': 'Existing facilities; limited initial history; processed daily discharge volume; one-day/third-day target; no energy/overflow/new-plant/real-time generalisation. No final journal decision in this DOCX.',
        },
        'target_journal': {
            'status': 'UNCONFIRMED',
            'old_handoff_source': 'materials/received_20261009/Wastewater_Part3_Codex_Handoff.zip::Codex_Handoff_2026-10-09/JOURNAL_AND_LITERATURE.md',
            'finding': 'Old plan named JWPE, later user removed it. Journal of Hydroinformatics and Water Science & Technology remain candidates; no final supervisor confirmation received.',
        },
        'old_generated_mapping_files_are_not_new_provider_replies': True,
        'old_official_queries_are_not_new_provider_replies': True,
        'file_mtime_used_as_receipt_evidence': False,
        'forecast_result_values_read': False,
        'original_data_bytes_hashed_only': True,
        'new_performance_computed': False,
        'metadata_verification_run_on_new_provider_mapping': False,
        'metadata_fixture_tests_required': False,
        'metadata_fixture_reason': 'No new mapping input was received, so no unnecessary synthetic mapping checks or fabricated facility verification were performed.',
        'checker_path': str(Path(__file__).relative_to(ROOT)), 'checker_sha256': sha(Path(__file__)),
    }
    path = OUT / 'NEW_EXTERNAL_INPUT_STATUS.json'
    path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: status[k] for k in ['input_status', 'actual_attachment_files', 'received_file_instances', 'unique_received_content_sha256_count', 'new_performance_computed']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
