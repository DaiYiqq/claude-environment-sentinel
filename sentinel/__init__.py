"""Claude Environment Sentinel.

A local-only companion that audits the consistency of the user's environment
with the network exit region, offers reversible alignment of user-level
settings, and provides a kill-switch for Claude processes started under its
supervision.

It is not a server-side risk-control bypass and makes no guarantee about
account outcomes.
"""

from __future__ import annotations

__version__ = "1.0.0"
APP_NAME = "Claude Environment Sentinel"
APP_SLOGAN = "先审计，再对齐，最后才安全启动。"

__all__ = ["__version__", "APP_NAME", "APP_SLOGAN"]
