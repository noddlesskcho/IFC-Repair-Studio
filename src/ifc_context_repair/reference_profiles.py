from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReferencePattern:
    product_class: str
    representation_identifier: str
    representation_type: str
    item_type: str
    context_identifier: str
    target_view: str
    clean_representation_count: int
    clean_file_count: int


# Derived semantically from the eight user-confirmed clean IFC4 samples. Local STEP
# IDs and GlobalIds are deliberately excluded. A profile only supports same-file
# context candidates that are also project-rooted; it never creates a context.
SUPPLIED_CLEAN_PATTERNS = (
    ReferencePattern("ifcslab", "body", "sweptsolid", "ifcextrudedareasolid",
                     "body", "MODEL_VIEW", 18, 8),
    ReferencePattern("ifcslab", "footprint", "curve2d", "ifcindexedpolycurve",
                     "footprint", "MODEL_VIEW", 16, 7),
)
