"""Explicit C00 hash refresh; test execution never rewrites fixtures or hashes."""
import hashlib
import json
import subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
PLAN=HERE.parent
REPO=PLAN.parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()


if __name__ == '__main__':
    manifest_path=PLAN/'ticket-manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    for key,name in [('use_cases','USE_CASES.md'),('spec','SPEC.md'),('contract','CONTRACT.md'),('schemas','CONTRACT_SCHEMAS.json'),('fixtures','CONTRACT_FIXTURES.json')]:
        manifest['hashes'][key]=sha(PLAN/name)
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    original=json.loads(subprocess.check_output(['git','show','9a3bffcf9b8a2d5090343121d01cceda74a9456e:specs/agent-vision-phase9/ticket-manifest.json'],cwd=REPO))['hashes']
    files=[p for p in PLAN.iterdir() if p.is_file() and p.name != 'IMPLEMENTATION_STATUS.md']
    files += [p for p in HERE.iterdir() if p.is_file() and p.name not in ['FREEZE.json','REPORT.md']]
    frozen=dict(contract_version=1,amendment='K08 C00 response freeze amendment 1',
                hash_encoding='UTF-8 LF normalized',baseline='bfbec17fe55b25a2ea7ddbd9051cc3937ccd3efb',
                planning_parent='9a3bffcf9b8a2d5090343121d01cceda74a9456e',original_planning_hashes=original,
                lf_sha256={p.relative_to(PLAN).as_posix():sha(p) for p in sorted(files)})
    (HERE/'FREEZE.json').write_text(json.dumps(frozen,indent=2)+'\n',encoding='utf-8')
