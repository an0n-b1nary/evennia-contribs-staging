# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026, an0n-b1nary. See LICENSE for full terms.
"""A connected session fixture for the Boards login transport tests."""

from contextlib import contextmanager
from unittest.mock import Mock, patch


@contextmanager
def connected_session(account):
    """Yield one attached test connection without using a real socket."""
    session = Mock()
    session.get_account.return_value = account
    session.get_puppet.return_value = None
    with patch("evennia.server.sessionhandler.SESSIONS") as sessions:
        sessions.get_sessions.return_value = [session]
        yield session
