from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib import request


class CompletionClient(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass(slots=True)
class OpenAICompatibleClient:
    """Minimal chat-completions client with no provider SDK dependency."""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60

    def complete(self, system: str, user: str) -> str:
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode()
        call = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with request.urlopen(call, timeout=self.timeout_seconds) as response:
            payload = json.load(response)
        try:
            return str(payload["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("Provider returned an unsupported chat-completions response") from error
