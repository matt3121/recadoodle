import json

from rrserver.notifications import RECORD_SEPARATOR, signalr_frame, signalr_reply


def decoded(frame: str) -> dict:
    assert frame.endswith(RECORD_SEPARATOR)
    return json.loads(frame.removesuffix(RECORD_SEPARATOR))


def test_signalr_ping_reply():
    assert decoded(signalr_reply({"type": 6})) == {"type": 6}


def test_signalr_get_subscriptions_completion():
    reply = signalr_reply(
        {"type": 1, "invocationId": "7", "target": "GetSubscriptions", "arguments": []}
    )
    assert decoded(reply) == {"type": 3, "invocationId": "7", "result": []}


def test_signalr_fire_and_forget_has_no_reply():
    assert signalr_reply({"type": 1, "target": "SubscribeToPlayers", "arguments": [[]]}) is None
    assert signalr_frame({}) == "{}" + RECORD_SEPARATOR
