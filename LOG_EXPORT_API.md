# Chatbot log export API

The chatbot exposes a read-only REST API for historical JSON records and a
Server-Sent Events (SSE) endpoint for newly completed interactions.

## Configuration

Add a long random secret to `vectors/.env`:

```env
LOG_EXPORT_API_KEY=replace-with-a-long-random-secret
```

One way to generate it is:

```bash
openssl rand -hex 32
```

Restart the backend after changing the environment. Keep this key on the
server side of the evaluation project. Send it in the header below; do not put
it in a URL or browser source code.

```http
Authorization: Bearer YOUR_LOG_EXPORT_API_KEY
```

The public agent IDs are `k12_chat` and `online_chat`. The legacy chat route
IDs `k12`, `ttu-online`, and `ttu_online` remain accepted by the backend.

## Historical records

```http
GET /api/v1/logs?agent=k12_chat&limit=100
Authorization: Bearer YOUR_LOG_EXPORT_API_KEY
```

Supported query parameters:

- `agent`: `k12_chat` or `online_chat` (optional)
- `since`: ISO-8601 timestamp, inclusive (optional)
- `until`: ISO-8601 timestamp, inclusive (optional)
- `limit`: 1-1000, default 100
- `cursor`: opaque value returned by the previous request

Example response:

```json
{
  "data": [],
  "next_cursor": null,
  "has_more": false,
  "count": 0
}
```

Continue requesting with `cursor=next_cursor` while `has_more` is true. A
single record is available at `GET /api/v1/logs/{log_id}`.

Python example:

```python
import os
import requests

base_url = "https://chatbot.example.edu"
headers = {"Authorization": f"Bearer {os.environ['CHATBOT_LOG_API_KEY']}"}
cursor = None

while True:
    params = {"agent": "k12_chat", "limit": 500}
    if cursor:
        params["cursor"] = cursor
    response = requests.get(
        f"{base_url}/api/v1/logs",
        headers=headers,
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    page = response.json()
    for record in page["data"]:
        evaluate(record)
    cursor = page["next_cursor"]
    if not page["has_more"]:
        break
```

## Live records

```http
GET /api/v1/logs/stream?agent=online_chat
Authorization: Bearer YOUR_LOG_EXPORT_API_KEY
Accept: text/event-stream
```

Each completed interaction is emitted after it has been appended to the daily
JSONL log file:

```text
event: interaction
id: 0e64354d-...
data: {"log_id":"0e64354d-...","timestamp":"..."}
```

The endpoint sends a heartbeat every 15 seconds. If the live connection drops,
reconnect and use the historical endpoint with the last saved cursor to recover
any records missed during the disconnection.

The current live broadcaster is in-process and matches the existing deployment,
which runs one Uvicorn backend process. If the backend is later scaled to
multiple processes or containers, replace the in-process broadcaster with Redis
Pub/Sub so every subscriber receives records from every backend instance.

## Browser access

Server-to-server calls do not require CORS configuration. If a separate browser
application must call the chatbot API directly, add its exact origin:

```env
LOG_EXPORT_CORS_ORIGINS=https://evaluation.example.edu
```

Direct browser access exposes the API key to browser users, so a server-side
proxy in the evaluation project is preferred.
