import time
import pytest
from app.handlers.batch import SESSION_TTL, _expired, menu
from app.handlers.start import _join_signature
from app.services.delivery import _minutes, _notice, DEFAULT_NOTICE


@pytest.mark.asyncio
async def test_batch_session_expires_after_200_seconds():
    assert await _expired({"status": "collecting", "last_activity_ts": time.time() - SESSION_TTL - 1})


@pytest.mark.asyncio
async def test_generating_batch_is_not_expired_mid_generation():
    assert not await _expired({"status": "generating", "last_activity_ts": 0})


def test_batch_menu_exposes_generate_cancel_and_back():
    labels = [button.text for row in menu().inline_keyboard for button in row]
    assert labels == ["GENERATE LINK", "CANCEL", "BACK"]


def test_force_join_signature_is_order_independent_but_configuration_sensitive():
    assert _join_signature(["@one", "@two"]) == _join_signature(["@two", "@one"])
    assert _join_signature(["@one", "@two"]) != _join_signature(["@one", "@three"])


def test_blueprint_auto_delete_cycles_and_labels():
    expected = (2, 5, 15, 30, 60, 180, 360, 720, 1440)
    for minutes in expected:
        assert _minutes({"minutes": minutes}) == minutes
    assert _minutes({"minutes": 7}) == 30


def test_notice_uses_readable_timer_label():
    assert _notice({"notice": DEFAULT_NOTICE, "minutes": 60}, 60) == "Your files will be automatically deleted after 1 hour."
    assert _notice({"notice": DEFAULT_NOTICE, "minutes": 180}, 180) == "Your files will be automatically deleted after 3 hours."
