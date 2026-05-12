"""DashScope Qwen v3 (and any OpenAI-compatible) embedding client.

Wraps `openai.OpenAI` with batch dispatch, character truncation, and exception
mapping to BBS_Database's error types. The OpenAI SDK already retries 5xx/429
with exponential backoff up to `max_retries`.
"""

from __future__ import annotations

import os

from bbs_database.config import EmbedConfig


class BBSDatabaseError(Exception):
    code: str = ""


class EmbedConfigError(BBSDatabaseError):
    code = "embed_config_error"


class EmbedAPIError(BBSDatabaseError):
    code = "embed_api_error"


class EmbedClient:
    def __init__(self, cfg: EmbedConfig):
        self._cfg = cfg
        api_key = os.environ.get(cfg.api_key_env, "").strip()
        if not api_key:
            raise EmbedConfigError(
                f"environment variable {cfg.api_key_env!r} is empty or missing"
            )
        from openai import OpenAI
        self._sdk = OpenAI(
            api_key=api_key,
            base_url=cfg.base_url,
            timeout=cfg.request_timeout_s,
            max_retries=cfg.max_retries,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input. Truncates each input to max_input_chars."""
        truncated = [t[: self._cfg.max_input_chars] for t in texts]
        out: list[list[float]] = []
        bs = self._cfg.batch_size
        for i in range(0, len(truncated), bs):
            batch = truncated[i : i + bs]
            try:
                resp = self._sdk.embeddings.create(
                    model=self._cfg.model,
                    input=batch,
                    dimensions=self._cfg.dimensions,
                )
            except Exception as e:
                raise EmbedAPIError(f"embedding API call failed: {e!r}") from e
            for d in resp.data:
                out.append(list(d.embedding))
        return out
