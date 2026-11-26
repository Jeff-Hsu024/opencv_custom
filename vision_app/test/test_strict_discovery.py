"""C01: real ADB adapter and public transports, simulated subprocess output only."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator

from service.platform.adb.adb import Adb
from service.platform.adb.adb_platform import AdbPlatform
from vision_app.cli import run_cli
from vision_app.discovery import ANDROID_DEVICES_SCHEMA, DiscoveryService
from vision_app.mcp_server import VisionMcpServer, _tool_definitions
from vision_app.observation import ObservationService, OperationError
from vision_app.store import FrameStore


HEADER = 'List of devices attached\n'
PLAN = Path(__file__).resolve().parents[2] / 'specs/agent-vision-phase9'


def services(tmp_path, monkeypatch, stdout, *, code=0, error=None):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if error:
            raise error
        return subprocess.CompletedProcess(argv, code, stdout, 'sensitive diagnostic')

    monkeypatch.setattr('service.platform.adb.adb.subprocess.run', run)
    platform = AdbPlatform(Adb(device_id='adb'), Mock())
    factory_calls = []

    def factory(device):
        factory_calls.append(device)
        return platform

    obs = ObservationService(FrameStore(tmp_path / 'store'), platform_factory=factory)
    server = VisionMcpServer(tmp_path / 'store', platform_factory=factory)
    return obs, server, calls, factory_calls, platform


@pytest.mark.parametrize('stdout,expected', [
    (HEADER, []),
    (HEADER + '\n', []),
    (HEADER + 'A\tdevice\n127.0.0.1:16480\tdevice\n', ['A', '127.0.0.1:16480']),
    (HEADER + 'device-offline\toffline\ndevice-unauthorized\tunauthorized\n', []),
    (HEADER + 'A\tdevice\ndevice-B\toffline\nC\tunauthorized\n', ['A']),
    ('List of devices attached\r\nA\tdevice\r\n', ['A']),
])
def test_actual_adapter_and_transport_parity(tmp_path, monkeypatch, capsys, stdout, expected):
    obs, server, calls, factories, _ = services(tmp_path, monkeypatch, stdout)
    request = tmp_path / 'request.json'
    request.write_text('{}', encoding='utf-8')
    assert run_cli(['phase9', 'android-devices', '--request', str(request)], service=obs) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = server.call_tool('vision_android_devices', {})
    assert cli == json.loads(mcp['content'][0]['text']) == {
        'ok': True, 'result': {'devices': [{'device_id': d, 'platform': 'adb'} for d in expected]}}
    assert not mcp['isError']
    response_schema = json.loads((PLAN / 'c00/RESPONSE_SCHEMAS.json').read_text())['operations']['android_devices']
    Draft202012Validator(response_schema).validate(cli)
    assert factories == ['adb', 'adb']
    assert len(calls) == 2
    for argv, kwargs in calls:
        assert argv[1:] == ['devices']  # no -s adb, connect, start-server, or input
        assert kwargs['shell'] is False
    # Legacy output retains desktop and its original envelope.
    assert obs.devices()[-1] == {'device_id': 'desktop', 'platform': 'desktop'}


@pytest.mark.parametrize('stdout,code,error', [
    ('', 0, None), ('garbage', 0, None), ('List of devices attached junk\n', 0, None),
    (HEADER + 'A device\n', 0, None), (HEADER + 'A\tdevice-extra\n', 0, None),
    (HEADER + 'A\tdevice\tmore\n', 0, None), (HEADER + '\tdevice\n', 0, None),
    (HEADER + 'A\tdevice\nA\tdevice\n', 0, None),
    (HEADER + 'adb\tdevice\n', 0, None), (HEADER + 'desktop\tdevice\n', 0, None),
    (HEADER + 'bad serial\tdevice\n', 0, None),
    (HEADER + 'A\tdevice\n', 1, None),
    (HEADER, 0, FileNotFoundError('secret path')),
    (HEADER, 0, subprocess.TimeoutExpired(['adb'], 30)),
])
def test_failure_never_becomes_empty_success(tmp_path, monkeypatch, capsys, stdout, code, error):
    obs, server, calls, _, _ = services(tmp_path, monkeypatch, stdout, code=code, error=error)
    request = tmp_path / 'request.json'
    request.write_text('{}')
    assert run_cli(['phase9', 'android-devices', '--request', str(request)], service=obs) == 3
    cli = json.loads(capsys.readouterr().out)
    mcp = server.call_tool('vision_android_devices', {})
    assert mcp['isError']
    assert cli == json.loads(mcp['content'][0]['text'])
    assert cli == {'ok': False, 'error': {'code': 'DISCOVERY_FAILED',
        'message': 'Android discovery failed', 'details': {}, 'retryable': True}}
    assert len(calls) == 2


@pytest.mark.parametrize('payload_in', [{'device': 'A'}, [], '', 0, False])
def test_request_validation_precedes_discovery(tmp_path, monkeypatch, capsys, payload_in):
    obs, server, calls, factories, _ = services(tmp_path, monkeypatch, HEADER)
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(payload_in))
    assert run_cli(['phase9', 'android-devices', '--request', str(path)], service=obs) == 2
    cli = json.loads(capsys.readouterr().out)
    mcp = server.call_tool('vision_android_devices', payload_in)
    assert cli == json.loads(mcp['content'][0]['text'])
    assert cli['error']['code'] == 'INVALID_ARGUMENT' and mcp['isError']
    assert calls == factories == []


@pytest.mark.parametrize('device', [None, '', 'adb', 'desktop', 'A\n', ' A', 'A ', 'A;echo', 'A'*129, False])
def test_explicit_serial_validation_precedes_io(tmp_path, monkeypatch, device):
    obs, _, calls, factories, _ = services(tmp_path, monkeypatch, HEADER)
    with pytest.raises(OperationError) as exc:
        DiscoveryService(obs).require_online(device)
    assert exc.value.code == 'INVALID_DEVICE'
    assert calls == factories == []


@pytest.mark.parametrize('device,expected', [('A', None), ('B', 'DEVICE_UNAVAILABLE'),
                                           ('device-offline', 'DEVICE_UNAVAILABLE')])
def test_exact_online_admission(tmp_path, monkeypatch, device, expected):
    obs, _, calls, _, _ = services(tmp_path, monkeypatch, HEADER + 'A\tdevice\ndevice-offline\toffline\n')
    if expected:
        with pytest.raises(OperationError) as exc:
            DiscoveryService(obs).require_online(device)
        assert exc.value.code == expected
    else:
        assert DiscoveryService(obs).require_online(device) == device
    assert len(calls) == 1


def test_core_exact_state_and_legacy_empty_failure(tmp_path, monkeypatch):
    obs, server, _, _, platform = services(tmp_path, monkeypatch,
        HEADER + 'device-offline\toffline\ndevice-unauthorized\tunauthorized\nA\tdevice\n')
    assert platform.get_devices() == ['A']
    _, server, _, _, platform = services(tmp_path, monkeypatch, HEADER, code=1)
    assert platform.get_devices() == []
    legacy = json.loads(server.call_tool('vision_devices', {})['content'][0]['text'])
    assert legacy == {'ok': True, 'devices': [{'device_id': 'desktop', 'platform': 'desktop'}]}


def test_schema_and_additive_tools():
    frozen = json.loads((PLAN / 'CONTRACT_SCHEMAS.json').read_text())['operations']['android_devices']
    assert ANDROID_DEVICES_SCHEMA == frozen
    baseline = json.loads((PLAN / 'c00/LEGACY_BASELINE.json').read_text())
    current = {tool['name']: tool for tool in _tool_definitions()}
    for tool in baseline['tools']:
        assert current[tool['name']] == tool
    assert {'vision_android_devices', 'vision_asset_revision_register',
            'vision_asset_revision_resolve'} <= current.keys()


def test_no_legacy_discovery_fallback(tmp_path, monkeypatch):
    platform = Mock(spec=['get_devices'])
    obs = ObservationService(FrameStore(tmp_path), platform_factory=lambda _: platform)
    payload, code = DiscoveryService(obs).invoke({})
    assert code == 3 and payload['error']['code'] == 'INTERNAL_ERROR'
    platform.get_devices.assert_not_called()


def test_unexpected_implementation_failure_is_internal(tmp_path):
    def broken_factory(_):
        raise RuntimeError('sensitive implementation details')
    obs = ObservationService(FrameStore(tmp_path), platform_factory=broken_factory)
    payload, code = DiscoveryService(obs).invoke({})
    assert code == 3 and payload['error']['code'] == 'INTERNAL_ERROR'
    assert 'sensitive' not in json.dumps(payload)


@pytest.mark.parametrize('content', ['null', '{', '{"device":"A"}', 'NaN'])
def test_bad_request_file(tmp_path, monkeypatch, capsys, content):
    obs, _, calls, _, _ = services(tmp_path, monkeypatch, HEADER)
    path = tmp_path / 'request.json'
    path.write_text(content)
    assert run_cli(['phase9', 'android-devices', '--request', str(path)], service=obs) == 2
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'INVALID_ARGUMENT'
    assert not calls
