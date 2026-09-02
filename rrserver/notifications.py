from __future__ import annotations

import json
import threading
from typing import Any

from flask_sock import Sock
from simple_websocket import ConnectionClosed

from .auth import current_account

RECORD_SEPARATOR = "\x1e"
_connections: dict[int, set[Any]] = {}
_connections_lock = threading.Lock()


def signalr_frame(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":")) + RECORD_SEPARATOR


def signalr_reply(message: dict[str, Any]) -> str | None:
    message_type = message.get("type")
    if message_type == 6:
        return signalr_frame({"type": 6})
    if message_type != 1:
        return None

    invocation_id = message.get("invocationId")
    if invocation_id is None:
        return None

    completion: dict[str, Any] = {"type": 3, "invocationId": str(invocation_id)}
    if message.get("target") == "GetSubscriptions":
        completion["result"] = []
    return signalr_frame(completion)


def notification_frame(notification_type: str | int, data: dict[str, Any]) -> str:
    payload = json.dumps(
        {"Id": str(notification_type), "Msg": {k: v for k, v in data.items() if v is not None}},
        separators=(",", ":"),
    )
    return signalr_frame({"type": 1, "target": "Notification", "arguments": [payload]})


def notify_player(player_id: int, notification_type: str | int, data: dict[str, Any]) -> int:
    with _connections_lock:
        sockets = list(_connections.get(player_id, set()))
    delivered = 0
    for ws in sockets:
        try:
            ws.send(notification_frame(notification_type, data))
            delivered += 1
        except ConnectionClosed:
            with _connections_lock:
                _connections.get(player_id, set()).discard(ws)
    return delivered


def notify_all(notification_type: str | int, data: dict[str, Any]) -> int:
    with _connections_lock:
        player_ids = list(_connections)
    return sum(notify_player(player_id, notification_type, data) for player_id in player_ids)


def register_notification_hub(sock: Sock) -> None:
    @sock.route("/hub/v1")
    def notification_hub(ws):
        account = current_account()
        player_id = account.id if account else None
        handshake_done = False
        try:
            while True:
                incoming = ws.receive()
                if incoming is None:
                    return
                if isinstance(incoming, bytes):
                    incoming = incoming.decode("utf-8", errors="replace")

                for record in incoming.split(RECORD_SEPARATOR):
                    if not record:
                        continue
                    try:
                        message = json.loads(record)
                    except json.JSONDecodeError:
                        continue

                    if not handshake_done:
                        if message.get("protocol", "json") != "json":
                            ws.send(signalr_frame({"error": "Only the JSON protocol is supported"}))
                            ws.close(reason=1002, message="unsupported protocol")
                            return
                        ws.send(signalr_frame({}))
                        ws.send(signalr_frame({"type": 1, "target": "OnConnect", "arguments": []}))
                        handshake_done = True
                        if player_id is not None:
                            with _connections_lock:
                                _connections.setdefault(player_id, set()).add(ws)
                        continue

                    reply = signalr_reply(message)
                    if reply is not None:
                        ws.send(reply)
        except ConnectionClosed:
            return
        finally:
            if player_id is not None:
                with _connections_lock:
                    _connections.get(player_id, set()).discard(ws)
