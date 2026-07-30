"""Reference assertions that must be expanded into Phase D tests."""
from __future__ import annotations
import ast
from pathlib import Path

MPC_REQUIRED_TOKENS = {'horizon', 'objective', 'constraints', 'solve'}


def assert_no_centered_convolution(source_path: str) -> None:
    text = Path(source_path).read_text(encoding='utf-8')
    assert "mode='same'" not in text and 'mode="same"' not in text


def assert_named_mpc_has_optimization(source_path: str) -> None:
    text = Path(source_path).read_text(encoding='utf-8').lower()
    missing = [t for t in MPC_REQUIRED_TOKENS if t not in text]
    assert not missing, f'Named MPC lacks implementation evidence: {missing}'


def assert_no_seed_mod_factor_encoding(source_path: str) -> None:
    text = Path(source_path).read_text(encoding='utf-8')
    forbidden = ['seed%2', 'seed % 2', 'seed%3', 'seed % 3', 'seed%4', 'seed % 4', 'seed%5', 'seed % 5']
    assert not any(x in text for x in forbidden)
