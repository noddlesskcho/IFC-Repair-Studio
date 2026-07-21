from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ..models import Diagnosis


class ResultModel(QAbstractTableModel):
    headers = [
        "Status", "STEP ID", "Product class", "Product GlobalId", "Product name",
        "Representation identifier", "Representation type", "Current context",
        "Proposed context", "Confidence", "Reason", "Validation result",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Diagnosis] = []

    def set_results(self, rows: list[Diagnosis]) -> None:
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.headers)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return super().headerData(section, orientation, role)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        item = self.rows[index.row()]
        proposed = item.proposed_context
        values = [
            item.status.value, item.representation_step_id, item.product_class,
            item.product_global_id, item.product_name, item.representation_identifier,
            item.representation_type, item.current_context_step_id,
            proposed.step_id if proposed else None, f"{item.confidence:.0%}",
            "; ".join([*item.evidence, *item.conflicts]), item.validation_result,
        ]
        return "" if values[index.column()] is None else str(values[index.column()])
