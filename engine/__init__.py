"""Premiere Pro Connector — engine package.

Pure, offline-testable editing engine. See ARCHITECTURE.md §2.1. Engine code depends
only on ``engine.contracts`` and the provider protocols — never on adapter internals
or Modal/HTTP specifics (AGENTS.md §2, golden rule 1).
"""

from engine.contracts import CONTRACT_VERSION

__all__ = ["CONTRACT_VERSION"]
