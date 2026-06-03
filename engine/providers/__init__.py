"""engine.providers — swappable adapters for the hosted analyzers (ARCHITECTURE §2.2).

Engine code imports the *protocols* (and, in Phase 0, the *fakes*) from here — never Modal
or HTTP specifics. Real Modal-backed adapters land in Phase 1 behind these same protocols.
"""

from engine.providers.base import AngleScoringProvider, TranscriberProvider
from engine.providers.fakes import FakeAngleScorer, FakeTranscriber

__all__ = [
    "TranscriberProvider",
    "AngleScoringProvider",
    "FakeTranscriber",
    "FakeAngleScorer",
]
