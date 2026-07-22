from __future__ import annotations

from pathlib import Path

import numpy as np

from d5freq.utils.hashing import (
    file_sha256_manifest,
    sha256_bytes,
    sha256_directory,
    sha256_file,
    sha256_json,
)


def test_sha256_known_vector_and_streamed_file(tmp_path: Path) -> None:
    expected = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    path = tmp_path / "payload.bin"
    path.write_bytes(b"abc")

    assert sha256_bytes(b"abc") == expected
    assert sha256_file(path, chunk_size=1) == expected


def test_json_hash_is_independent_of_mapping_order() -> None:
    left = {"grid": {"M_s": 8.0, "f0_hz": 50.0}, "seed": 2}
    right = {"seed": 2, "grid": {"f0_hz": 50.0, "M_s": 8.0}}

    assert sha256_json(left) == sha256_json(right)
    assert sha256_json(left) != sha256_json({**left, "seed": 3})


def test_json_hash_supports_numpy_scalars_and_arrays() -> None:
    scientific = {"scalar": np.float64(1.5), "array": np.array([1, 2, 3])}
    plain = {"scalar": 1.5, "array": [1, 2, 3]}

    assert sha256_json(scientific) == sha256_json(plain)


def test_directory_manifest_is_sorted_and_content_sensitive(tmp_path: Path) -> None:
    (tmp_path / "z.txt").write_text("last", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "a.txt").write_text("first", encoding="utf-8")

    manifest = file_sha256_manifest(tmp_path)
    assert [entry["path"] for entry in manifest] == ["nested/a.txt", "z.txt"]
    before = sha256_directory(tmp_path)
    (nested / "a.txt").write_text("changed", encoding="utf-8")
    assert sha256_directory(tmp_path) != before
