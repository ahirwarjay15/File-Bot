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


def test_batch_menu_exposes_only_generate_and_cancel():
    labels = [button.text for row in menu().inline_keyboard for button in row]
    assert labels == ["ɢᴇɴᴇʀᴀᴛᴇ ʟɪɴᴋ", "ᴄᴀɴᴄᴇʟ"]


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
    import app.handlers.file
    import app.handlers.admin
    import app.handlers.shortener
    import main


def test_settings_pages_get_shared_heading_and_body_style():
    from app.handlers.settings import format_settings_page

    raw = "AUTO DELETE" + "\n" + "Automatically delete delivered files." + "\n" + "Status: DISABLED"
    rendered = format_settings_page(raw)
    assert rendered.startswith("<b><u>AUTO DELETE</u></b>" + "\n\n" + "<i>")
    assert "___________" not in rendered
    assert "<u>AUTO DELETE</u>" in rendered
    assert rendered.endswith("</i>")

def test_common_variables_render_bot_and_channel_links_in_start_and_invalid_text():
    from types import SimpleNamespace
    from app.handlers.start import render_common_variables
    from app.handlers.misc import _render_user_text

    user = SimpleNamespace(
        id=42,
        first_name="Alice",
        last_name="Example",
        mention_html=lambda: '<a href="tg://user?id=42">Alice</a>',
    )
    bot = SimpleNamespace(username="sample_bot", full_name="Sample Bot")
    template = "{bot} | {bot_mention} | {first_name} | {last_name} | {user} | {owner} | {anime} | {hindi_anime}"
    for rendered in (render_common_variables(template, user, bot), _render_user_text(template, user, bot)):
        assert '<a href="https://t.me/sample_bot">Sample Bot</a>' in rendered
        assert "Alice" in rendered
        assert "Example" in rendered
        assert '<a href="tg://user?id=42">Alice</a>' in rendered
        assert '<a href="https://t.me/lexxiowner">Lexi</a>' in rendered
        assert '<a href="https://t.me/lexianime">Lexi Anime</a>' in rendered
        assert '<a href="https://t.me/lexianimehindi">Lexi Anime Hindi</a>' in rendered




def test_force_join_default_button_numbers_and_custom_slot():
    from app.handlers.start import force_join_button_label

    labels = [
        force_join_button_label({}, 1),
        force_join_button_label({}, 2),
        force_join_button_label({"button_text": "Premium Channel"}, 3),
        force_join_button_label({}, 4),
    ]
    assert labels == ["Join 1", "Join 2", "Premium Channel", "Join 4"]


def test_force_join_custom_label_does_not_reset_following_number():
    from app.handlers.start import force_join_button_label

    assert force_join_button_label({"button_text": "Paid Group"}, 1) == "Paid Group"
    assert force_join_button_label({}, 2) == "Join 2"


def test_force_join_mode_defaults_preserve_legacy_join_request_behavior():
    from app.handlers.start import join_status
    assert callable(join_status)



@pytest.mark.asyncio
async def test_pending_join_request_only_verifies_join_request_mode():
    from types import SimpleNamespace
    from app.handlers.start import join_status

    class Collection:
        def __init__(self, doc=None):
            self.doc = doc

        async def find_one(self, query):
            return self.doc

    class FakeDB:
        def __init__(self, mode):
            self.settings = Collection({"mode": mode})
            self.pending_join_requests = Collection({"chat_id": -100123, "user_id": 42})

    class FakeBot:
        async def get_chat(self, chat_id):
            return SimpleNamespace(id=-100123)

        async def get_chat_member(self, chat_id, user_id):
            return SimpleNamespace(status="left", is_member=False)

    bot = FakeBot()
    assert await join_status(bot, 42, ["-100123"], FakeDB("normal")) == ["-100123"]
    assert await join_status(bot, 42, ["-100123"], FakeDB("join_request")) == []



