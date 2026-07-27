# IFC+SG Rule Development Guide

All production rules live under `src/ifc_context_repair/rules/ifc_sg/` and
implement `IfcSgRule`.

Every rule declares:

- immutable versioned `rule_id`;
- purpose and category;
- supported IFC schemas;
- tested exporter patterns;
- supported signatures;
- `SAFE`, `ADVANCED`, or `AUDIT_ONLY` repair level;
- `EXPERIMENTAL`, `BETA`, or `PRODUCTION` maturity;
- confidence requirement;
- repair capability and known limitations.

## Required lifecycle

1. `is_applicable(context)` uses pre-scan and schema evidence.
2. `detect(context)` returns issues without modifying the model.
3. `classify(issue, context)` separates `HIGH`, `REPORT_ONLY`, `AMBIGUOUS`,
   `ORPHANED`, and `UNSUPPORTED`.
4. `propose_repair` records target, attribute, current/proposed values, evidence
   and the exact expected record difference.
5. `verify` proves the intended attribute changed and unrelated data did not.

## Context rule requirements

- Supported signatures are initially `Body / SweptSolid`,
  `Body / Tessellation`, and `FootPrint / Curve2D`.
- Candidate contexts must be project-connected and semantically compatible.
- Multiple compatible entity references are ambiguous even when their labels
  look identical.
- Direct ownership, shape-aspect ownership, mapped usage, type ownership and
  type occurrences are distinct evidence paths.
- Type-owned maps without occurrences may qualify only when one context,
  semantic peers and sibling hierarchy all agree.
- Production code must not contain sample STEP IDs.

## Maturity promotion

- Experimental: synthetic detection tests.
- Beta: relationship, ambiguity, cancellation and failure-safety tests.
- Production: clean/faulty regression counts, exact-difference verification,
  large-file performance evidence, packaged executable smoke test, and written
  limitations.

Never create a “fix all” rule and never broaden signatures during a bug fix.
