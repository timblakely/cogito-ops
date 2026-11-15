"""Recover a ChatGPT token rejected before its advertised expiry.

LiteLLM 1.105.5 refreshes auth.json only when expires_at passes. A ChatGPT
account change can revoke the access token earlier and return token_expired.
Keep this hook scoped to that response and remove it when upstream handles it.
"""

import asyncio
import fcntl
import logging
import os
from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx

from litellm.llms.chatgpt.authenticator import Authenticator
from litellm.llms.chatgpt.common_utils import RefreshAccessTokenError
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler, HTTPHandler


_LOG = logging.getLogger("litellm.chatgpt_early_refresh")
_ASYNC_POST = AsyncHTTPHandler.post
_SYNC_POST = HTTPHandler.post


def _is_chatgpt_token_expired(url: object, error: httpx.HTTPStatusError) -> bool:
    if error.response.status_code != 401 or not isinstance(url, str):
        return False
    base = urlsplit(Authenticator().get_api_base())
    target = urlsplit(url)
    if (target.scheme, target.netloc) != (base.scheme, base.netloc):
        return False
    if not target.path.startswith(base.path.rstrip("/") + "/"):
        return False
    try:
        body = error.response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    detail = body.get("detail")
    return isinstance(detail, dict) and detail.get("code") == "token_expired"


def _request_parts(args: tuple, kwargs: dict) -> tuple[object, Mapping | None]:
    url = args[0] if args else kwargs.get("url")
    headers = args[4] if len(args) > 4 else kwargs.get("headers")
    return url, headers if isinstance(headers, Mapping) else None


def _retry_args(args: tuple, kwargs: dict, headers: dict) -> tuple[tuple, dict]:
    if len(args) > 4:
        changed = list(args)
        changed[4] = headers
        return tuple(changed), kwargs
    return args, {**kwargs, "headers": headers}


def _recover_headers(headers: Mapping) -> dict | None:
    authorization = next((v for k, v in headers.items() if k.lower() == "authorization"), None)
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return None
    sent_token = authorization.removeprefix("Bearer ")
    auth = Authenticator()

    # Separate lock inode: auth.json itself is rewritten during refresh. This
    # serializes simultaneous 401s across proxy workers sharing the RWX PVC.
    lock_fd = os.open(os.path.join(auth.token_dir, "early-refresh.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        record = auth._read_auth_file()
        if not record:
            return None
        if record.get("access_token") == sent_token:
            refresh_token = record.get("refresh_token")
            if not isinstance(refresh_token, str) or not refresh_token:
                return None
            try:
                auth._refresh_tokens(refresh_token)
            except RefreshAccessTokenError as exc:
                # The upstream exception can contain the token endpoint body.
                _LOG.warning(
                    "ChatGPT early token refresh failed (HTTP %s); interactive login may be required",
                    exc.status_code,
                )
                return None
            record = auth._read_auth_file()
            _LOG.info("Refreshed a ChatGPT access token rejected before its stored expiry")
        if not record:
            return None
        new_token = record.get("access_token")
        if not isinstance(new_token, str) or not new_token or new_token == sent_token:
            return None
        updated = dict(headers)
        for name in list(updated):
            if name.lower() == "authorization":
                updated[name] = "Bearer " + new_token
            elif name.lower() == "chatgpt-account-id" and isinstance(record.get("account_id"), str):
                updated[name] = record["account_id"]
        return updated
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


async def _async_post_with_recovery(self, *args, **kwargs):
    try:
        return await _ASYNC_POST(self, *args, **kwargs)
    except httpx.HTTPStatusError as error:
        url, headers = _request_parts(args, kwargs)
        if headers is None or not _is_chatgpt_token_expired(url, error):
            raise
        try:
            refreshed = await asyncio.to_thread(_recover_headers, headers)
        except Exception as exc:
            _LOG.warning("ChatGPT early token refresh could not run (%s)", type(exc).__name__)
            raise error
        if refreshed is None:
            raise
        retry_args, retry_kwargs = _retry_args(args, kwargs, refreshed)
        return await _ASYNC_POST(self, *retry_args, **retry_kwargs)


def _sync_post_with_recovery(self, *args, **kwargs):
    try:
        return _SYNC_POST(self, *args, **kwargs)
    except httpx.HTTPStatusError as error:
        url, headers = _request_parts(args, kwargs)
        if headers is None or not _is_chatgpt_token_expired(url, error):
            raise
        try:
            refreshed = _recover_headers(headers)
        except Exception as exc:
            _LOG.warning("ChatGPT early token refresh could not run (%s)", type(exc).__name__)
            raise error
        if refreshed is None:
            raise
        retry_args, retry_kwargs = _retry_args(args, kwargs, refreshed)
        return _SYNC_POST(self, *retry_args, **retry_kwargs)


AsyncHTTPHandler.post = _async_post_with_recovery
HTTPHandler.post = _sync_post_with_recovery
