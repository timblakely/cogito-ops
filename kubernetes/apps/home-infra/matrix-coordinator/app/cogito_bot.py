"""Thin encrypted Matrix transport for the durable Cogito coordinator."""

from datetime import datetime, timezone
import asyncio
import hashlib
import hmac
import json

from maubot import MessageEvent, Plugin
from maubot.handlers import event
from mautrix.errors import MUnknown
from mautrix.types import Event, EventID, EventType, MessageType, RelationType, RoomID, TextMessageEventContent
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("coordinator_url")
        helper.copy("coordinator_secret")
        helper.copy("allowed_senders")


class CogitoBot(Plugin):
    async def start(self) -> None:
        self.log.info(
            "Matrix command receiver started for %d allowed sender(s)",
            len(self.config["allowed_senders"]),
        )
        self._outbox_task = asyncio.create_task(self._deliver_outbox())

    async def stop(self) -> None:
        self._outbox_task.cancel()

    async def _request(self, path: str, value: dict) -> dict:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(
            self.config["coordinator_secret"].encode(), payload, hashlib.sha256
        ).hexdigest()
        async with self.http.post(
            self.config["coordinator_url"].rstrip("/") + path,
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
                for item in result.get("notifications", []):
                    relation = TextMessageEventContent(msgtype=MessageType.TEXT, body="")
                    relation.set_thread_parent(EventID(item["thread_root"]), reply_fallback=True)
                    try:
                        event_id = await self.client.send_markdown(
                            RoomID(item["room_id"]), item["body"], allow_html=False,
                            relates_to=relation.relates_to,
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
                self.log.exception("coordinator outbox delivery failed")
            await asyncio.sleep(5)

    @classmethod
    def get_config_class(cls):
        return Config

    @event.on(EventType.ALL)
    async def on_event(self, evt: Event) -> None:
        # A global handler receives both the encrypted envelope and the decrypted
        # message emitted by mautrix's DecryptionDispatcher. Explicitly select the
        # latter here rather than depending on maubot's per-type handler routing.
        if not isinstance(evt, MessageEvent) or evt.type != EventType.ROOM_MESSAGE:
            return
        await self.on_message(evt)

    async def on_message(self, evt: MessageEvent) -> None:
        if evt.sender == self.client.mxid or evt.sender not in self.config["allowed_senders"]:
            return
        if getattr(evt.content, "msgtype", None) not in {MessageType.TEXT, MessageType.NOTICE}:
            return
        evt.content.trim_reply_fallback()
        body = getattr(evt.content, "body", "").strip()
        relation = getattr(evt.content, "relates_to", None)
        is_thread_reply = bool(relation and relation.rel_type == RelationType.THREAD)
        if not body.startswith("!cogito") and not is_thread_reply:
            return
        self.log.info("Forwarding Matrix command event %s", evt.event_id)
        try:
            command = body.removeprefix("!cogito").strip().partition(" ")[0].lower()
            progress = {
                "plan": "⏳ Plan request received. I’ll post the draft here when planning completes.",
                "revise": "⏳ Revision request received. I’ll post the updated plan here when ready.",
                "approve": "⏳ Approval received. I’m creating and dispatching the deliverables now.",
                "merge": "⏳ Merge approval received. I’m validating and merging the reviewed change now.",
            }.get(command)
            if body.startswith("!cogito") and progress:
                await evt.respond(progress, in_thread=True)
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
            result = await self._request("/v1/matrix/events", value)
            for action in result.get("actions", []):
                if action.get("kind") == "message":
                    await evt.respond(action["body"], markdown=True, allow_html=False, in_thread=True)
            self.log.info("Completed Matrix command event %s", evt.event_id)
        except Exception as exc:
            self.log.exception("coordinator event failed")
            await evt.respond(f"⚠️ Coordinator error: {exc}", in_thread=True)
