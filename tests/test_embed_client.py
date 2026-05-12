import os
from unittest.mock import MagicMock, patch

import pytest

from bbs_database.config import EmbedConfig
from bbs_database.embed.client import EmbedClient, EmbedAPIError, EmbedConfigError


def _cfg(**overrides):
    base = dict(
        enabled=True, provider="dashscope",
        base_url="https://example.test/v1",
        model="text-embedding-v3",
        dimensions=1024,
        api_key_env="TEST_EMBED_KEY",
        batch_size=25,
        max_input_chars=2000,
        max_retries=3,
        request_timeout_s=30,
        pinned_only_at_full_build=True,
    )
    base.update(overrides)
    return EmbedConfig(**base)


def test_embed_client_raises_if_api_key_env_missing(monkeypatch):
    monkeypatch.delenv("TEST_EMBED_KEY", raising=False)
    with pytest.raises(EmbedConfigError):
        EmbedClient(_cfg())


def test_embed_returns_one_vector_per_input(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg())
    fake_response = MagicMock()
    fake_response.data = [
        MagicMock(embedding=[0.1] * 1024),
        MagicMock(embedding=[0.2] * 1024),
    ]
    with patch.object(client._sdk.embeddings, "create", return_value=fake_response) as m:
        vecs = client.embed(["hello", "world"])
    assert len(vecs) == 2
    assert len(vecs[0]) == 1024
    m.assert_called_once()
    kwargs = m.call_args.kwargs
    assert kwargs["model"] == "text-embedding-v3"
    assert kwargs["dimensions"] == 1024
    assert kwargs["input"] == ["hello", "world"]


def test_embed_batches_inputs_above_batch_size(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg(batch_size=2))
    calls = []

    def fake_create(model, input, dimensions, **_):
        calls.append(list(input))
        r = MagicMock()
        r.data = [MagicMock(embedding=[float(i)] * 1024) for i in range(len(input))]
        return r

    with patch.object(client._sdk.embeddings, "create", side_effect=fake_create):
        vecs = client.embed(["a", "b", "c", "d", "e"])
    assert len(vecs) == 5
    assert [len(c) for c in calls] == [2, 2, 1]


def test_embed_truncates_long_inputs(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg(max_input_chars=10))
    captured = {}

    def fake_create(model, input, dimensions, **_):
        captured["input"] = list(input)
        r = MagicMock()
        r.data = [MagicMock(embedding=[0.0] * 1024) for _ in input]
        return r

    with patch.object(client._sdk.embeddings, "create", side_effect=fake_create):
        client.embed(["short", "x" * 100])
    assert captured["input"] == ["short", "x" * 10]


def test_embed_wraps_sdk_exception_as_embedapierror(monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "sk-test")
    client = EmbedClient(_cfg())
    with patch.object(client._sdk.embeddings, "create", side_effect=RuntimeError("boom")):
        with pytest.raises(EmbedAPIError):
            client.embed(["hello"])
