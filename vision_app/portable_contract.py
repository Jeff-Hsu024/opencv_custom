"""Runtime copy of the frozen portable request schema catalog (no dev dependency)."""
import math
import re
from vision_app.observation import OperationError

CATALOG={'portable_publish': {'type': 'object',
                      'properties': {'source_workflow_id': {'type': 'string',
                                                            'pattern': '^wf_[0-9a-f]{64}$(?![\\s\\S])'},
                                     'source_run_id': {'type': 'string',
                                                       'pattern': '^run_[0-9a-f]{32}$(?![\\s\\S])'}},
                      'required': ['source_workflow_id', 'source_run_id'],
                      'additionalProperties': False},
 'portable_inspect': {'type': 'object',
                      'properties': {'portable_id': {'type': 'string',
                                                     'pattern': '^portable_[0-9a-f]{64}$(?![\\s\\S])'}},
                      'required': ['portable_id'],
                      'additionalProperties': False},
 'portable_list': {'type': 'object',
                   'properties': {'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 20},
                                  'after': {'type': 'integer', 'minimum': 0, 'default': 0}},
                   'required': [],
                   'additionalProperties': False},
 'portable_preflight': {'type': 'object',
                        'properties': {'portable_id': {'type': 'string',
                                                       'pattern': '^portable_[0-9a-f]{64}$(?![\\s\\S])'},
                                       'device': {'type': 'string',
                                                  'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'},
                                       'return_image': {'type': 'boolean', 'default': False}},
                        'required': ['portable_id', 'device'],
                        'additionalProperties': False},
 'portable_preflight_inspect': {'type': 'object',
                                'properties': {'preflight_id': {'type': 'string',
                                                                'pattern': '^preflight_[0-9a-f]{64}$(?![\\s\\S])'},
                                               'return_image': {'type': 'boolean', 'default': False}},
                                'required': ['preflight_id'],
                                'additionalProperties': False},
 'portable_trial': {'type': 'object',
                    'properties': {'preflight_id': {'type': 'string',
                                                    'pattern': '^preflight_[0-9a-f]{64}$(?![\\s\\S])'},
                                   'device': {'type': 'string',
                                              'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'},
                                   'run_id': {'type': 'string', 'pattern': '^prun_[0-9a-f]{32}$(?![\\s\\S])'},
                                   'return_image': {'type': 'boolean', 'default': False}},
                    'required': ['preflight_id', 'device', 'run_id'],
                    'additionalProperties': False},
 'portable_trial_inspect': {'type': 'object',
                            'properties': {'run_id': {'type': 'string',
                                                      'pattern': '^prun_[0-9a-f]{32}$(?![\\s\\S])'},
                                           'return_image': {'type': 'boolean', 'default': False}},
                            'required': ['run_id'],
                            'additionalProperties': False},
 'portable_qualify_commit': {'type': 'object',
                             'properties': {'portable_id': {'type': 'string',
                                                            'pattern': '^portable_[0-9a-f]{64}$(?![\\s\\S])'},
                                            'device': {'type': 'string',
                                                       'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'},
                                            'expected_slot_generation': {'type': 'integer', 'minimum': 0},
                                            'proof_kind': {'enum': ['source', 'trial']},
                                            'proof_id': {'anyOf': [{'type': 'string',
                                                                    'pattern': '^run_[0-9a-f]{32}$(?![\\s\\S])'},
                                                                   {'type': 'string',
                                                                    'pattern': '^prun_[0-9a-f]{32}$(?![\\s\\S])'}]},
                                            'semantic_pass': {'type': 'object',
                                                              'properties': {'verification': {'const': 'PASS'},
                                                                             'observation': {'type': 'string',
                                                                                             'minLength': 1,
                                                                                             'maxLength': 4000},
                                                                             'reviewer': {'type': 'string',
                                                                                          'minLength': 1,
                                                                                          'maxLength': 128}},
                                                              'required': ['verification',
                                                                           'observation',
                                                                           'reviewer'],
                                                              'additionalProperties': False}},
                             'required': ['portable_id',
                                          'device',
                                          'expected_slot_generation',
                                          'proof_kind',
                                          'proof_id',
                                          'semantic_pass'],
                             'additionalProperties': False,
                             'allOf': [{'if': {'properties': {'proof_kind': {'const': 'source'}}},
                                        'then': {'properties': {'proof_id': {'type': 'string',
                                                                             'pattern': '^run_[0-9a-f]{32}$(?![\\s\\S])'}}}},
                                       {'if': {'properties': {'proof_kind': {'const': 'trial'}}},
                                        'then': {'properties': {'proof_id': {'type': 'string',
                                                                             'pattern': '^prun_[0-9a-f]{32}$(?![\\s\\S])'}}}}]},
 'portable_qualification_revoke': {'type': 'object',
                                   'properties': {'portable_id': {'type': 'string',
                                                                  'pattern': '^portable_[0-9a-f]{64}$(?![\\s\\S])'},
                                                  'device': {'type': 'string',
                                                             'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'},
                                                  'expected_slot_generation': {'type': 'integer',
                                                                               'minimum': 0},
                                                  'reason': {'type': 'string',
                                                             'minLength': 1,
                                                             'maxLength': 1000}},
                                   'required': ['portable_id',
                                                'device',
                                                'expected_slot_generation',
                                                'reason'],
                                   'additionalProperties': False},
 'portable_qualification_inspect': {'type': 'object',
                                    'properties': {'portable_id': {'type': 'string',
                                                                   'pattern': '^portable_[0-9a-f]{64}$(?![\\s\\S])'},
                                                   'device': {'type': 'string',
                                                              'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'}},
                                    'required': ['portable_id', 'device'],
                                    'additionalProperties': False},
 'portable_qualification_record': {'type': 'object',
                                   'properties': {'qualification_id': {'type': 'string',
                                                                       'pattern': '^qlf_[0-9a-f]{64}$(?![\\s\\S])'}},
                                   'required': ['qualification_id'],
                                   'additionalProperties': False},
 'portable_qualification_list': {'type': 'object',
                                 'properties': {'portable_id': {'type': 'string',
                                                                'pattern': '^portable_[0-9a-f]{64}$(?![\\s\\S])'},
                                                'limit': {'type': 'integer',
                                                          'minimum': 1,
                                                          'maximum': 50,
                                                          'default': 20},
                                                'after': {'type': 'integer', 'minimum': 0, 'default': 0}},
                                 'required': ['portable_id'],
                                 'additionalProperties': False},
 'portable_family_publish': {'type': 'object',
                             'properties': {'family_id': {'type': 'string',
                                                          'pattern': '^[a-z][a-z0-9_-]{0,63}$(?![\\s\\S])'},
                                            'portable_id': {'type': 'string',
                                                            'pattern': '^portable_[0-9a-f]{64}$(?![\\s\\S])'},
                                            'expected_generation': {'type': 'integer', 'minimum': 0},
                                            'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1000}},
                             'required': ['family_id', 'portable_id', 'expected_generation', 'reason'],
                             'additionalProperties': False},
 'portable_family_activate': {'type': 'object',
                              'properties': {'family_id': {'type': 'string',
                                                           'pattern': '^[a-z][a-z0-9_-]{0,63}$(?![\\s\\S])'},
                                             'revision': {'anyOf': [{'type': 'integer', 'minimum': 1},
                                                                    {'type': 'null'}]},
                                             'expected_generation': {'type': 'integer', 'minimum': 0},
                                             'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1000}},
                              'required': ['family_id', 'revision', 'expected_generation', 'reason'],
                              'additionalProperties': False},
 'portable_family_inspect': {'type': 'object',
                             'properties': {'family_id': {'type': 'string',
                                                          'pattern': '^[a-z][a-z0-9_-]{0,63}$(?![\\s\\S])'}},
                             'required': ['family_id'],
                             'additionalProperties': False},
 'portable_family_list': {'type': 'object',
                          'properties': {'limit': {'type': 'integer',
                                                   'minimum': 1,
                                                   'maximum': 50,
                                                   'default': 20},
                                         'after': {'type': 'integer', 'minimum': 0, 'default': 0}},
                          'required': [],
                          'additionalProperties': False},
 'portable_execute': {'type': 'object',
                      'properties': {'family_id': {'type': 'string',
                                                   'pattern': '^[a-z][a-z0-9_-]{0,63}$(?![\\s\\S])'},
                                     'expected_generation': {'type': 'integer', 'minimum': 0},
                                     'device': {'type': 'string',
                                                'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'},
                                     'task_id': {'type': 'string',
                                                 'pattern': '^ptask_[0-9a-f]{32}$(?![\\s\\S])'},
                                     'return_image': {'type': 'boolean', 'default': False}},
                      'required': ['family_id', 'expected_generation', 'device', 'task_id'],
                      'additionalProperties': False},
 'portable_task_inspect': {'type': 'object',
                           'properties': {'task_id': {'type': 'string',
                                                      'pattern': '^ptask_[0-9a-f]{32}$(?![\\s\\S])'},
                                          'return_image': {'type': 'boolean', 'default': False}},
                           'required': ['task_id'],
                           'additionalProperties': False},
 'portable_run_inspect': {'type': 'object',
                          'properties': {'run_id': {'type': 'string',
                                                    'pattern': '^prun_[0-9a-f]{32}$(?![\\s\\S])'},
                                         'return_image': {'type': 'boolean', 'default': False}},
                          'required': ['run_id'],
                          'additionalProperties': False},
 'portable_task_list': {'type': 'object',
                        'properties': {'limit': {'type': 'integer',
                                                 'minimum': 1,
                                                 'maximum': 50,
                                                 'default': 20},
                                       'after': {'type': 'integer', 'minimum': 0, 'default': 0},
                                       'device': {'anyOf': [{'type': 'string',
                                                             'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'},
                                                            {'type': 'null'}],
                                                  'default': None}},
                        'required': [],
                        'additionalProperties': False},
 'portable_batch_execute': {'type': 'object',
                            'properties': {'batch_id': {'type': 'string',
                                                        'pattern': '^batch_[0-9a-f]{32}$(?![\\s\\S])'},
                                           'family_id': {'type': 'string',
                                                         'pattern': '^[a-z][a-z0-9_-]{0,63}$(?![\\s\\S])'},
                                           'expected_generation': {'type': 'integer', 'minimum': 0},
                                           'devices': {'type': 'array',
                                                       'items': {'type': 'string',
                                                                 'pattern': '^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\\s\\S])'},
                                                       'minItems': 1,
                                                       'maxItems': 16,
                                                       'uniqueItems': True},
                                           'max_concurrency': {'type': 'integer',
                                                               'minimum': 1,
                                                               'maximum': 4,
                                                               'default': 2}},
                            'required': ['batch_id', 'family_id', 'expected_generation', 'devices'],
                            'additionalProperties': False},
 'portable_batch_inspect': {'type': 'object',
                            'properties': {'batch_id': {'type': 'string',
                                                        'pattern': '^batch_[0-9a-f]{32}$(?![\\s\\S])'}},
                            'required': ['batch_id'],
                            'additionalProperties': False},
 'portable_batch_list': {'type': 'object',
                         'properties': {'limit': {'type': 'integer',
                                                  'minimum': 1,
                                                  'maximum': 50,
                                                  'default': 20},
                                        'after': {'type': 'integer', 'minimum': 0, 'default': 0}},
                         'required': [],
                         'additionalProperties': False}}

def _normalize(schema,value):
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                return _normalize(branch,value)
            except ValueError:
                pass
        raise ValueError("Invalid union")
    if "const" in schema and (type(value)!=type(schema["const"]) or value!=schema["const"]):
        raise ValueError("Invalid literal")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Invalid enumeration")
    kind=schema.get("type")
    if kind=="object" or "properties" in schema:
        props=schema.get("properties",{})
        if type(value) is not dict or set(schema.get("required",[]))-value.keys() or (
                schema.get("additionalProperties") is False and value.keys()-props.keys()):
            raise ValueError("Invalid object fields")
        value={key:_normalize(props[key],item) if key in props else item for key,item in value.items()}
        for key,rule in props.items():
            if key not in value and "default" in rule:
                value[key]=_normalize(rule,rule["default"])
        for branch in schema.get("allOf",[]):
            try:
                _normalize(branch["if"],value)
            except ValueError:
                continue
            _normalize(branch["then"],value)
    elif kind=="string":
        if not isinstance(value,str) or not schema.get("minLength",0)<=len(value)<=schema.get("maxLength",len(value)):
            raise ValueError("Invalid string")
        if "pattern" in schema and re.fullmatch(schema["pattern"],value) is None:
            raise ValueError("Invalid string pattern")
    elif kind=="integer":
        if type(value) not in (int,float) or not math.isfinite(value) or int(value)!=value:
            raise ValueError("Invalid integer")
        if not schema.get("minimum",value)<=value<=schema.get("maximum",value):
            raise ValueError("Integer outside range")
        value=int(value)
    elif kind=="boolean":
        if type(value) is not bool:
            raise ValueError("Invalid boolean")
    elif kind=="null":
        if value is not None:
            raise ValueError("Expected null")
    elif kind=="array":
        if type(value) is not list or not schema.get("minItems",0)<=len(value)<=schema.get("maxItems",len(value)):
            raise ValueError("Invalid array")
        value=[_normalize(schema["items"],item) for item in value]
        if schema.get("uniqueItems") and len(set(value))!=len(value):
            raise ValueError("Duplicate item")
    return value

def normalize(operation,request):
    try:
        return _normalize(CATALOG[operation],request)
    except (ValueError,TypeError,OverflowError) as exc:
        raise OperationError("INVALID_ARGUMENT","Invalid request shape",exit_code=2) from exc
