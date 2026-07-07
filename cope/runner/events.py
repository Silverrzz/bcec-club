from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


DEFAULT_WEB_EVENT_URL = "http://127.0.0.1:8701/internal/tournament-events"


def publish_tournament_event(tournament_id: int, live: dict | None = None) -> None:
    url = os.environ.get("COPE_WEB_EVENT_URL", DEFAULT_WEB_EVENT_URL)
    payload_data = {"tournament_id": tournament_id}
    if live is not None:
        payload_data["live"] = live
    payload = json.dumps(payload_data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=0.2):
            pass
    except (OSError, urllib.error.URLError):
        return
