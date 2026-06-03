"""engine.export — turn an EditDecisionList into editor-importable files.

**Primary (default): FCP7 XML (`.xml`, `<xmeml>`)** — Premiere Pro 2026 imports this
natively. Premiere 2026 does NOT recognize `.fcpxml`, so `fcpxml.py` is kept only as a
secondary/reference exporter. `edl` (CMX3600) remains the documented last-resort fallback
(PRD §9 Q4); built only if FCP7 XML import also fights us.

The exporters depend only on the contract types (CONTRACTS.md is law) — never on engine
internals. Frame-snapping from float seconds to integer frames happens HERE ONLY.
"""

from engine.export.fcp7xml import edit_decision_list_to_fcp7xml, write_fcp7xml
from engine.export.fcpxml import edit_decision_list_to_fcpxml, write_fcpxml

# Default export surface = FCP7 XML.
write_sequence = write_fcp7xml
edit_decision_list_to_sequence = edit_decision_list_to_fcp7xml

__all__ = [
    # primary (FCP7 XML / Premiere-native)
    "write_fcp7xml",
    "edit_decision_list_to_fcp7xml",
    "write_sequence",
    "edit_decision_list_to_sequence",
    # secondary (FCPXML — Premiere 2026 does not import this)
    "write_fcpxml",
    "edit_decision_list_to_fcpxml",
]