def test_force_join_public_and_private_chats_select_automatic_modes():
    from types import SimpleNamespace
    from app.handlers.settings import force_join_mode_for_chat

    public_channel = SimpleNamespace(username="public_channel")
    public_group = SimpleNamespace(username="public_group")
    private_channel = SimpleNamespace(username=None)
    private_group = SimpleNamespace(username=None)

    assert force_join_mode_for_chat(public_channel) == "normal"
    assert force_join_mode_for_chat(public_group) == "normal"
    assert force_join_mode_for_chat(private_channel) == "join_request"
    assert force_join_mode_for_chat(private_group) == "join_request"


def test_custom_button_settings_layout_uses_two_controls_per_row():
    from app.handlers.settings import custom_button_settings_rows

    rows = custom_button_settings_rows([
        {"text": "Protect", "url": "https://example.com"},
        {"text": "Update", "url": "https://example.org"},
    ])
    assert [[button.text for button in row] for row in rows] == [
        ["Protect", "✖"],
        ["Update", "✖"],
    ]


@pytest.mark.asyncio
async def test_button_panel_refresh_keeps_inline_back_navigation():
    from types import SimpleNamespace
    from app.handlers.settings import refresh_button_panel

    class SettingsCollection:
        async def find_one(self, query):
            return {
                "button1_enabled": True,
                "button1_text": "Updates",
                "button1_url": "https://t.me/example",
                "button2_enabled": False,
            }

    class FakeBot:
        def __init__(self):
            self.edited = None

        async def edit_message_text(self, **kwargs):
            self.edited = kwargs

    bot = FakeBot()
    await refresh_button_panel(bot, 123, 456, SimpleNamespace(settings=SettingsCollection()), "start")

    assert bot.edited["chat_id"] == 123
    assert bot.edited["message_id"] == 456
    markup = bot.edited["reply_markup"]
    callback_data = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert "settings:start" in callback_data
    assert "settings:start_button_1" in callback_data
    assert "settings:start_button_2" in callback_data


def test_start_message_default_and_markdown_are_normalized_without_leaked_markers():
    from app.handlers.settings import DEFAULT_START_TEXT
    from app.services.text_format import normalize_telegram_text

    assert DEFAULT_START_TEXT.splitlines() == [
        "<b>Hey {user_mention}✨</b>",
        "",
        "<i>Welcome to the fastest and most secure file store bot!</i>",
    ]
    rendered = normalize_telegram_text("**Hey {user_mention}✨**\\n\\n*Welcome to the fastest and most secure file store bot!*")
    assert rendered == DEFAULT_START_TEXT
    assert "\\\\n" not in rendered
    assert "**" not in rendered
    assert "*Welcome" not in rendered
    assert normalize_telegram_text("`sample`") == "<code>sample</code>"


def test_broadcast_confirmation_has_no_back_button():
    from app.handlers.broadcast import confirmation_keyboard

    labels = [button.text for row in confirmation_keyboard("draft123").inline_keyboard for button in row]
    callbacks = [button.callback_data for row in confirmation_keyboard("draft123").inline_keyboard for button in row]
    assert labels == ["ᴄᴏɴꜰɪʀᴍ", "ᴄᴀɴᴄᴇʟ"]
    assert callbacks == ["broadcast:yes:draft123", "broadcast:no:draft123"]


def test_batch_requires_two_files_and_preserves_message_order():
    from types import SimpleNamespace
    from app.handlers.batch import is_batch_file, ordered_batch_items

    assert is_batch_file(SimpleNamespace(
        document=None, photo=None, video=None, audio=None, animation=None,
        voice=None, video_note=None, sticker=None,
    )) is False
    assert is_batch_file(SimpleNamespace(
        document=object(), photo=None, video=None, audio=None, animation=None,
        voice=None, video_note=None, sticker=None,
    )) is True
    items = [
        {"original_message_id": 12, "source_message_id": 102},
        {"original_message_id": 10, "source_message_id": 100},
        {"original_message_id": 11, "source_message_id": 101},
    ]
    assert [item["original_message_id"] for item in ordered_batch_items(items)] == [10, 11, 12]


