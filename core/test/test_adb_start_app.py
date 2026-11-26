from pathlib import Path
import sys
from unittest.mock import MagicMock

project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from service.platform.adb.adb_platform import AdbPlatform
from service.core.opencv.open_cv_service import OpenCvService


def test_start_app_uses_component_line_from_resolve_activity():
    adb = MagicMock()
    adb.device_id = "emulator-5554"
    adb.exec.side_effect = [
        "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=false\n"
        "com.bandainamcoent.gget_WW/com.unity3d.player.UnityPlayerActivity\n",
        "Starting: Intent",
    ]
    cv = MagicMock(spec=OpenCvService)
    platform = AdbPlatform(adb, cv)

    result = platform.start_app("com.bandainamcoent.gget_WW")

    assert result == "Starting: Intent"
    start_command = adb.exec.call_args_list[1][0][0]
    assert "com.bandainamcoent.gget_WW/com.unity3d.player.UnityPlayerActivity" in start_command
    assert "priority=0" not in start_command
