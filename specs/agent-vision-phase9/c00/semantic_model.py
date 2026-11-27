"""Pure C00 contract oracle. No I/O, proof bypass, scheduler or production use.

Fixtures define expected state transitions; future implementation tests must use
real ownership/proof/storage seams independently. This models design only.
"""
import copy
import hashlib
import json


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def normalize(value, schema):
    value = copy.deepcopy(value)
    if isinstance(value, dict):
        for branch in schema.get('oneOf', schema.get('anyOf', [])):
            if branch.get('type') == 'object' and branch.get('properties', {}).get('mode', {}).get('const') == value.get('mode'):
                schema = branch
                break
        for key, prop in schema.get('properties', {}).items():
            if key not in value and 'default' in prop:
                value[key] = copy.deepcopy(prop['default'])
            if key in value:
                value[key] = normalize(value[key], prop)
    return value


def effect_identity(value, schema):
    value = normalize(value, schema)
    value.pop('return_image', None)
    return digest(value)


def child_ids(batch_id, device):
    task = 'ptask_' + digest(dict(kind='batch-child-task', batch_id=batch_id, device=device))[:32]
    run = 'prun_' + digest(dict(kind='task-run', task_id=task, device=device))[:32]
    return dict(task_id=task, run_id=run)


def batch_status(children, parent_live, abandoned):
    if any(c['status'] in ('reserved', 'running') and (parent_live or c.get('owner_live', False)) for c in children):
        return ['in_progress', 'open' if parent_live else 'reconciling']
    states = [c['status'] for c in children]
    if all(s == 'completed' for s in states):
        return ['completed', 'terminal']
    if abandoned and any(s in ('not_attempted', 'interrupted') for s in states):
        return ['interrupted', 'terminal']
    if 'completed' in states:
        return ['partial', 'terminal']
    return ['needs_agent', 'terminal']


def qualification(state, event):
    state = copy.deepcopy(state)
    action = event['action']
    # Duplicate lookup precedes CAS, current state or probe.
    if event.get('duplicate'):
        return state, 'original_receipt'
    if action == 'probe_unknown' or action == 'profile_restored':
        return state, 'unchanged'
    if event['expected'] != state['generation']:
        return state, 'STALE_GENERATION'
    if action == 'drift':
        if state['status'] != 'active':
            return state, 'unchanged'
        state.update(status='invalidated', generation=state['generation']+1)
    elif action == 'revoke':
        if state['status'] == 'absent':
            return state, 'NOT_FOUND'
        if state['status'] != 'active':
            return state, 'QUALIFICATION_INACTIVE'
        state.update(status='revoked', generation=state['generation']+1)
    elif action == 'commit':
        if event.get('proof_kind') == 'source' and (state['status'] != 'absent' or not event.get('source_device')):
            return state, 'PROOF_INVALID'
        if state['status'] != 'absent' and not event.get('fresh_trial'):
            return state, 'PROOF_INVALID'
        state.update(status='active', generation=state['generation']+1, qualification_id=event['qualification_id'])
    return state, 'ok'


def reconcile(children, parent_owner_acquired):
    children = copy.deepcopy(children)
    if not parent_owner_acquired:
        return dict(phase='open', children=children, dispatched=0)
    for child in children:
        if child['status'] == 'reserved':
            child.update(status='not_attempted', action_outcome='not_attempted')
        elif child['status'] == 'running' and not child['owner_live']:
            child.update(status='interrupted', action_outcome='unknown' if child.get('pending') else child['action_outcome'])
    phase = 'reconciling' if any(c['status']=='running' for c in children) else 'terminal'
    return dict(phase=phase, children=children, dispatched=0)


ORDER = ['compatibility', 'parent', 'request', 'device', 'metadata']


def legal_locks(sequence):
    # Names are lock classes; duplicate device/request acquisition is forbidden.
    return len(set(sequence)) == len(sequence) and all(ORDER.index(a) < ORDER.index(b) for a,b in zip(sequence,sequence[1:]))


def storage(trace):
    durable = False
    indexed = False
    pinned = False
    protected = False
    revision = 0
    snapshot = None
    result = 'ok'
    for event in trace:
        if event == 'publish_bytes': durable = True
        elif event == 'commit_pointer':
            if not durable: return 'TORN_PUBLICATION'
            indexed = True
        elif event == 'pin': pinned = True
        elif event == 'unpin': pinned = False
        elif event == 'protect': protected = True
        elif event == 'unprotect': protected = False
        elif event == 'remove_index':
            if pinned or protected: return 'PROTECTED'
            indexed = False
        elif event == 'delete_bytes':
            if indexed or pinned or protected: return 'UNSAFE_DELETE'
            durable = False
        elif event == 'snapshot': snapshot = revision
        elif event == 'mutate': revision += 1
        elif event == 'commit_evidence':
            if snapshot != revision: return 'EVIDENCE_CHANGED'
        elif event == 'crash': result = 'orphan_only' if durable and not indexed else 'coherent'
    return result


def reserve(existing, proposed):
    """Atomic admission oracle: no partial writes on any task/run collision."""
    if not set(existing).isdisjoint(proposed):
        return existing.copy(), 'REQUEST_ID_CONFLICT'
    return {**existing, **proposed}, 'ok'


def lookup(claim, request_hash, standalone=False):
    if claim['request_hash'] != request_hash:
        return 'REQUEST_ID_CONFLICT'
    if standalone and claim['state'] == 'reserved' and claim['parent_id']:
        return 'ID_RESERVED'
    return 'original_receipt'


def guard(reference, device, session, epoch):
    if reference['device'] != device or (reference.get('session') is not None and reference['session'] != session):
        return 'SCOPE_MISMATCH'
    if 'epoch' not in reference:
        return 'REF_UNVERSIONED'
    if reference['epoch'] != epoch:
        return 'STALE_REF_EPOCH'
    return 'ok'


def transport(ok, query=False, status=None, code=None):
    if not ok:
        return [2 if code == 'INVALID_ARGUMENT' else 4 if code == 'CAPTURE_TIMEOUT' else 3, True]
    return [0 if query or status in (None,'completed','in_progress') else 3, False]
