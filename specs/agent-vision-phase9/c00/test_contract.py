"""C00 design freeze, not runtime/live acceptance. Run explicitly with pytest."""
import copy
import hashlib
import itertools
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from baseline import capture
from semantic_model import (batch_status, child_ids, effect_identity, legal_locks,
                            normalize, qualification, reconcile, storage, reserve, lookup, guard, transport)

HERE = Path(__file__).resolve().parent
PLAN = HERE.parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


REQUESTS = read(PLAN / 'CONTRACT_SCHEMAS.json')['operations']
RESPONSES = read(HERE / 'RESPONSE_SCHEMAS.json')['operations']
SEMANTICS = read(HERE / 'SEMANTIC_EXAMPLES.json')
EXAMPLES = read(HERE / 'REQUEST_EXAMPLES.json')
ORIGINAL = read(PLAN / 'CONTRACT_FIXTURES.json')
EXAMPLES += [dict(row, valid=valid, case='original') for valid,key in [(True,'valid'),(False,'invalid')] for row in ORIGINAL[key]]


@pytest.mark.parametrize('op', REQUESTS)
def test_draft202012_schemas(op):
    Draft202012Validator.check_schema(REQUESTS[op])
    Draft202012Validator.check_schema(RESPONSES[op])


def test_catalog_complete():
    assert len(REQUESTS) == 29 and REQUESTS.keys() == RESPONSES.keys()
    assert {x['op'] for x in EXAMPLES if x['valid']} == set(REQUESTS)
    assert {x['op'] for x in EXAMPLES if not x['valid']} == set(REQUESTS)


def test_explicit_regex_amendment_is_only_request_schema_change():
    original=read(HERE / 'ORIGINAL_REQUEST_SCHEMAS.json')
    current=read(PLAN / 'CONTRACT_SCHEMAS.json')
    def undo(value):
        if isinstance(value,dict):
            return {key:(item.removesuffix(r'(?![\s\S])') if key=='pattern' else undo(item)) for key,item in value.items()}
        if isinstance(value,list): return [undo(item) for item in value]
        return value
    assert undo(current) == original
    request={'portable_id':'portable_'+'a'*64+'\n','device':'A\n'}
    assert Draft202012Validator(original['operations']['portable_preflight']).is_valid(request)
    assert not Draft202012Validator(REQUESTS['portable_preflight']).is_valid(request)


@pytest.mark.parametrize('row', EXAMPLES, ids=lambda r:r['op']+'-'+r['case'])
def test_request_examples(row, tmp_path):
    schema = REQUESTS[row['op']]
    # Actual UTF-8 CLI request-file roundtrip and MCP arguments JSON projection
    # feed the same schema. Phase9 adapters are not implemented at C00.
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(row['request'], ensure_ascii=False), encoding='utf-8')
    cli = read(path)
    mcp = json.loads(json.dumps({'name':'vision_'+row['op'], 'arguments':row['request']}))['arguments']
    assert cli == mcp
    for request in [cli,mcp]:
        assert Draft202012Validator(schema).is_valid(request) == row['valid']
    if row['valid']:
        normalized = normalize(cli,schema)
        assert Draft202012Validator(schema).is_valid(normalized)
        assert normalize(normalized,schema) == normalized


@pytest.mark.parametrize('row', read(HERE / 'RESPONSE_EXAMPLES.json'), ids=lambda r:r['op']+'-'+r['case'])
def test_response_examples(row):
    assert Draft202012Validator(RESPONSES[row['op']]).is_valid(row['response']) == row['valid']


@pytest.mark.parametrize('row', SEMANTICS['qualification'], ids=lambda r:r['case'])
def test_qualification_slot_CAS(row):
    state = copy.deepcopy(row['state'])
    assert list(qualification(state,row['event'])) == row['expected']
    assert state == row['state']


@pytest.mark.parametrize('row', SEMANTICS['batch'], ids=lambda r:r['case'])
def test_batch_precedence(row):
    assert batch_status(row['children'],row['parent_live'],row['abandoned']) == row['expected']


@pytest.mark.parametrize('row', SEMANTICS['locks'])
def test_lock_order(row):
    assert legal_locks(row['sequence']) == row['valid']


@pytest.mark.parametrize('row', SEMANTICS['storage'])
def test_storage_order(row):
    assert storage(row['trace']) == row['expected']


@pytest.mark.parametrize('row', SEMANTICS['reconciliation'], ids=lambda r:r['case'])
def test_owner_reconciliation_never_dispatches(row):
    assert reconcile(row['children'],row['acquired']) == row['expected']


def test_legacy_61_tool_shapes_defaults_and_actual_query_projection():
    frozen = read(HERE / 'LEGACY_BASELINE.json')
    actual = capture()
    assert frozen['tool_count'] == 61 and actual['tool_count'] >= 61
    names={row['name'] for row in frozen['tools']}
    assert [row for row in actual['tools'] if row['name'] in names] == frozen['tools']
    def legacy_parser(current,old):
        # Additive Phase9 commands/options may coexist with every frozen action.
        by_dest={a['dest']:a for a in current}
        for action in old:
            candidate=copy.deepcopy(by_dest[action['dest']])
            if 'commands' in action:
                commands=candidate.pop('commands')
                for key,sub in action['commands'].items():
                    legacy_parser(commands[key],sub)
                assert candidate == {k:v for k,v in action.items() if k != 'commands'}
            else:
                assert candidate == action
    legacy_parser(actual['cli_parser'],frozen['cli_parser'])
    assert actual['calls'] == frozen['calls'] and actual['unknown_mcp'] == frozen['unknown_mcp']
    assert actual['snapshots'] == frozen['snapshots']


