import numpy as np

from bbs_database.embed.cache import encode_vec, decode_vec, decode_vecs


def test_encode_then_decode_roundtrip_preserves_values():
    vec = [0.1, -0.5, 1.0, 0.0, 3.14] + [0.0] * 1019
    blob = encode_vec(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == 1024 * 4
    decoded = decode_vec(blob)
    assert isinstance(decoded, np.ndarray)
    assert decoded.dtype == np.float32
    assert decoded.shape == (1024,)
    assert np.allclose(decoded[:5], np.array([0.1, -0.5, 1.0, 0.0, 3.14], dtype=np.float32))


def test_decode_vecs_stacks_into_2d():
    v1 = [0.0] * 1024
    v2 = [1.0] * 1024
    blobs = [encode_vec(v1), encode_vec(v2)]
    arr = decode_vecs(blobs)
    assert arr.shape == (2, 1024)
    assert arr.dtype == np.float32
    assert np.allclose(arr[1], 1.0)
