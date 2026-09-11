"""Thin encrypted Matrix transport for the durable Cogito coordinator."""

from datetime import datetime, timezone
import hashlib
import hmac
import json

from maubot import MessageEvent, Plugin
from maubot.handlers import event
from mautrix.types import EventType, RelationType
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("coordinator_url")
        helper.copy("coordinator_secret")
        helper.copy("allowed_senders")


class CogitoBot(Plugin):
    async def start(self) -> None:
        self.config.load_and_update()

    @classmethod
    def get_config_class(cls):
        return Config

    @event.on(EventType.ROOM_MESSAGE)
    async def on_message(self, evt: MessageEvent) -> None:
        if evt.sender == self.client.mxid or evt.sender not in self.config["allowed_senders"]:
            return
        body = getattr(evt.content, "body", "").strip()
        if not (body.startswith("!cogito") or body.startswith(">>")):
            return
        relation = getattr(evt.content, "relates_to", None)
        thread_root = None
        if relation and relation.rel_type == RelationType.THREAD:
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
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(
            self.config["coordinator_secret"].encode(), payload, hashlib.sha256
        ).hexdigest()
        try:
            async with self.http.post(
                self.config["coordinator_url"].rstrip("/") + "/v1/matrix/events",
                data=payload,
                headers={"Content-Type": "application/json", "X-Cogito-Signature-256": signature},
            ) as response:
                result = await response.json()
                if response.status >= 400:
                    raise RuntimeError(result.get("error", f"HTTP {response.status}"))
            for action in result.get("actions", []):
                if action.get("kind") == "message":
                    await evt.respond(action["body"], markdown=True, allow_html=False, in_thread=True)
        except Exception as exc:
            self.log.exception("coordinator event failed")
            await evt.respond(f"⚠️ Coordinator error: `{type(exc).__name__}`", in_thread=True)
