"""Thin encrypted Matrix transport for the durable Cogito gateway.

One process runs per Matrix identity. The MXID encodes the role — `@gateway`,
`@planner`, `@coordinator` — so the agent backing a role can be swapped without
Tim losing the sender he already recognises in his client. Only the `gateway`
role receives: it owns inbound events, room state and the typing indicator,
while the persona roles drain their own slice of the shared outbox.
"""

from datetime import datetime, timezone
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
from typing import Any

from maubot import MessageEvent, Plugin
from maubot.handlers import event
from mautrix.errors import MLimitExceeded, MNotFound, MUnknown
from mautrix.crypto.attachments import decrypt_attachment
from mautrix.types import (Event, EventID, EventType, MessageType, RelationType, RoomID,
                           TextMessageEventContent)
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("gateway_url")
        helper.copy("gateway_secret")
        helper.copy("allowed_senders")


class CogitoBot(Plugin):
    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    PINNED = EventType.find("m.room.pinned_events", EventType.Class.STATE)
    # Synapse rate-limits bursts. Pace ordinary sends and wait out the limiter
    # rather than letting one throttled write wedge the strictly ordered queue.
    SEND_PACE = 0.3
    RATE_LIMIT_ATTEMPTS = 8

    async def start(self) -> None:
        self._role = os.environ.get("COGITO_BOT_ROLE", "gateway")
        self._receives = self._role == "gateway"
        self._project_rooms = set(filter(
            None, os.environ.get("MATRIX_PROJECT_ROOM_ID", "").split(",")))
        # Rooms where a bare message is a conversation rather than noise: the
        # project rooms for planning, the implementation room for Luna.
        self._conversational_rooms = self._project_rooms | set(filter(
            None, os.environ.get("MATRIX_IMPLEMENTATION_ROOM_ID", "").split(",")))
        self._mention_users = [
            user for user in self.config["allowed_senders"] if user]
        self.log.info(
            "Matrix %s bot started (receiving=%s) for %d allowed sender(s) "
            "and %d project room(s)",
            self._role, self._receives, len(self.config["allowed_senders"]),
            len(self._project_rooms),
        )
        self._planning_typing_rooms = set()
        self._outbox_task = asyncio.create_task(self._deliver_outbox())

    async def stop(self) -> None:
        self._outbox_task.cancel()
        for room_id in self._planning_typing_rooms:
            await self.client.set_typing(RoomID(room_id), timeout=0)

    async def _request(self, path: str, value: dict) -> dict:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(
            self.config["gateway_secret"].encode(), payload, hashlib.sha256
        ).hexdigest()
        async with self.http.post(
            self.config["gateway_url"].rstrip("/") + path,
            data=payload,
            headers={"Content-Type": "application/json", "X-Cogito-Signature-256": signature},
        ) as response:
            result = await response.json()
            if response.status >= 400:
                raise RuntimeError(result.get("error", f"HTTP {response.status}"))
            return result

    async def _set_pinned(self, room_id: str, event_id: str, pinned: bool) -> str:
        """Add or remove one event in the room's pin list, preserving the rest.

        An open plan's card is pinned so it stays reachable from the room
        header once the conversation has scrolled past it.
        """
        room = RoomID(room_id)
        try:
            current = await self.client.get_state_event(room, self.PINNED)
            existing = list(getattr(current, "pinned", None) or current.get("pinned", []))
        except MNotFound:
            # No pin list yet. Any other failure must propagate rather than be
            # read as "empty", which would silently drop existing pins.
            existing = []
        existing = [str(item) for item in existing]
        if pinned and event_id not in existing:
            existing.append(event_id)
        elif not pinned and event_id in existing:
            existing.remove(event_id)
        else:
            return event_id
        await self.client.send_state_event(room, self.PINNED, {"pinned": existing})
        return event_id

    async def _deliver_outbox(self) -> None:
        while True:
            try:
                result = await self._request("/v1/matrix/outbox", {
                    "operation": "poll", "limit": 20, "sender": self._role})
                typing_rooms = set(result.get("typing_rooms", []))
                for room_id in typing_rooms:
                    # Matrix typing is room-scoped. Refresh a short lease on
                    # every poll while any planning scout or Astra synthesis
                    # for that room remains active.
                    await self.client.set_typing(RoomID(room_id), timeout=15000)
                for room_id in self._planning_typing_rooms - typing_rooms:
                    await self.client.set_typing(RoomID(room_id), timeout=0)
                self._planning_typing_rooms = typing_rooms
                for item in result.get("notifications", []):
                    kind = item.get("kind")
                    if kind in {"pin", "unpin"}:
                        # A pin is a convenience and needs power level 50 the
                        # bot may not hold. Never let one stall the messages
                        # queued behind it: log, leave it pending, move on.
                        try:
                            event_id = await self._set_pinned(
                                item["room_id"], item["target_event_id"], kind == "pin")
                        except Exception:
                            self.log.exception(
                                "could not %s %s in %s", kind,
                                item["target_event_id"], item["room_id"])
                            continue
                        await self._request("/v1/matrix/outbox", {
                            "operation": "ack", "notification_id": item["notification_id"],
                            "event_id": str(event_id),
                        })
                        continue
                    if kind == "edit":
                        def edit() -> Any:
                            content = TextMessageEventContent(
                                msgtype=MessageType.TEXT, body=item["body"])
                            content.set_edit(EventID(item["target_event_id"]))
                            return self.client.send_message_event(
                                RoomID(item["room_id"]), EventType.ROOM_MESSAGE,
                                content, txn_id=item["notification_id"],
                            )

                        event_id = await self._patiently(edit, item["notification_id"])
                        await self._request("/v1/matrix/outbox", {
                            "operation": "ack", "notification_id": item["notification_id"],
                            "event_id": str(event_id),
                        })
                        await asyncio.sleep(self.SEND_PACE)
                        continue
                    relates_to = None
                    if item.get("thread_root"):
                        relation = TextMessageEventContent(msgtype=MessageType.TEXT, body="")
                        relation.set_thread_parent(EventID(item["thread_root"]), reply_fallback=True)
                        relates_to = relation.relates_to
                    try:
                        event_id = await self._patiently(
                            lambda: self._send(item, relates_to), item["notification_id"])
                    except MUnknown as exc:
                        if "unknown event" not in str(exc).lower():
                            raise
                        # A referenced root the bot never saw must not strand the
                        # notification; deliver it at room level instead.
                        fallback = dict(
                            item, body="[Original context unavailable] " + item["body"],
                            notification_id=item["notification_id"] + "-fallback")
                        event_id = await self._patiently(
                            lambda: self._send(fallback, None), fallback["notification_id"])
                    await self._request("/v1/matrix/outbox", {
                        "operation": "ack", "notification_id": item["notification_id"],
                        "event_id": str(event_id),
                    })
                    await asyncio.sleep(self.SEND_PACE)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("gateway outbox delivery failed")
            await asyncio.sleep(5)

    @staticmethod
    def _retry_after(exc: Exception, attempt: int) -> float:
        found = re.search(r'"?retry_after_ms"?[:=]\s*(\d+)', str(exc))
        if found:
            return min(int(found.group(1)) / 1000 + 0.25, 60.0)
        return min(2.0 ** attempt, 60.0)

    async def _patiently(self, action, description: str):
        """Run one Matrix write, waiting out Synapse's rate limiter.

        Publishing a scout transcript is a burst of ~70 messages and reliably
        trips M_LIMIT_EXCEEDED. Retrying the individual write matters because
        the outbox is strictly ordered: without it the batch aborts on the same
        head item every cycle and the queue never drains again.
        """
        for attempt in range(self.RATE_LIMIT_ATTEMPTS):
            try:
                return await action()
            except MLimitExceeded as exc:
                delay = self._retry_after(exc, attempt)
                self.log.warning(
                    "rate limited delivering %s; retrying in %.1fs", description, delay)
                await asyncio.sleep(delay)
        return await action()

    async def _send(self, item: dict, relates_to) -> EventID:
        """Send one outbox message, pinging the owner when it needs a decision.

        Rooms that carry status are set to mentions-only on the phone, so a
        transition Tim has to act on only reaches him if the event itself
        carries `m.mentions`.
        """
        extra_content = None
        if item.get("mention") and self._mention_users:
            extra_content = {"m.mentions": {"user_ids": list(self._mention_users)}}
        return await self.client.send_markdown(
            RoomID(item["room_id"]), item["body"], allow_html=False,
            relates_to=relates_to, extra_content=extra_content,
            txn_id=item["notification_id"])

    @classmethod
    def get_config_class(cls):
        return Config

    @event.on(EventType.ALL)
    async def on_event(self, evt: Event) -> None:
        # A global handler receives both the encrypted envelope and the decrypted
        # message emitted by mautrix's DecryptionDispatcher. Explicitly select the
        # latter here rather than depending on maubot's per-type handler routing.
        if not self._receives:
            return
        if evt.type == EventType.REACTION:
            relation = getattr(evt.content, "relates_to", None)
            key = getattr(relation, "key", "")
            target = str(getattr(relation, "event_id", ""))
            if (evt.sender != self.client.mxid
                    and evt.sender in self.config["allowed_senders"]
                    and key in {"⏹", "⏸", "🔄", "🔍"} and target):
                await self._request("/v1/matrix/events", {
                    "event_id": str(evt.event_id), "room_id": str(evt.room_id),
                    "sender": str(evt.sender), "body": f"!cogito react {key} {target}",
                    "timestamp": datetime.fromtimestamp(
                        evt.timestamp / 1000, timezone.utc).isoformat(),
                })
            return
        if not isinstance(evt, MessageEvent) or evt.type != EventType.ROOM_MESSAGE:
            return
        await self.on_message(evt)

    async def on_message(self, evt: MessageEvent) -> None:
        if evt.sender == self.client.mxid or evt.sender not in self.config["allowed_senders"]:
            return
        msgtype = getattr(evt.content, "msgtype", None)
        if msgtype not in {MessageType.TEXT, MessageType.NOTICE, MessageType.IMAGE}:
            return
        if hasattr(evt.content, "trim_reply_fallback"):
            evt.content.trim_reply_fallback()
        body = getattr(evt.content, "body", "").strip()
        relation = getattr(evt.content, "relates_to", None)
        # Conversations are flat. A rich reply carries no rel_type, only
        # `m.in_reply_to`, and is how Tim addresses a specific earlier message.
        # A thread relation is still resolved so a client that opens one does
        # not silently drop the message.
        reply_to = ""
        if relation is not None:
            in_reply_to = getattr(relation, "in_reply_to", None)
            if in_reply_to is not None and in_reply_to.event_id:
                reply_to = str(in_reply_to.event_id)
            elif relation.rel_type == RelationType.THREAD and relation.event_id:
                reply_to = str(relation.event_id)
        if not body.startswith("!cogito") and str(evt.room_id) not in self._conversational_rooms:
            return
        self.log.info("Forwarding Matrix command event %s", evt.event_id)
        typing_task = None
        try:
            async def keep_typing() -> None:
                while True:
                    await self.client.set_typing(evt.room_id, timeout=60000)
                    await asyncio.sleep(45)

            typing_task = asyncio.create_task(keep_typing())
            value = {
                "event_id": str(evt.event_id),
                "room_id": str(evt.room_id),
                "sender": str(evt.sender),
                "body": body,
                "timestamp": datetime.fromtimestamp(evt.timestamp / 1000, timezone.utc).isoformat(),
            }
            if reply_to:
                value["reply_to"] = reply_to
            if msgtype == MessageType.IMAGE:
                info = getattr(evt.content, "info", None)
                mime_type = str(getattr(info, "mimetype", ""))
                if mime_type not in self.IMAGE_TYPES:
                    raise ValueError(f"unsupported image type: {mime_type or 'unknown'}")
                size = int(getattr(info, "size", 0) or 0)
                if size > self.MAX_IMAGE_BYTES:
                    raise ValueError("image exceeds the 8 MiB limit")
                encrypted = getattr(evt.content, "file", None)
                if encrypted:
                    ciphertext = await self.client.download_media(encrypted.url)
                    data = decrypt_attachment(
                        ciphertext, encrypted.key.key,
                        encrypted.hashes["sha256"], encrypted.iv,
                    )
                else:
                    data = await self.client.download_media(evt.content.url)
                if not data or len(data) > self.MAX_IMAGE_BYTES:
                    raise ValueError("image exceeds the 8 MiB limit")
                value["image"] = {
                    "mime_type": mime_type,
                    "name": str(getattr(evt.content, "filename", None) or body)[:512],
                    "data": base64.b64encode(data).decode("ascii"),
                }
            await self._request("/v1/matrix/events", value)
            self.log.info("Completed Matrix command event %s", evt.event_id)
        except Exception as exc:
            self.log.exception("gateway event failed")
            await evt.respond(f"⚠️ Gateway error: {exc}")
        finally:
            if typing_task:
                typing_task.cancel()
            await self.client.set_typing(evt.room_id, timeout=0)
