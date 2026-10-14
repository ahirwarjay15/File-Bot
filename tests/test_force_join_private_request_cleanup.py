from types import SimpleNamespace

import pytest

from app.handlers.start import _is_private_chat, clear_accepted_private_join_request


@pytest.mark.parametrize(
    ("chat_type", "username", "expected"),
    [
        ("channel", None, True),
        ("supergroup", None, True),
        ("group", None, True),
        ("channel", "public_channel", False),
        ("supergroup", "public_group", False),
        ("private", None, False),
    ],
)
def test_is_private_chat(chat_type, username, expected):
    chat = SimpleNamespace(type=chat_type, username=username)
    assert _is_private_chat(chat) is expected


class FakePendingRequests:
    def __init__(self):
        self.deleted = []

    async def delete_one(self, query):
        self.deleted.append(query)


@pytest.mark.asyncio
async def test_accepted_private_supergroup_request_is_removed():
    pending = FakePendingRequests()
    database = SimpleNamespace(db=SimpleNamespace(pending_join_requests=pending))
    event = SimpleNamespace(
        chat=SimpleNamespace(id=-100123, type="supergroup", username=None),
        old_chat_member=SimpleNamespace(status="left", user=SimpleNamespace(id=42)),
        new_chat_member=SimpleNamespace(status="member", user=SimpleNamespace(id=42)),
    )

    await clear_accepted_private_join_request(event, database)

    assert pending.deleted == [{"chat_id": -100123, "user_id": 42}]


@pytest.mark.asyncio
async def test_public_group_membership_does_not_clear_private_request_record():
    pending = FakePendingRequests()
    database = SimpleNamespace(db=SimpleNamespace(pending_join_requests=pending))
    event = SimpleNamespace(
        chat=SimpleNamespace(id=-100123, type="supergroup", username="public_group"),
        old_chat_member=SimpleNamespace(status="left", user=SimpleNamespace(id=42)),
        new_chat_member=SimpleNamespace(status="member", user=SimpleNamespace(id=42)),
    )

    await clear_accepted_private_join_request(event, database)

    assert pending.deleted == []


@pytest.mark.asyncio
async def test_membership_loss_does_not_count_as_request_acceptance():
    pending = FakePendingRequests()
    database = SimpleNamespace(db=SimpleNamespace(pending_join_requests=pending))
    event = SimpleNamespace(
        chat=SimpleNamespace(id=-100123, type="supergroup", username=None),
        old_chat_member=SimpleNamespace(status="member", user=SimpleNamespace(id=42)),
        new_chat_member=SimpleNamespace(status="left", user=SimpleNamespace(id=42)),
    )

    await clear_accepted_private_join_request(event, database)

    assert pending.deleted == []
