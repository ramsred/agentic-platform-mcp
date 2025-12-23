import os
import json
import httpx
from typing import Any, Dict, List, Optional


class LLMClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("LLM_BASE_URL", "http://llm:8000/v1").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        self.api_key = os.getenv("LLM_API_KEY")  # optional for local vLLM

        self._headers = {"Content-Type": "application/json"}
        if self.api_key:
            self._headers["Authorization"] = f"Bearer {self.api_key}"

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 256,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
    ) -> Dict[str, Any]:
        """
        Calls /v1/chat/completions and expects the assistant to output JSON only.
        We parse and return that JSON object.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        url = f"{self.base_url}/chat/completions"
        with httpx.Client(timeout=timeout_s) as client:
            try:
                r = client.post(url, headers=self._headers, json=payload)
            except Exception as e:
                raise RuntimeError(
                    f"LLMClient failed to reach {url}. "
                    f"If using docker-compose service DNS like 'llm', run host inside compose; "
                    f"otherwise use http://localhost:8008/v1. Original: {e}"
                )
            r.raise_for_status()
            data = r.json()

        content = data["choices"][0]["message"]["content"].strip()

        # Hard parse: must be JSON. If the model wraps it in text, try extracting JSON object.
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # fallback: extract first {...} block
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(content[start : end + 1])
            raise