# Repair algorithm

The prescan reads bounded chunks and recognizes complete STEP records across physical
lines while tracking strings, doubled apostrophes, and comments. It only marks records
whose entity keyword is `IfcShapeRepresentation` and whose first argument is `$`.

Semantic inspection queries shape representations once and builds reusable indexes for
contexts, ownership, products, signatures, and context usage. Candidate scores are:

- matching valid sibling with the same identifier: +80;
- equivalent same-file representations: +45 plus frequency (capped);
- matching context identifier: +30;
- compatible Body `MODEL_VIEW`: +10;
- connection to the active project: +5.

Scores are evidence weights, not probabilities. Safe repair requires strong file
evidence and no conflict. A lead below 15 points is ambiguous. Identifier-only matches
are warnings. These thresholds are deterministic and unit-tested, but must be tuned
only from anonymised sample evidence.

Before assignment the engine confirms that the selected entity is in the same model.
It records item references, writes a new temporary IFC, reopens it, validates it, checks
entity counts, GlobalIds and representation item counts, then atomically renames it.
The source is never used as the output path.

The targeted mode patches `$` only in a fully parsed, confirmed representation record.
It retains encoding and line endings, and its output must pass the same reopen and
validation checks.
