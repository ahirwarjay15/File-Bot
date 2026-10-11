import time
import pytest
from app.handlers.batch import SESSION_TTL, _expired, menu
from app.handlers.start import _join_signature
from app.services.delivery import _minutes, _notice, DEFAULT_NOTICE
from app.handlers.settings import time_label, time_words


@pytest.mark.asyncio
async def test_batch_session_expires_after_200_seconds():
    assert await _expired({"status": "collecting", "last_activity_ts": time.time() - SESSION_TTL - 1})


@pytest.mark.asyncio
async def test_generating_batch_is_not_expired_mid_generation():
    assert not await _expired({"status": "generating", "last_activity_ts": 0})


def test_batch_menu_exposes_generate_cancel_and_back():
    labels = [button.text for row in menu().inline_keyboard for button in row]
    assert labels == ["ɢᴇɴᴇʀᴀᴛᴇ ʟɪɴᴋ", "ᴄᴀɴᴄᴇʟ", "《 BACK"]


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


def test_blueprint_timer_display_labels():
    assert [time_label(m) for m in (2, 5, 15, 30, 60, 180, 360, 720, 1440)] == [
        "2m", "5m", "15m", "30m", "1h", "3h", "6h", "12h", "24h"
    ]
    assert time_words(60) == "1 hour"
    assert time_words(1440) == "24 hours"


def test_animation_mode_buttons_persist_distinct_modes():
    from app.handlers.settings import _animation_mode_for_action

    assert _animation_mode_for_action("animation_mode_new") == "new_message"
    assert _animation_mode_for_action("animation_mode_poster") == "force_join_poster"


def test_settings_buttons_use_small_caps_with_required_exceptions():
    from app.handlers.settings import unicode_buttons

    assert unicode_buttons("START TEXT") == "ꜱᴛᴀʀᴛ ᴛᴇxᴛ"
    assert unicode_buttons("《 BACK") == "《 BACK"
    assert unicode_buttons("📟 UPDATE CHANNEL") == "📟 UPDATE CHANNEL"


def test_invalid_post_about_defaults_to_multiline_standard_about():
    from app.handlers.misc import DEFAULT_ABOUT

    assert "\\n" not in DEFAULT_ABOUT
    assert "\n" in DEFAULT_ABOUT
    assert "{bot_name}" in DEFAULT_ABOUT


def test_invalid_post_template_replaces_user_variables_safely():
    from types import SimpleNamespace
    from app.handlers.misc import _render_user_text

    user = SimpleNamespace(id=42, first_name="A&B", last_name="User")
    rendered = _render_user_text("Hi {mention} / {first_name} / {last_name}", user)
    assert 'tg://user?id=42' in rendered
    assert "A&amp;B" in rendered
    assert "User" in rendered


def test_all_runtime_handlers_import_cleanly():
    import app.handlers.start
    import app.handlers.misc
    import app.handlers.broadcast
    import app.handlers.settings
    import app.services.delivery


def test_settings_pages_get_shared_heading_and_body_style():
    from app.handlers.settings import format_settings_page

    rendered = format_settings_page("AUTO DELETE\nAutomatically delete delivered files.\nStatus: DISABLED")
    assert rendered.startswith("<b><u>AUTO DELETE</u></b>\n\n<i>")
    assert rendered.endswith("</i>")