def test_normalized_identity_and_duplicate_projection():
    schema = REQUESTS['portable_execute']
    value = dict(family_id='settings',expected_generation=2,device='A',task_id='ptask_'+'a'*32)
    original = effect_identity(value,schema)
    assert effect_identity({**value,'return_image':True},schema) == original
    assert effect_identity({**value,'return_image':False},schema) == original
    assert effect_identity({**value,'device':'B'},schema) != original
    assert normalize({},REQUESTS['portable_list']) == {'limit':20,'after':0}
    batch=dict(batch_id='batch_'+'a'*32,family_id='settings',expected_generation=2,devices=['A','B'])
    assert normalize(batch,REQUESTS['portable_batch_execute'])['max_concurrency'] == 2
    assert effect_identity(batch,REQUESTS['portable_batch_execute']) != effect_identity({**batch,'devices':['B','A']},REQUESTS['portable_batch_execute'])


def test_namespaces_and_child_id_golden():
    golden = read(HERE / 'ID_EXAMPLES.json')
    for row in golden:
        assert child_ids(row['batch_id'],row['device']) == row['expected']
    patterns={p:re.compile('^'+p+'_[0-9a-f]{'+str(n)+'}$') for n,ps in [(64,['portable','preflight','qlf','ar']),(32,['act','strans','prun','ptask','batch','run','task','trans'])] for p in ps}
    for p,pattern in patterns.items():
        length = 64 if p in ['portable','preflight','qlf','ar'] else 32
        identifier = p+'_'+'a'*length
        assert pattern.fullmatch(identifier)
        assert sum(bool(other.fullmatch(identifier)) for other in patterns.values()) == 1
        assert not pattern.fullmatch(identifier.upper())
        assert not pattern.fullmatch(identifier+'\n')


def test_atomic_reservation_and_standalone_child_rejection():
    # Set-based atomic admission oracle, no SQLite/process claim qualification.
    ids=[child_ids('batch_'+'a'*32,device) for device in ['A','B']]
    proposed={'batch_'+'a'*32} | {v for pair in ids for v in pair.values()}
    existing={ids[1]['run_id']:'independent'}
    before=existing.copy()
    admitted,code=reserve(existing,{key:'reserved' for key in proposed})
    assert code == 'REQUEST_ID_CONFLICT' and admitted == before
    admitted,code=reserve({}, {key:'reserved' for key in proposed})
    assert code == 'ok' and set(admitted) == proposed and len(admitted) == 5
    claim=dict(request_hash='same',state='reserved',parent_id='batch_'+'a'*32)
    assert lookup(claim,'same',standalone=True) == 'ID_RESERVED'
    assert lookup(claim,'different') == 'REQUEST_ID_CONFLICT'
    assert lookup({**claim,'state':'running'},'same') == 'original_receipt'
    assert lookup({**claim,'state':'terminal'},'same') == 'original_receipt'


def test_epoch_and_scope_contract_vectors():
    epoch={'A':7,'B':3}
    old_ref=dict(device='A',session='ses_one',epoch=7)
    epoch['A'] += 1  # pending persisted before possibly effective input, even crash
    assert guard(old_ref,'A','ses_one',epoch['A']) == 'STALE_REF_EPOCH' and epoch['B'] == 3
    fresh_ref={**old_ref,'epoch':epoch['A']}
    assert guard(fresh_ref,'A','ses_one',epoch['A']) == 'ok'
    assert guard(fresh_ref,'B','ses_one',epoch['B']) == 'SCOPE_MISMATCH'
    assert guard(fresh_ref,'A','ses_two',epoch['A']) == 'SCOPE_MISMATCH'
    assert guard({'device':'A'},'A',None,epoch['A']) == 'REF_UNVERSIONED'


@pytest.mark.parametrize('status', ['in_progress','completed','needs_agent','interrupted','busy','rejected','not_attempted'])
def test_CLI_MCP_receipt_mapping(status):
    assert transport(True,status=status) == [0 if status in ['completed','in_progress'] else 3,False]
    assert transport(True,query=True,status=status) == [0,False]


@pytest.mark.parametrize('code,exit_code', [('INVALID_ARGUMENT',2),('CAPTURE_TIMEOUT',4),('DEVICE_BUSY',3),('DEVICE_UNAVAILABLE',3),('INTERNAL_ERROR',3)])
def test_CLI_MCP_rejection_mapping(code,exit_code):
    assert transport(False,code=code) == [exit_code,True]


def test_planning_and_frozen_asset_hashes():
    frozen = read(HERE / 'FREEZE.json')
    for name,expected in frozen['lf_sha256'].items():
        content=(PLAN / name).read_bytes().replace(b'\r\n',b'\n')
        assert hashlib.sha256(content).hexdigest() == expected, name
    manifest=read(PLAN / 'ticket-manifest.json')
    for key,name in [('use_cases','USE_CASES.md'),('spec','SPEC.md'),('contract','CONTRACT.md'),('schemas','CONTRACT_SCHEMAS.json'),('fixtures','CONTRACT_FIXTURES.json')]:
        assert manifest['hashes'][key] == frozen['lf_sha256'][name]