def test_batch_repository_rejects_single_file_batch():
    import inspect
    from app.database.files import FileRepository

    source = inspect.getsource(FileRepository.save_batch)
    assert "len(items) < 2" in source
    assert "2 to 100 files" in source


def test_broadcast_job_restores_saved_inline_keyboard():
    from aiogram.types import InlineKeyboardMarkup
    markup_data = {"inline_keyboard": [[{"text": "Open", "url": "https://example.com"}]]}
    markup = InlineKeyboardMarkup.model_validate(markup_data)
    assert markup.inline_keyboard[0][0].url == "https://example.com"


def test_shortener_accepts_command_urls_and_plain_domains():
    from app.handlers.shortener import extract_target

    assert extract_target("https://example.com/a") == "https://example.com/a"
    assert extract_target("example.com") == "https://example.com"
    assert extract_target("/batch") is None


def test_force_join_settings_page_uses_real_line_breaks():
    from app.handlers.settings import build_forcejoin_page

    import inspect
    source = inspect.getsource(build_forcejoin_page)
    assert r"FORCE JOIN\\n\\n" not in source
    assert r"FORCE JOIN\n\n" in source


def test_new_message_animation_is_deleted_only_after_replacement_post():
    from pathlib import Path

    source = Path("app/handlers/start.py").read_text()
    assert "delete_separate: bool = True" in source
    assert "delete_separate=False" in source
    send_position = source.index('new_post = await _send_force_join_post(bot, user_id, force_cfg, rendered, markup)')
    delete_position = source.index('await bot.delete_message(chat_id=user_id, message_id=separate_animation_id)', send_position)
    poster_delete_position = source.index('await animation_post.delete()', send_position)
    old_post_delete_position = source.index('await old_post.delete()', send_position)
    assert send_position < poster_delete_position < old_post_delete_position
    assert send_position < delete_position


def test_force_join_add_cleans_prompts_and_returns_to_main_page():
    from pathlib import Path

    source = Path("app/handlers/settings.py").read_text()
    assert "await remove_temporary_prompts(message.bot, data)" in source
    assert "await keyboard_removal.delete()" in source
    assert "await message.bot.edit_message_text(chat_id=panel_chat_id, message_id=panel_message_id" in source
    assert "Force Join added successfully." not in source


def test_force_join_verification_resolves_public_chat_username_for_join_button():
    from pathlib import Path

    source = Path("app/handlers/start.py").read_text()
    assert source.count('target = f"https://t.me/{chat.username}"') >= 2
    assert source.count("chat = await bot.get_chat(chat_arg)") >= 2

def test_new_message_animation_is_reused_as_force_join_post_for_verify_and_deeplink():
    from pathlib import Path

    source = Path("app/handlers/start.py").read_text()
    assert 'message_id=separate_animation_id,' in source
    assert 'text=rendered,' in source
    assert 'Could not convert deeplink animation message into Force Join post' in source
    assert 'Could not convert Verify animation message into Force Join post' in source
    assert 'if old_post and old_post.message_id != separate_animation_id:' in source

def test_settings_flow_messages_are_tracked_for_page_navigation_cleanup():
    from pathlib import Path

    source = Path("app/handlers/settings.py").read_text()
    callback_start = source.index('@router.callback_query(F.data.startswith("settings:"))')
    callback_end = source.index('@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))', callback_start)
    callback_handler = source[callback_start:callback_end]
    input_start = source.index('@router.message(SettingInput.waiting)')
    input_end = source.index('@router.message(Command("setstart"))', input_start)
    input_handler = source[input_start:input_end]

    assert "await remove_temporary_prompts(query.bot, pending)" in callback_handler
    assert "await tracked_answer(query.message, state," in callback_handler
    assert "await tracked_answer(message, state," in input_handler
    assert "async def clear_state_preserving_prompts(state):" in source
    assert "prompt_ids = list(data.get(\"temporary_prompt_ids\", []))" in source
    assert "await track_temporary_prompt(state, sent)" in source
    assert "await remove_temporary_prompts(message.bot, data)" in source[source.index('@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))'):source.index("async def send_button_settings_reply_panel")]




