"""Shared test fixtures.

The `no_network` fixture is autouse: it hard-fails any test that tries to open a
socket, guaranteeing the suite (and mock mode) never hits the network.
"""

from __future__ import annotations

import socket

import pytest

from pod_autopilot import config


class _NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Block all outbound sockets during tests."""

    def _blocked(*args, **kwargs):
        raise _NetworkBlocked(
            "network access attempted during a test — tests must stay offline"
        )

    # Block at the lowest level: socket creation and connection.
    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield


@pytest.fixture
def mock_cfg(tmp_path):
    """A MOCK-mode Config writing artifacts into a temp output dir."""
    return config.Config(
        mock=True,
        output_dir=tmp_path / "output",
        retail_price=24.99,
        min_margin=0.35,
    )
