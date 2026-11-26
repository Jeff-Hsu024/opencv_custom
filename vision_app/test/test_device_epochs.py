import sqlite3
from contextlib import closing
from dataclasses import replace

import numpy as np
import pytest

from service.core.opencv.dto import MatchResult
from vision_app.actions import ActionService
from vision_app.assets import RefRegistry, _map_match_to_ref
from vision_app.coordinator import Claim, ClaimError
from vision_app.epochs import ActionIntent, DeviceEpochs, RefEpoch
from vision_app.observation import ObservationService, OperationError
from vision_app.store import FrameStore
from vision_app.test.test_coordinator import worker


ACTION = "act_" + "a" * 32


class Platform:
    def __init__(self):
        self.clicks = []

    def snapshot(self):
        return np.zeros((16, 16, 3), dtype=np.uint8)

    def click(self, x, y):
        self.clicks.append((x, y))
        return True

    def swipe(self, *args, **kwargs):
        return True

    def type_text(self, text):
        return False

    def key_event(self, key):
        raise TimeoutError("input outcome unknown")


def make_ref(store, frame_id, session_id=None):
    frame = store.get_frame(frame_id)
    match = MatchResult(bbox=(1, 1, 3, 3), center=(2, 2), score=1.0)
    return RefRegistry(store.store_dir).save(_map_match_to_ref(frame, "target", match), session_id=session_id)


def claim_for(ref):
    return Claim(ACTION, "guarded_click", {"ref_id": ref.ref_id, "device": "A"},
                 {"action_outcome": "not_attempted", "last_frame_id": ref.frame_id}, "A")


def test_intervening_raw_input_invalidates_young_ref_and_preserves_device_isolation(tmp_path):
    store = FrameStore(tmp_path)
    epochs = DeviceEpochs(store)
    platform = Platform()
    observation = ObservationService(store, platform_factory=lambda _: platform)
    actions = ActionService(store, platform_factory=lambda _: platform)
    with epochs.device_owner("A") as owner:
        original = observation.snapshot("A", device_owner=owner)["frame"]["frame_id"]
    old_ref = make_ref(store, original, "ses_one")
    with epochs.device_owner("B") as owner:
        other = observation.snapshot("B", device_owner=owner)["frame"]["frame_id"]
    assert actions.swipe("A", start=(1, 1), end=(3, 3))["status"] == "executed"
    assert epochs.current("A") == 1
    assert epochs.current("B") == epochs.frame_epoch(other, "B") == 0

    for operation, code in [(lambda: actions.type_text("A", text="test"), "ACTION_FAILED"),
                            (lambda: actions.press_key("A", key="BACK"), "ACTION_TIMEOUT")]:
        with pytest.raises(OperationError) as error:
            operation()
        assert error.value.code == code
    assert epochs.current("A") == 3
    with pytest.raises(OperationError) as error:
        actions.click("A", ref_id=old_ref.ref_id, session_id="ses_one", max_age_seconds=15)
    assert error.value.code == "STALE_REF_EPOCH"
    assert epochs.current("A") == 3
    assert platform.clicks == []

    cropped = observation.crop(original, (0, 0, 8, 8))["frame"]["frame_id"]
    resized = observation.resize(cropped, .5)["frame"]["frame_id"]
    assert epochs.frame_epoch(resized, "A") == 0
    derived_ref = make_ref(store, resized)
    assert epochs.ref_epoch(derived_ref.ref_id) == RefEpoch("A", 0, None)
    assert RefRegistry(tmp_path).get(old_ref.ref_id) == old_ref
    with pytest.raises(ClaimError, match="ID_RESERVED"):
        RefRegistry(tmp_path).save(replace(old_ref, target="replacement"))

    with epochs.request_owner(ACTION) as request:
        with epochs.device_owner("A") as owner:
            fresh = observation.snapshot("A", device_owner=owner)["frame"]["frame_id"]
        ref = make_ref(store, fresh, "ses_one")
        epochs.admit(request, claim_for(ref))
        with epochs.device_owner("A") as owner:
            intent = ActionIntent(request, ACTION, "click", lambda receipt, epoch: dict(receipt, epoch=epoch))
            with pytest.raises(OperationError) as scope:
                actions.click("A", ref_id=ref.ref_id, max_age_seconds=15, device_owner=owner, intent=intent)
            assert scope.value.code == "SCOPE_MISMATCH"
            with pytest.raises(OperationError) as stale:
                actions.click("A", ref_id=old_ref.ref_id, max_age_seconds=15, device_owner=owner,
                              session_id="ses_one", intent=intent)
            assert stale.value.code == "STALE_REF_EPOCH"
            assert epochs.current("A") == 3

            click = platform.click

            def click_with_cleanup(x, y):
                captured = store.get_frame(fresh)
                removed = store.cleanup(now=captured.timestamp + store.ttl_seconds + 1)
                assert original in removed and fresh not in removed
                return click(x, y)

            platform.click = click_with_cleanup
            receipt = actions.click("A", ref_id=ref.ref_id, max_age_seconds=15, session_id="ses_one",
                                    device_owner=owner, intent=intent)
    assert receipt["status"] == "executed"
    assert platform.clicks == [(2, 2)]
    assert epochs.current("A") == 4
    assert epochs.current("B") == 0


