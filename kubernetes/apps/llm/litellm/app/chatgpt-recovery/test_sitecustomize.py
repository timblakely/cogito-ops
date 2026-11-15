"""Focused checks for the LiteLLM 1.105.5 ChatGPT 401 recovery hook."""

import asyncio
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory

import httpx
import sitecustomize as recovery
from litellm.llms.custom_httpx.http_handler import MaskedHTTPStatusError


URL = "https://chatgpt.com/backend-api/codex/responses"


def upstream_error(code="token_expired", url=URL):
    request = httpx.Request("POST", url)
    response = httpx.Response(401, json={"detail": {"code": code}}, request=request)
    original = httpx.HTTPStatusError("upstream rejected token", request=request, response=response)
    return MaskedHTTPStatusError(original)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        old_async = recovery._ASYNC_POST
        old_sync = recovery._SYNC_POST
        old_recover = recovery._recover_headers
        old_auth = recovery.Authenticator
        self.addCleanup(setattr, recovery, "_ASYNC_POST", old_async)
        self.addCleanup(setattr, recovery, "_SYNC_POST", old_sync)
        self.addCleanup(setattr, recovery, "_recover_headers", old_recover)
        self.addCleanup(setattr, recovery, "Authenticator", old_auth)

    def test_async_retries_exact_token_expired_once(self):
        seen = []

        async def post(_self, *args, **kwargs):
            seen.append(kwargs["headers"]["Authorization"])
            if len(seen) == 1:
                raise upstream_error()
            return "ok"

        recovery._ASYNC_POST = post
        recovery._recover_headers = lambda headers: {**headers, "Authorization": "Bearer new"}
        result = asyncio.run(recovery._async_post_with_recovery(
            object(), url=URL, headers={"Authorization": "Bearer old"}
        ))
        self.assertEqual(result, "ok")
        self.assertEqual(seen, ["Bearer old", "Bearer new"])

    def test_unrelated_401_does_not_refresh(self):
        for code, url in [("invalid_grant", URL), ("token_expired", "https://example.com/responses")]:
            with self.subTest(code=code, url=url):
                calls = []

                def post(_self, *args, **kwargs):
                    calls.append(1)
                    raise upstream_error(code, url)

                recovery._SYNC_POST = post
                recovery._recover_headers = lambda headers: self.fail("unexpected refresh")
                with self.assertRaises(httpx.HTTPStatusError):
                    recovery._sync_post_with_recovery(
                        object(), url=url, headers={"Authorization": "Bearer old"}
                    )
                self.assertEqual(len(calls), 1)

    def test_second_401_is_returned_without_another_refresh(self):
        calls = []
        refreshes = []

        def post(_self, *args, **kwargs):
            calls.append(1)
            raise upstream_error()

        recovery._SYNC_POST = post
        recovery._recover_headers = lambda headers: (refreshes.append(1) or {
            **headers, "Authorization": "Bearer new"
        })
        with self.assertRaises(httpx.HTTPStatusError):
            recovery._sync_post_with_recovery(object(), url=URL, headers={"Authorization": "Bearer old"})
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(refreshes), 1)

    def test_simultaneous_401s_use_one_refresh(self):
        with TemporaryDirectory() as token_dir:
            record = {"access_token": "old", "refresh_token": "refresh", "account_id": "account"}
            refreshes = []
            barrier = threading.Barrier(2)

            class FakeAuth:
                def __init__(self):
                    self.token_dir = token_dir

                def _read_auth_file(self):
                    return dict(record)

                def _refresh_tokens(self, token):
                    self_test.assertEqual(token, "refresh")
                    refreshes.append(1)
                    time.sleep(0.05)
                    record.update(access_token="new", refresh_token="next")

            self_test = self
            recovery.Authenticator = FakeAuth

            def recover():
                barrier.wait()
                return recovery._recover_headers({
                    "Authorization": "Bearer old", "ChatGPT-Account-Id": "account"
                })

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: recover(), range(2)))
            self.assertEqual(len(refreshes), 1)
            self.assertEqual([r["Authorization"] for r in results], ["Bearer new", "Bearer new"])


if __name__ == "__main__":
    unittest.main()
