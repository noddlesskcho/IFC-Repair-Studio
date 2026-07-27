from __future__ import annotations

import sys
import time
from collections import Counter

import ifcopenshell

from ifc_context_repair.indirect import classify_missing_contexts


started = time.perf_counter()
model = ifcopenshell.open(sys.argv[1])
print(f"OPEN_SECONDS={time.perf_counter() - started:.3f}")
timings: dict[str, float] = {}
diagnoses, _index = classify_missing_contexts(model, timings=timings)
print(f"TOTAL={len(diagnoses)}")
for (classification, identifier, representation_type), count in sorted(Counter(
    (
        item.classification.value,
        item.representation_identifier or "-",
        item.representation_type or "-",
    )
    for item in diagnoses
).items()):
    scoped = [
        item for item in diagnoses
        if (
            item.classification.value,
            item.representation_identifier or "-",
            item.representation_type or "-",
        ) == (classification, identifier, representation_type)
    ]
    high = sum(item.confidence_level.value == "HIGH" for item in scoped)
    ambiguous = sum(item.confidence_level.value == "AMBIGUOUS" for item in scoped)
    print(
        f"ROW={classification}|{identifier}/{representation_type}|"
        f"{count}|{high}|{ambiguous}"
    )
print("PRODUCT_CLASSES")
for key, count in sorted(Counter(
    product_class
    for item in diagnoses
    for product_class, amount in item.ultimate_product_classes.items()
    for _ in range(amount)
).items()):
    print(f"PRODUCT={key}|{count}")
print(f"TIMINGS={timings}")
