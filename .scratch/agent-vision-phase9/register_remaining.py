"""One-shot native task registration, never a scheduler or retry harness."""
import json
import pathlib
import shutil
import subprocess

root = pathlib.Path.cwd()
out = root / '.scratch/agent-vision-phase9/coordinator'
out.mkdir(exist_ok=True)
run = 'run_212fdcb86d47'
cli = shutil.which('orca')
manifest = json.loads((root/'specs/agent-vision-phase9/ticket-manifest.json').read_text())
mapping = {'C00': 'task_ac79f0fdd976'}
mapping_path = out/'task-mapping.json'
if mapping_path.exists():
    raise SystemExit('Registration receipt already exists; inspect before any recovery.')
constraints = '''
Coordinator global constraints (normative task execution boundaries):
Read AGENTS.md, all nine specs/agent-vision-phase9 planning files, C00 REPORT.md, STATES.md, FREEZE.json and K08 amendment; implement this original ticket only against frozen contract. Existing project opencv_custom, feature branch feat/agent-vision-multi-device, current existing worktree only. No new projects/worktrees, main merge/push, release/deployment, official Store/archive or immutable acceptance evidence changes, no Queqiao wrapper. Do not edit coordinator-owned IMPLEMENTATION_STATUS.md or registration evidence. Serialize all writes under coordinator dispatch; do not launch workers or downstream tasks.
Preserve legacy 308 regression cases, 61 MCP tools/defaults, binding/proof/recorder/API, source-device guard; expand/migrate/contract with outer gate until C11. Agent-specific state in vision_app, preserve Core except narrowly allowed discovery fix. CLI/MCP share service and store; native MCP ImageContent. Shared metadata transactions, durable pre-input epoch, immutable revisions, independent family/slot CAS, atomic parent/child IDs, actual OS plus thread owner locks, no unknown replay, surviving live child never falsely interrupted. No mocking proof or ownership to manufacture success.
Use isolated temporary candidate stores and .scratch/c00-env Python as appropriate; never modify real evidence/bundles/device instances in tests. Run real targeted tests and required python -m pytest core/test vision_app/test -q with PYTHONPATH=core;. on Windows; report actual commands/exits/counts. Each implementation task commits scoped changes only on feature branch and writes its own concrete report/evidence paths; exclude coordinator files and unrelated changes. worker_done only with actual results, commit and evidence; failures must be reported honestly, never marked success. Contradictions require precise evidence and coordinator escalation, no silent contract/hash changes or blind retries.
No device input until two explicitly selected authorized compatible Android devices are established. Currently only 127.0.0.1:16480 and desktop externally observed; desktop is not Android. Never start/connect/operate other devices. V01 is independent compatibility verification with real subprocess barriers and consistency/crash/revocation/drift/timeout/duplicate/batch tests. V02 must be a fresh independent agent: raw SQLite/PNG/journal audit, A learns once, B same definition qualifies without re-exploration, two repeats each and actual overlap/isolation; if only one device remains report BLOCKED_LIVE_DEVICE, never fake PASS. Continue software-only acceptance where possible.
Placement: this machine (local), NB explicitly named by user.
'''
mapping_path.write_text(json.dumps({'run_id':run,'tickets':mapping},indent=2))
for ticket in manifest['tickets'][1:]:
    spec = out/(ticket['id']+'-spec.md')
    spec.write_text((root/ticket['file']).read_text(encoding='utf-8')+'\n'+constraints,encoding='utf-8')
    args=[cli,'orchestration','task-create','--environment','local','--run',run,'--task-title',ticket['id']+' '+ticket['title'],'--spec-file',str(spec),'--deps',json.dumps([mapping[d] for d in ticket['blocked_by']]),'--full','--json']
    result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8')
    (out/(ticket['id']+'-registration.json')).write_text(result.stdout,encoding='utf-8')
    (out/(ticket['id']+'-registration.stderr.txt')).write_text(result.stderr,encoding='utf-8')
    if result.returncode:
        raise SystemExit('Native registration failed: '+ticket['id']+'; inspect saved receipt, do not rerun batch.')
    receipt=json.loads(result.stdout)
    body=receipt['result']
    task_id=body.get('taskId') or body.get('id') or body.get('task',{}).get('id')
    if not task_id:
        raise SystemExit('Inspect registration receipt; unrecognized task ID location, no retry.')
    mapping[ticket['id']]=task_id
    mapping_path.write_text(json.dumps({'run_id':run,'tickets':mapping},indent=2),encoding='utf-8')
    print(ticket['id'],task_id,flush=True)
result=subprocess.run([cli,'orchestration','task-list','--environment','local','--run',run,'--full','--json'],capture_output=True,text=True,encoding='utf-8')
(out/'native-graph.json').write_text(result.stdout,encoding='utf-8')
result.check_returncode()
tasks={t['id']:t for t in json.loads(result.stdout)['result']['tasks']}
for ticket in manifest['tickets']:
    task=tasks[mapping[ticket['id']]]
    deps=task['deps']
    if isinstance(deps,str): deps=json.loads(deps)
    assert set(deps)=={mapping[d] for d in ticket['blocked_by']},ticket['id']
    if ticket['id']!='C00': assert (root/ticket['file']).read_text(encoding='utf-8') in task['spec']
summary={'run_id':run,'manifest_nodes':len(mapping),'manifest_edges':sum(len(t['blocked_by']) for t in manifest['tickets']),'verified':True,'extra_native_tasks':[t for t in tasks if t not in mapping.values()]}
(out/'graph-verification.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary),flush=True)
