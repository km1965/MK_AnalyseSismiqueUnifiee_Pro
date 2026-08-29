"""Modèle de données structuré pour les rapports de calcul.

Remplace les sentinelles '---' (autrefois utilisées comme clés de section)
par un objet ``Report`` composé de ``Item`` (grandeur, valeur, unité, note).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union

Number = Union[int, float]


@dataclass
class Item:
    label: str
    value: Union[Number, str, None]
    unit: str = ""
    note: str = ""
    verdict: Optional[str] = None  # "OK" | "NON OK" | None

    def formatted(self) -> str:
        if self.value is None:
            return "—"
        if isinstance(self.value, str):
            return self.value
        if isinstance(self.value, float):
            if abs(self.value) < 1e-9:
                return "0"
            return f"{self.value:,.4g}"
        return str(self.value)


class Report:
    """Rapport structuré : métadonnées + sections (titre, items)."""

    def __init__(self, title: str = ""):
        self.title = title
        self.meta: dict = {}
        self.sections: List[tuple[str, List[Item]]] = []

    def add_meta(self, key: str, value) -> "Report":
        self.meta[key] = value
        return self

    def section(self, title: str, items: List[Item]) -> "Report":
        self.sections.append((title, items))
        return self

    def merge(self, other: "Report") -> "Report":
        self.sections.extend(other.sections)
        self.meta.update(other.meta)
        return self

    @property
    def ok(self) -> bool:
        for _, items in self.sections:
            for it in items:
                if it.verdict == "NON OK":
                    return False
        return True

    def find(self, label: str):
        for _, items in self.sections:
            for it in items:
                if it.label == label:
                    return it.value
        return None
