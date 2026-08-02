from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class Subscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[dict[str, Any]]


_subscribers: set[Subscriber] = set()
_subscribers_lock = Lock()


def subscribe(max_queue_size: int = 100) -> Subscriber:
    subscriber = Subscriber(
        loop=asyncio.get_running_loop(),
        queue=asyncio.Queue(maxsize=max_queue_size),
    )
    with _subscribers_lock:
        _subscribers.add(subscriber)
    return subscriber


def unsubscribe(subscriber: Subscriber) -> None:
    with _subscribers_lock:
        _subscribers.discard(subscriber)


def _enqueue(queue: asyncio.Queue[dict[str, Any]], record: dict[str, Any]) -> None:
    # A slow evaluator must not block chatbot logging. Keep the newest events;
    # clients can use the historical endpoint to recover anything they missed.
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    queue.put_nowait(record)


def publish(record: dict[str, Any]) -> None:
    with _subscribers_lock:
        subscribers = tuple(_subscribers)
    for subscriber in subscribers:
        if not subscriber.loop.is_closed():
            subscriber.loop.call_soon_threadsafe(_enqueue, subscriber.queue, record)