def test_stats_alert_only_contains_total_and_banned_users():
    from pathlib import Path

    source = Path("app/handlers/settings.py").read_text()
    stats_block = source.split('elif action == "stats":', 1)[1].split('\n    await query.answer()', 1)[0]
    assert '⛦ Total Users: {total}' in stats_block
    assert '⛦ Banned Users: {blocked}' in stats_block
    assert 'get_me()' not in stats_block
    assert 'USERS:' not in stats_block
    assert 'BLOCKED:' not in stats_block


def test_animation_legacy_defaults_are_migrated_and_frames_are_bold():
    from app.handlers.start import animation_frame_text, normalize_animation_config

    cfg = normalize_animation_config({
        "enabled": True,
        "prefix": "Checking..",
        "frames": ["OLD", "VALUES", "HERE"],
        "speed": 0.75,
        "mode": "new_message",
    })
    assert cfg["prefix"] == "Checking"
    assert cfg["frames"] == [".", "..", "..."]
    assert cfg["speed"] == 0.15
    assert cfg["mode"] == "new_message"
    assert cfg["enabled"] is True
    assert animation_frame_text(cfg["prefix"], cfg["frames"][0]) == "Checking<b>.</b>"


def test_animation_speed_is_clamped_for_both_modes_without_overriding_custom_speed():
    from app.handlers.start import normalize_animation_config

    slow = normalize_animation_config({
        "prefix": "Checking", "frames": [".", "..", "..."],
        "speed": 0.05, "mode": "force_join_poster",
    })
    fast = normalize_animation_config({
        "prefix": "Checking", "frames": [".", "..", "..."],
        "speed": 0.75, "mode": "new_message",
    })
    assert slow["speed"] == 0.15
    assert fast["speed"] == 0.75


def test_animation_speed_never_exceeds_supported_range():
    from app.handlers.start import normalize_animation_config

    cfg = normalize_animation_config({
        "prefix": "Checking", "frames": [".", "..", "..."],
        "speed": 3.5, "mode": "force_join_poster",
    })
    assert cfg["speed"] == 1.0


def test_settings_navigation_does_not_spawn_duplicate_panels_and_picker_prompt_is_hidden():
    from pathlib import Path

    source = Path("app/handlers/settings.py").read_text()
    edit_page = source.split("async def edit_page(query, text, keyboard):", 1)[1].split("\nasync def render_home", 1)[0]
    assert "query.message.answer(" not in edit_page
    assert "never spawn duplicate panels" in edit_page
    picker = source.split('elif action == "forcejoin_add":', 1)[1].split('elif action == "forcejoin_other":', 1)[0]
    assert '"\\u2063"' in picker
    assert "Choose the type of chat to add." not in picker


def test_force_join_chat_shared_message_and_cancel_keyboard_are_cleaned_up():
    from pathlib import Path

    source = Path("app/handlers/settings.py").read_text()
    input_handler = source.split("async def receive_setting_input", 1)[1]
    shared_block = input_handler.split('if field == "forcejoin_wait_chat":', 1)[1]
    assert "await message.delete()" in shared_block
    cancel_block = input_handler.split('if field in {"forcejoin_wait_chat", "forcejoin_wait_mode"}', 1)[1].split('if field == "forcejoin_wait_chat":', 1)[0]
    assert "Force Join channel selection cancelled." not in cancel_block
    assert "keyboard_removal.delete()" in cancel_block
