from __future__ import annotations

import time
from typing import Any


def test_products(model: Any, products: list[Any]) -> list[dict[str, object]]:
    import ifcopenshell.geom

    settings = ifcopenshell.geom.settings()
    results = []
    for product in products:
        started = time.perf_counter()
        try:
            ifcopenshell.geom.create_shape(settings, product)
            results.append({"step_id": product.id(), "success": True,
                            "seconds": time.perf_counter() - started})
        except Exception as exc:
            results.append({"step_id": product.id(), "success": False,
                            "seconds": time.perf_counter() - started,
                            "error": f"{type(exc).__name__}: {exc}"})
    return results
