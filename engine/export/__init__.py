"""engine.export — turn an EditDecisionList into editor-importable files.

Phase 0 ships ``fcpxml`` (primary). ``edl`` (CMX3600) is the documented fallback per
CONTRACTS.md / PRD §9 Q4, to be built only if FCPXML import proves too fragile.

The exporters depend only on the contract types (CONTRACTS.md is law) — never on engine
internals. Frame-snapping from float seconds to rational frame time happens HERE ONLY.
"""

from engine.export.fcpxml import edit_decision_list_to_fcpxml, write_fcpxml

__all__ = ["edit_decision_list_to_fcpxml", "write_fcpxml"]
