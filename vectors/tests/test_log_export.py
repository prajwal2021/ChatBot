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

from agent_ids import canonical_agent_id
from log_export import _validated_agent, require_log_api_key, router


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

    def test_pagination_and_alias_normalization(self):
        first, cursor, has_more = logger.list_log_records(limit=2)
        self.assertEqual([record["log_id"] for record in first], ["old-online", "new-k12"])
        self.assertEqual(first[0]["query"]["agent_routed_to"], "ttu-online")
        self.assertEqual(first[1]["query"]["agent_routed_to"], "k12")
        self.assertTrue(has_more)
        self.assertIsNotNone(cursor)

        second, _, has_more = logger.list_log_records(limit=2, cursor=cursor)
        self.assertEqual([record["log_id"] for record in second], ["new-online"])
        self.assertFalse(has_more)

    def test_filters_by_agent_and_time(self):
        records, _, _ = logger.list_log_records(
            agent="ttu-online",
            since=datetime(2026, 8, 2, tzinfo=timezone.utc),
        )
        self.assertEqual([record["log_id"] for record in records], ["new-online"])

        alias_records, _, _ = logger.list_log_records(agent="online_chat")
        self.assertEqual(
            [record["log_id"] for record in alias_records],
            ["old-online", "new-online"],
        )

        k12_records, _, _ = logger.list_log_records(agent="k12_chat")
        self.assertEqual([record["log_id"] for record in k12_records], ["new-k12"])

    def test_single_record_lookup_normalizes_agent(self):
        record = logger.get_log_record("old-online")
        self.assertIsNotNone(record)
        self.assertEqual(record["query"]["agent_routed_to"], "ttu-online")

    def test_reverted_ids_are_canonical_and_aliases_validate(self):
        self.assertEqual(canonical_agent_id("ttu-online"), "ttu-online")
        self.assertEqual(canonical_agent_id("online_chat"), "ttu-online")
        self.assertEqual(canonical_agent_id("k12"), "k12")
        self.assertEqual(canonical_agent_id("k12_chat"), "k12")
        self.assertEqual(_validated_agent("online_chat"), "ttu-online")
        self.assertEqual(_validated_agent("k12_chat"), "k12")

    def test_bearer_authentication(self):
        with patch.dict(os.environ, {"LOG_EXPORT_API_KEY": "test-secret"}):
            require_log_api_key("Bearer test-secret")
            with self.assertRaises(HTTPException) as raised:
                require_log_api_key("Bearer wrong-secret")
            self.assertEqual(raised.exception.status_code, 401)

    def test_all_log_export_get_routes_keep_bearer_dependency(self):
        expected_paths = {
            "/api/v1/logs",
            "/api/v1/logs/stream",
            "/api/v1/logs/{log_id}",
        }
        get_routes = {
            route.path: route
            for route in router.routes
            if "GET" in getattr(route, "methods", set())
        }
        self.assertTrue(expected_paths.issubset(get_routes))
        for path in expected_paths:
            dependencies = get_routes[path].dependant.dependencies
            self.assertTrue(
                any(dependency.call is require_log_api_key for dependency in dependencies),
                path,
            )


class LiveLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_published_record_reaches_subscriber(self):
        subscriber = subscribe()
        try:
            publish({"log_id": "live-test"})
            record = await asyncio.wait_for(subscriber.queue.get(), timeout=1)
            self.assertEqual(record["log_id"], "live-test")
        finally:
            unsubscribe(subscriber)
