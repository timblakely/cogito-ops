"""Thin encrypted Matrix transport for the durable Cogito gateway."""

from datetime import datetime, timezone
import asyncio
import base64
import hashlib
import hmac
import json
import os

from maubot import MessageEvent, Plugin
from maubot.handlers import event
from mautrix.errors import MUnknown
from mautrix.crypto.attachments import decrypt_attachment
from mautrix.types import Event, EventID, EventType, MessageType, RelationType, RoomID, TextMessageEventContent
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("gateway_url")
        helper.copy("gateway_secret")
        helper.copy("allowed_senders")


class CogitoBot(Plugin):
    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

    async def start(self) -> None:
        self._project_rooms = set(filter(
            None, os.environ.get("MATRIX_PROJECT_ROOM_ID", "").split(",")))
        self.log.info(
            "Matrix receiver started for %d allowed sender(s) and %d project room(s)",
            len(self.config["allowed_senders"]),
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

    async def _deliver_outbox(self) -> None:
        while True:
            try:
                result = await self._request("/v1/matrix/outbox", {"operation": "poll", "limit": 20})
                typing_rooms = set(result.get("typing_rooms", []))
                for room_id in typing_rooms:
                    # Matrix typing is room-scoped, not thread-scoped. Refresh
                    # a short lease on every poll while any planning scout or
                    # Astra synthesis for that room remains active.
                    await self.client.set_typing(RoomID(room_id), timeout=15000)
                for room_id in self._planning_typing_rooms - typing_rooms:
                    await self.client.set_typing(RoomID(room_id), timeout=0)
                self._planning_typing_rooms = typing_rooms
                for item in result.get("notifications", []):
                    if item.get("kind") == "edit":
                        content = TextMessageEventContent(
                            msgtype=MessageType.TEXT, body=item["body"])
                        content.set_edit(EventID(item["target_event_id"]))
                        event_id = await self.client.send_message_event(
                            RoomID(item["room_id"]), EventType.ROOM_MESSAGE,
                            content, txn_id=item["notification_id"],
                        )
                        await self._request("/v1/matrix/outbox", {
                            "operation": "ack", "notification_id": item["notification_id"],
                            "event_id": str(event_id),
                        })
                        continue
                    relates_to = None
                    if item["thread_root"]:
                        relation = TextMessageEventContent(msgtype=MessageType.TEXT, body="")
                        relation.set_thread_parent(EventID(item["thread_root"]), reply_fallback=True)
                        relates_to = relation.relates_to
                    try:
                        event_id = await self.client.send_markdown(
                            RoomID(item["room_id"]), item["body"], allow_html=False,
                            relates_to=relates_to,
                            txn_id=item["notification_id"],
                        )
                    except MUnknown as exc:
                        if "unknown event" not in str(exc).lower():
                            raise
                        # Imported or synthetic legacy plans can reference a root
                        # the bot never saw. Preserve the notification at room level;
                        # newly created plans always retain their real thread root.
                        event_id = await self.client.send_markdown(
                            RoomID(item["room_id"]),
                            "[Original plan thread unavailable] " + item["body"],
                            allow_html=False,
                            txn_id=item["notification_id"] + "-fallback",
                        )
                    await self._request("/v1/matrix/outbox", {
                        "operation": "ack", "notification_id": item["notification_id"],
                        "event_id": str(event_id),
                    })
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("gateway outbox delivery failed")
            await asyncio.sleep(5)

    @classmethod
    def get_config_class(cls):
        return Config

    @event.on(EventType.ALL)
    async def on_event(self, evt: Event) -> None:
        # A global handler receives both the encrypted envelope and the decrypted
        # message emitted by mautrix's DecryptionDispatcher. Explicitly select the
        # latter here rather than depending on maubot's per-type handler routing.
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
        is_thread_reply = bool(relation and relation.rel_type == RelationType.THREAD)
        if (not body.startswith("!cogito") and not is_thread_reply
                and str(evt.room_id) not in self._project_rooms):
            return
        self.log.info("Forwarding Matrix command event %s", evt.event_id)
        typing_task = None
        try:
            async def keep_typing() -> None:
                while True:
                    await self.client.set_typing(evt.room_id, timeout=60000)
                    await asyncio.sleep(45)

            typing_task = asyncio.create_task(keep_typing())
            thread_root = None
            if is_thread_reply:
                thread_root = str(relation.event_id)
            value = {
                "event_id": str(evt.event_id),
                "room_id": str(evt.room_id),
                "sender": str(evt.sender),
                "body": body,
                "timestamp": datetime.fromtimestamp(evt.timestamp / 1000, timezone.utc).isoformat(),
            }
            if thread_root:
                value["thread_root"] = thread_root
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
            await evt.respond(f"⚠️ Gateway error: {exc}", in_thread=True)
        finally:
            if typing_task:
                typing_task.cancel()
            await self.client.set_typing(evt.room_id, timeout=0)