def test_legacy_unstamped_ref_and_coordinates_keep_shape_and_advance_epoch(tmp_path):
    store = FrameStore(tmp_path)
    epochs = DeviceEpochs(store)
    platform = Platform()
    actions = ActionService(store, platform_factory=lambda _: platform)
    frame = store.save_frame(platform.snapshot(), "A")
    ref = make_ref(store, frame.frame_id)
    with epochs.request_owner(ACTION) as request:
        epochs.admit(request, claim_for(ref))
        with epochs.device_owner("A") as owner:
            intent = ActionIntent(request, ACTION, "click", lambda receipt, _: receipt)
            with pytest.raises(OperationError) as error:
                actions.click("A", ref_id=ref.ref_id, device_owner=owner, max_age_seconds=15, intent=intent)
            assert error.value.code == "REF_UNVERSIONED"
    assert epochs.current("A") == 0
    legacy = actions.click("A", ref_id=ref.ref_id)
    assert set(legacy) == {"action", "device_id", "status", "verified", "target", "source", "executed_at"}
    assert legacy["source"]["ref_id"] == ref.ref_id
    for _ in range(2):
        assert actions.click("A", frame_id=frame.frame_id, point=(1, 1))["status"] == "executed"
    assert epochs.current("A") == 3
    assert epochs.ref_epoch(ref.ref_id) is None
    assert RefRegistry(tmp_path).get(ref.ref_id) == ref


def test_pending_intent_commits_before_process_death_and_cannot_replay(tmp_path):
    store = FrameStore(tmp_path)
    epochs = DeviceEpochs(store)
    with epochs.device_owner("A") as owner:
        frame = store.save_frame(Platform().snapshot(), "A", device_owner=owner)
    ref = make_ref(store, frame.frame_id)
    with worker(tmp_path, """
from vision_app.epochs import DeviceEpochs
epochs = DeviceEpochs(sys.argv[1])
action = sys.argv[2]
frame = sys.argv[3]
with epochs.request_owner(action) as request:
    epochs.admit(request, Claim(action, "guarded_click", {"device": "A"},
                               {"last_frame_id": frame, "action_outcome": "not_attempted"}, "A"))
    with epochs.device_owner("A") as owner:
        assert epochs.begin_intent(owner, request, action, "step", lambda receipt, _: receipt) == 1
        print("ready")
        sys.stdin.readline()
""", ACTION, frame.frame_id) as process:
        with closing(sqlite3.connect(tmp_path / "coordinator.sqlite")) as db:
            assert db.execute("SELECT * FROM device_epoch").fetchall() == [("A", 1)]
            assert db.execute("SELECT * FROM action_intent").fetchall() == [(ACTION, "step", 1)]
        process.kill()
        assert process.wait(timeout=15) != 0
    reopened = DeviceEpochs(tmp_path)
    with reopened.device_owner("A", timeout=1) as owner:
        with pytest.raises(ClaimError, match="STALE_REF_EPOCH"):
            reopened.guard_ref(owner, ref.ref_id, "A")
        fresh = store.save_frame(Platform().snapshot(), "A", device_owner=owner)
        assert reopened.frame_epoch(fresh.frame_id, "A") == 1
    pending = reopened.inspect(ACTION)
    assert (pending["action_outcome"], pending["observation_phase"], pending["last_frame_id"]) == (
        "unknown", "post_action_unknown", None)
    reconciled = reopened.inspect(ACTION, lambda _, receipt: dict(receipt, status="interrupted"))
    assert reconciled["action_outcome"] == "unknown"
    with reopened.request_owner(ACTION) as request, reopened.device_owner("A") as owner:
        with pytest.raises(RuntimeError, match="running device claim"):
            reopened.begin_intent(owner, request, ACTION, "step", lambda receipt, _: receipt)
    assert reopened.current("A") == 1


def test_intent_failure_rolls_back_epoch_and_duplicate_step_cannot_advance(tmp_path):
    epochs = DeviceEpochs(tmp_path)
    claim = Claim(ACTION, "guarded_click", {"device": "A"}, {"action_outcome": "not_attempted"}, "A")
    with epochs.request_owner(ACTION) as request:
        epochs.admit(request, claim)
        with epochs.device_owner("A") as owner:
            with pytest.raises(TypeError):
                epochs.begin_intent(owner, request, ACTION, "step", lambda receipt, _: dict(receipt, bad=object()))
            assert epochs.current("A") == 0
            assert epochs.inspect(ACTION) == claim.receipt
            assert epochs.begin_intent(owner, request, ACTION, "step", lambda receipt, _: receipt) == 1
            with pytest.raises(ClaimError, match="ACTION_UNCERTAIN"):
                epochs.begin_intent(owner, request, ACTION, "next_step", lambda receipt, _: receipt)
            epochs.record(request, ACTION, dict(epochs.inspect(ACTION), action_outcome="executed_unverified"))
            with pytest.raises(ClaimError, match="ACTION_UNCERTAIN"):
                epochs.begin_intent(owner, request, ACTION, "step", lambda receipt, _: receipt)
            assert epochs.current("A") == 1
            assert epochs.begin_intent(owner, request, ACTION, "next_step", lambda receipt, _: receipt) == 2
