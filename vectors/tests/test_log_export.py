from __future__ import annotations

import json
import os
import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import logger
from log_stream import publish, subscribe, unsubscribe
from fastapi import HTTPException

from log_export import require_log_api_key


class LogExportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.logs_dir = Path(self.temp_dir.name)
        self.logs_patch = patch.object(logger, "_LOGS_DIR", self.logs_dir)
        self.logs_patch.start()

        records = [
            {
                "log_id": "old-online",
                "timestamp": "2026-08-01T12:00:00+00:00",
                "query": {"agent_routed_to": "ttu-online", "text": "one"},
            },
            {
                "log_id": "new-k12",
                "timestamp": "2026-08-02T12:00:00+00:00",
                "query": {"agent_routed_to": "k12_chat", "text": "two"},
            },
            {
                "log_id": "new-online",
                "timestamp": "2026-08-02T13:00:00+00:00",
                "query": {"agent_routed_to": "online_chat", "text": "three"},
            },
        ]
        (self.logs_dir / "2026-08-01.jsonl").write_text(
            json.dumps(records[0]) + "\n", encoding="utf-8"
        )
        (self.logs_dir / "2026-08-02.jsonl").write_text(
            "\n".join(json.dumps(record) for record in records[1:]) + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.logs_patch.stop()
        self.temp_dir.cleanup()

    def test_pagination_and_old_agent_normalization(self):
        first, cursor, has_more = logger.list_log_records(limit=2)
        self.assertEqual([record["log_id"] for record in first], ["old-online", "new-k12"])
        self.assertEqual(first[0]["query"]["agent_routed_to"], "online_chat")
        self.assertTrue(has_more)
        self.assertIsNotNone(cursor)

        second, _, has_more = logger.list_log_records(limit=2, cursor=cursor)
        self.assertEqual([record["log_id"] for record in second], ["new-online"])
        self.assertFalse(has_more)

    def test_filters_by_agent_and_time(self):
        records, _, _ = logger.list_log_records(
            agent="online_chat",
            since=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        self.assertEqual([record["log_id"] for record in records], ["new-online"])

    def test_single_record_lookup_normalizes_agent(self):
        record = logger.get_log_record("old-online")
        self.assertIsNotNone(record)
        self.assertEqual(record["query"]["agent_routed_to"], "online_chat")

    def test_bearer_authentication(self):
        with patch.dict(os.environ, {"LOG_EXPORT_API_KEY": "test-secret"}):
            require_log_api_key("Bearer test-secret")
            with self.assertRaises(HTTPException) as raised:
                require_log_api_key("Bearer wrong-secret")
            self.assertEqual(raised.exception.status_code, 401)


class LiveLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_published_record_reaches_subscriber(self):
        subscriber = subscribe()
        try:
            publish({"log_id": "live-test"})
            record = await asyncio.wait_for(subscriber.queue.get(), timeout=1)
            self.assertEqual(record["log_id"], "live-test")
        finally:
            unsubscribe(subscriber)
