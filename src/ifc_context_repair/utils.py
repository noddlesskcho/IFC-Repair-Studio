from __future__ import annotations


def format_bytes(value: int) -> str:
    """Format a byte count consistently for the desktop UI and reports."""
    amount = float(value or 0)
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value:,} B"
