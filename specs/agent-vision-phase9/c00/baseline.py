"""Read-only legacy public surface capture using a temporary store/fake platform."""
import argparse
import contextlib
import inspect
import io
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np

from vision_app.cli import _build_parser, run_cli
from vision_app.mcp_server import _tool_definitions, VisionMcpServer
from vision_app.observation import ObservationService
from vision_app.store import FrameStore


class Platform:
    def get_devices(self):
        return ['fixture-A', 'fixture-B']

    def get_capabilities(self):
        return {'platform': 'adb', 'snapshot': True, 'click': True}

    def snapshot(self):
        return np.zeros((20,30,3),dtype=np.uint8)


def capture():
    def parser_shape(parser):
        actions = []
        for action in parser._actions:
            row = dict(dest=action.dest, options=action.option_strings, required=action.required,
                       default=action.default, nargs=action.nargs,
                       type=getattr(action.type, '__name__', None))
            if isinstance(action, argparse._SubParsersAction):
                row['commands'] = {key: parser_shape(value) for key, value in action.choices.items()}
            elif action.choices is not None:
                row['choices'] = list(action.choices)
            actions.append(row)
        return actions
    with patch.dict(os.environ, {'VISION_STORE_DIR': '<store>', 'VISION_SESSION_ID': '<session>'}):
        parser = parser_shape(_build_parser())
    tools = _tool_definitions()
    with tempfile.TemporaryDirectory(prefix='vision-c00-baseline-') as directory:
        store = FrameStore(Path(directory))
        obs = ObservationService(store, platform_factory=lambda _: Platform())
        server = VisionMcpServer(store_dir=directory, platform_factory=lambda _: Platform())
        calls = {}
        for operation, argv in [('devices', ['devices', '--json']), ('assets_list', ['assets', 'list', '--json'])]:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = run_cli(['--store-dir', directory, *argv], service=obs)
            calls[operation] = dict(cli_exit=exit_code, cli=json.loads(output.getvalue()),
                                    mcp=server.call_tool('vision_' + operation, {}))
        error = server.call_tool('vision_unknown', {})
        # Freeze actual legacy image order/default and metadata-only projection.
        def stable(value):
            if isinstance(value,dict):
                return {k:('<frame_id>' if k == 'frame_id' else '<timestamp>' if k in ['timestamp','created_at'] else
                           '<path>' if k in ['path','image_path'] else stable(v)) for k,v in value.items()}
            if isinstance(value,list):
                return [stable(v) for v in value]
            return value
        snapshots={}
        for mode,args in [('default',{}),('metadata',{'return_image':False})]:
            response=server.call_tool('vision_snapshot',{'device':'fixture-A',**args})
            for content in response['content']:
                if content['type']=='text':
                    content['text']=json.dumps(stable(json.loads(content['text'])),sort_keys=True)
                elif content['type']=='image':
                    # Compression bytes can vary with OpenCV; freeze transport,
                    # decoded pixel digest/dimensions rather than codec version.
                    import base64,hashlib,cv2
                    pixels=cv2.imdecode(np.frombuffer(base64.b64decode(content.pop('data')),dtype=np.uint8),cv2.IMREAD_COLOR)
                    content['decoded_shape']=list(pixels.shape)
                    content['decoded_sha256']=hashlib.sha256(pixels.tobytes()).hexdigest()
            # PNG byte count also depends on codec implementation.
            for content in response['content']:
                if content['type']=='text':
                    payload=json.loads(content['text'])
                    if 'artifact' in payload: payload['artifact']['bytes']='<png_byte_count>'
                    content['text']=json.dumps(payload,sort_keys=True)
            snapshots[mode]=response
    return dict(tool_count=len(tools), tools=tools, cli_parser=parser, calls=calls, unknown_mcp=error, snapshots=snapshots)


if __name__ == '__main__':
    target = Path(__file__).with_name('LEGACY_BASELINE.json')
    target.write_text(json.dumps(capture(), indent=2) + '\n', encoding='utf-8')
