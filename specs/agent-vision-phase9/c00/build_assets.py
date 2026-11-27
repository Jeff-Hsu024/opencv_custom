"""Rebuild supplemental contract assets only; never changes normative planning files.

Run with the isolated C00 Python. These are synthetic design fixtures, not a
runtime implementation or evidence of device/proof/lock qualification.
"""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAN = ROOT.parent
DIALECT = 'https://json-schema.org/draft/2020-12/schema'


def write(name, data):
    (ROOT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def obj(properties, required=None):
    return dict(type='object', properties=properties,
                required=list(properties) if required is None else required, additionalProperties=False)


def arr(items):
    return dict(type='array', items=items)


def nullable(s):
    return {'anyOf': [s, {'type': 'null'}]}


def enum(*values):
    return {'enum': list(values)}


S = {'type': 'string'}
N = {'type': 'integer', 'minimum': 0}
T = {'type': 'number', 'minimum': 0}
B = {'type': 'boolean'}
O = {'type': 'object'}  # Only explicitly legacy/evidence payloads use open objects.
H = {'type': 'string', 'pattern': r'^[0-9a-f]{64}$(?![\s\S])'}


def ident(prefix, length=64):
    return {'type': 'string', 'pattern': '^' + prefix + '_[0-9a-f]{' + str(length) + r'}$(?![\s\S])'}


def ref(name):
    return {'$ref': '#/$defs/' + name}


def build():
    requests = json.loads((PLAN / 'CONTRACT_SCHEMAS.json').read_text(encoding='utf-8'))['operations']
    # Preserve original examples/hashes. Supplement every operation with a valid
    # request and negatives for required fields, unknown properties and types.
    def sample(schema):
        if 'const' in schema:
            return schema['const']
        if 'enum' in schema:
            return schema['enum'][-1]  # trial proof, when applicable
        for key in ('oneOf', 'anyOf'):
            if key in schema:
                return sample(schema[key][0])
        typ = schema.get('type')
        if typ == 'object':
            return {k: sample(schema['properties'][k]) for k in schema.get('required', [])}
        if typ == 'array':
            return [sample(schema['items']) for _ in range(schema.get('minItems', 1))]
        if typ in ('number', 'integer'):
            return schema.get('minimum', schema.get('exclusiveMinimum', 0) + 1)
        if typ == 'boolean':
            return False
        pattern = schema.get('pattern', '')
        if pattern.startswith('^[a-z]'):
            return 'settings'
        import re
        m = re.match(r'\^([a-z]+)_\[0-9a-f\]\{(\d+)\}', pattern)
        if m:
            return m[1] + '_' + 'a' * int(m[2])
        if pattern.startswith('^frm_'):
            return 'frm_fixture'
        if pattern.startswith('^ref_'):
            return 'ref_fixture'
        if pattern.startswith('^ses_'):
            return 'ses_fixture'
        return 'A'
    cases = []
    for op, schema in requests.items():
        value = sample(schema)
        if op == 'portable_qualify_commit':
            value['proof_id'] = 'prun_' + 'a' * 32
        cases.append(dict(op=op, valid=True, request=value, case='minimal'))
        if op == 'scoped_transition':
            variant=copy.deepcopy(value)
            variant['postcondition']=dict(mode='image',timeout=1,asset_revision_id='ar_'+'a'*64)
            cases.append(dict(op=op,valid=True,request=variant,case='image-postcondition'))
        if op == 'portable_qualify_commit':
            cases.append(dict(op=op,valid=True,request={**value,'proof_kind':'source','proof_id':'run_'+'a'*32},case='source-proof'))
        cases.append(dict(op=op, valid=False, request={**value, 'unexpected': True}, case='unknown'))
        for key in schema['required']:
            bad = copy.deepcopy(value)
            del bad[key]
            cases.append(dict(op=op, valid=False, request=bad, case='missing-' + key))
        for key, prop in schema['properties'].items():
            if prop.get('pattern'):
                cases.append(dict(op=op,valid=False,request={**value,key:'../wrong-kind'},case='pattern-'+key))
                cases.append(dict(op=op,valid=False,request={**value,key:sample(prop)+'\n'},case='suffix-'+key))
            if 'minimum' in prop:
                cases.append(dict(op=op,valid=False,request={**value,key:prop['minimum']-1},case='minimum-'+key))
            if 'exclusiveMinimum' in prop:
                cases.append(dict(op=op,valid=False,request={**value,key:prop['exclusiveMinimum']},case='exclusive-'+key))
            if 'maximum' in prop:
                cases.append(dict(op=op,valid=False,request={**value,key:prop['maximum']+1},case='maximum-'+key))
            if key == 'devices':
                for label,devices in [('empty',[]),('duplicate',['A','A']),('oversize',['A'+str(i) for i in range(17)]),('alias',['adb'])]:
                    cases.append(dict(op=op,valid=False,request={**value,key:devices},case='devices-'+label))
            if prop.get('type') in ('integer', 'number'):
                cases.append(dict(op=op, valid=False, request={**value, key: True}, case='bool-' + key))
            if key == 'device':
                for alias in ['adb', 'desktop', '../escape', 'A\n']:
                    cases.append(dict(op=op, valid=False, request={**value, key: alias}, case='device-' + alias))
    write('REQUEST_EXAMPLES.json', cases)
    device = requests['portable_preflight']['properties']['device']
    frame = requests['scoped_find']['properties']['frame_id']
    rid = requests['guarded_click']['properties']['ref_id']
    profile = obj(dict(package=S, version_code={'type': 'integer', 'minimum': 1},
                       rotation={'type': 'integer', 'minimum': 0, 'maximum': 3}, locale=S, ui_mode=S))
    geometry = obj(dict(width={'type': 'integer', 'minimum': 1}, height={'type': 'integer', 'minimum': 1},
                        rotation={'type': 'integer', 'minimum': 0, 'maximum': 3}))
    codes = 'INVALID_ARGUMENT INVALID_DEVICE DEVICE_UNAVAILABLE DISCOVERY_FAILED NOT_FOUND SCOPE_MISMATCH DEVICE_BUSY STALE_REF_EPOCH REF_UNVERSIONED FRAME_STALE PROFILE_MISMATCH GEOMETRY_MISMATCH INITIAL_STATE_MISMATCH TARGET_NOT_FOUND TARGET_AMBIGUOUS PRECONDITION_FAILED EVIDENCE_CHANGED PROOF_INVALID QUALIFICATION_REQUIRED QUALIFICATION_INACTIVE STALE_GENERATION FAMILY_INACTIVE REQUEST_ID_CONFLICT ID_RESERVED STORE_ERROR INTERNAL_ERROR CAPTURE_TIMEOUT INTERRUPTED ACTION_UNCERTAIN'.split()
    reason = obj(dict(code=enum(*codes), message=S, details=O, retryable=B))
    reason['allOf']=[{'if':{'properties':{'retryable':{'const':True}}},
                      'then':{'properties':{'code':enum('DEVICE_BUSY','DEVICE_UNAVAILABLE','DISCOVERY_FAILED','CAPTURE_TIMEOUT')}}}]
    admitted_reason=copy.deepcopy(reason)
    admitted_reason['properties']['retryable']={'const':False}
    status = enum('in_progress', 'completed', 'needs_agent', 'interrupted', 'busy', 'rejected', 'not_attempted')
    outcome = enum('not_attempted', 'unknown', 'executed_unverified', 'verified')
    context = obj(dict(kind=enum('legacy', 'trial', 'portable_run'), definition_id=S,
                       source_workflow_id=ident('wf'), source_seal=H, device=device,
                       profile=profile, geometry=geometry, admission_id=S,
                       binding_id=nullable(S), qualification_id=nullable(ident('qlf'))))
    # Runtime step bodies are retained legacy payloads with the contract's new
    # epoch/context evidence. Detailed chronology/proof is a semantic gate.
    target=obj(dict(ref_id=rid,frame_id=frame,score={'type':'number'},
                    device_bbox={'type':'array','items':N,'minItems':4,'maxItems':4},template_sha256=H,epoch=N))
    post=obj(dict(frame_id=frame,state=nullable(S),ambiguous=B,guards=O))
    step = obj(dict(step_id=S, **{'from': S, 'to': S}, pre_frame_id=nullable(frame),
                    post_frame_id=nullable(frame), target=nullable(target), action_receipt=nullable(O),
                    status=enum('observing','action_pending','verifying','verified'), post_observations=arr(post)))
    step['additionalProperties'] = True  # nested legacy receipt per K02
    effect_props = dict(kind=S, id=S, device=device, status=status, request=O,
                        action_outcome=outcome, completed_steps=N, last_frame_id=nullable(frame),
                        last_confirmed_state=nullable(S), observation_phase=enum('none', 'pre_action', 'post_action_unknown', 'post_action'),
                        reason=nullable(admitted_reason), created_at=T, finished_at=nullable(T), duplicate_request=B,
                        steps=arr(step), action_receipt=nullable(O))
    def effect(kind, prefix, extras=None):
        schema=obj({**effect_props, 'kind': {'const': kind}, 'id': ident(prefix, 32), **(extras or {})})
        schema['allOf']=[{'if':{'properties':{'status':{'const':'in_progress'}}},
                          'then':{'properties':{'finished_at':{'type':'null'}}}}]
        return schema
    portable = obj(dict(portable_id=ident('portable'), source_workflow_id=ident('wf'), source_run_id=ident('run', 32),
                       source_device=device, source_seal=H, profile=profile, geometry=geometry,
                       step_count=N, template_sha256=arr(H), created_at=T))
    asset = obj(dict(asset_revision_id=ident('ar'), device=device, session_id=nullable(S), name=S,
                    source_frame_id=frame, region=nullable({'type':'array','items':N,'minItems':4,'maxItems':4}),
                    png_sha256=H, width=N, height=N))
    preflight = obj(dict(preflight_id=ident('preflight'), portable_id=ident('portable'), device=device,
                        status=enum('pass', 'fail'), profile=nullable(profile), geometry=nullable(geometry),
                        frame_id=nullable(frame), epoch=nullable(N), reason=nullable(reason), created_at=T))
    qualify = obj(dict(qualification_id=ident('qlf'), portable_id=ident('portable'), device=device,
                      slot_generation=N, status={'const': 'active'}, proof_kind=enum('source','trial'),
                      proof_id=S, proof_seal=H, semantic_pass=requests['portable_qualify_commit']['properties']['semantic_pass'], created_at=T,
                      duplicate_request=B))
    qualify['allOf'] = copy.deepcopy(requests['portable_qualify_commit']['allOf'])
    slot = obj(dict(portable_id=ident('portable'), device=device, slot_generation=N,
                   status=enum('absent','active','revoked','invalidated'), qualification_id=nullable(ident('qlf')),
                   reason=nullable(reason), history_count=N))
    revoke = obj({k:v for k,v in slot['properties'].items() if k != 'history_count'})
    revoke['properties']['status'] = {'const':'revoked'}
    revoke['properties']['duplicate_request'] = B
    revoke['required'].append('duplicate_request')
    family = obj(dict(family_id=S, generation=N, active_revision=nullable(N),
                      revisions=arr(obj(dict(revision=N, portable_id=ident('portable'))))))
    trial = effect('trial','prun',dict(preflight_id=ident('preflight'),portable_id=ident('portable'),context=context,source_seal=H))
    pinned = dict(run_id=ident('prun',32), family_id=S,generation=N,revision=N,qualification_id=ident('qlf'),
                  slot_generation=N,portable_id=ident('portable'),context=context)
    task = effect('portable_task','ptask',pinned)
    run = effect('portable_run','prun',dict(context=context))
    child = obj(dict(device=device,task_id=ident('ptask',32),run_id=ident('prun',32),qualification_id=ident('qlf'),
                     slot_generation=N,status=status,action_outcome=outcome,reason=nullable(reason)))
    counts = obj({k:N for k in status['enum']})
    batch = obj(dict(batch_id=ident('batch',32),request=requests['portable_batch_execute'],
                     status=enum('in_progress','completed','partial','needs_agent','interrupted'),
                     phase=enum('open','closed','reconciling','terminal'),family_id=S,generation=N,revision=N,
                     portable_id=ident('portable'),children=arr(child),counts=counts,duplicate_request=B,created_at=T,finished_at=nullable(T)))
    summaries = {
        'portable_list': portable,
        'portable_qualification_list': slot,
        'portable_family_list': obj(dict(family_id=S,generation=N,active_revision=nullable(N),revision_count=N)),
        'portable_task_list': obj({k:v for k,v in task['properties'].items() if k != 'steps'}),
        'portable_batch_list': obj({**{k:v for k,v in batch['properties'].items() if k != 'children'},
                                   'child_ids':arr(obj(dict(device=device,task_id=ident('ptask',32),run_id=ident('prun',32))))}),
    }
    results = {
        'android_devices':obj(dict(devices=arr(obj(dict(device_id=device,platform={'const':'adb'}))))),
        'asset_revision_register':asset,'asset_revision_resolve':asset,
        'scoped_find':obj(dict(device=device,frame_id=frame,asset_revision_id=ident('ar'),match_count=N,
                               matches=arr(obj(dict(ref_id=rid,device_bbox={'type':'array','items':N,'minItems':4,'maxItems':4},score={'type':'number'},epoch=N))))),
        'guarded_click':effect('guarded_click','act'), 'scoped_transition':effect('scoped_transition','strans'),
        'portable_publish':portable,'portable_inspect':portable,'portable_preflight':preflight,'portable_preflight_inspect':preflight,
        'portable_trial':trial,'portable_trial_inspect':trial,'portable_qualify_commit':qualify,
        'portable_qualification_record':qualify,'portable_qualification_revoke':revoke,'portable_qualification_inspect':slot,
        'portable_family_publish':family,'portable_family_activate':family,'portable_family_inspect':family,
        'portable_execute':task,'portable_task_inspect':task,'portable_run_inspect':{'oneOf':[trial,run]},
        'portable_batch_execute':batch,'portable_batch_inspect':batch,
    }
    for op, summary in summaries.items():
        results[op] = obj(dict(items=arr(summary),next_cursor=nullable(N)))
    for result in [*results.values(), *summaries.values()]:
        if result.get('type') == 'object':
            result['properties']['details'] = O
    schemas = {op:{'$schema':DIALECT,'oneOf':[
        obj(dict(ok={'const':True},result=result)),obj(dict(ok={'const':False},error=reason))
    ]} for op,result in results.items()}
    assert set(schemas) == set(requests)
    write('RESPONSE_SCHEMAS.json',dict(contract_version=1,operations=schemas))
    # Shape examples include nullable/unavailable observations and empty pages.
    responses=[]
    for op,schema in schemas.items():
        value=sample(schema)
        # sample strings for response-only legacy IDs and hashes
        def repair(v,s):
            if 'oneOf' in s or 'anyOf' in s:
                return repair(v,s.get('oneOf',s.get('anyOf'))[0])
            if s.get('type')=='object':
                return {k:repair(x,s['properties'].get(k,{})) for k,x in v.items()}
            if s.get('type')=='array':
                return [repair(x,s['items']) for x in v]
            if s.get('pattern')==H['pattern']:
                return 'a'*64
            return v
        value=repair(value,schema)
        if op in ('portable_qualify_commit','portable_qualification_record'):
            value['result']['proof_id']='prun_'+'a'*32
        responses.append(dict(op=op,valid=True,response=value,case='shape'))
        for code in ['INVALID_ARGUMENT','DEVICE_BUSY','DEVICE_UNAVAILABLE','DISCOVERY_FAILED','CAPTURE_TIMEOUT','PROOF_INVALID','INTERNAL_ERROR']:
            responses.append(dict(op=op,valid=True,case='error-'+code,
                                  response=dict(ok=False,error=dict(code=code,message='Synthetic rejection',details={},retryable=code in ['DEVICE_BUSY','DEVICE_UNAVAILABLE','DISCOVERY_FAILED','CAPTURE_TIMEOUT']))))
        bad=copy.deepcopy(value); bad['unexpected']=True
        responses.append(dict(op=op,valid=False,response=bad,case='unknown-envelope'))
        for key in list(value['result']):
            bad=copy.deepcopy(value); del bad['result'][key]
            responses.append(dict(op=op,valid=False,response=bad,case='missing-'+key))
        if op.endswith('_list'):
            responses.append(dict(op=op,valid=True,response=dict(ok=True,result=dict(items=[],next_cursor=None)),case='empty-page'))
        if op in ['portable_preflight','portable_preflight_inspect']:
            missing=copy.deepcopy(value)
            missing['result'].update(status='fail',profile=None,geometry=None,frame_id=None,epoch=None,
                                     reason=dict(code='CAPTURE_TIMEOUT',message='No frame captured',details={},retryable=True))
            responses.append(dict(op=op,valid=True,response=missing,case='capture-no-frame'))
    write('RESPONSE_EXAMPLES.json',responses)
    from semantic_model import child_ids
    write('ID_EXAMPLES.json',[dict(batch_id='batch_'+'a'*32,device=d,
                                  expected=child_ids('batch_'+'a'*32,d)) for d in ['A','B','127.0.0.1:16480']])


if __name__ == '__main__':
    build()
