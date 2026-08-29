"""Vérifications de stabilité au glissement et au renversement."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

from core.results import Item


@dataclass
class StabilityConfig:
    friction_coeff: float = 0.5
    fs_sliding: float = 1.5
    fs_overturning: float = 1.5


def verifier_stabilite(poids_total_kN, V_total, M_total, largeur_base, config: StabilityConfig = None) -> List[Item]:
    cfg = config or StabilityConfig()

    # 1. Glissement
    f_stab_g = poids_total_kN * cfg.friction_coeff
    fs_g = f_stab_g / V_total if V_total > 0 else float("inf")
    # 2. Renversement
    bras = largeur_base / 2.0
    m_stab = poids_total_kN * bras
    fs_r = m_stab / M_total if M_total > 0 else float("inf")

    return [
        Item("Force stabilisante – glissement (kN)", f_stab_g, "kN"),
        Item(
            "Facteur de sécurité glissement",
            round(fs_g, 3),
            "",
            f"objectif ≥ {cfg.fs_sliding}",
            "OK" if fs_g >= cfg.fs_sliding else "NON OK",
        ),
        Item("Moment stabilisant (kN·m)", m_stab, "kN·m"),
        Item(
            "Facteur de sécurité renversement",
            round(fs_r, 3),
            "",
            f"objectif ≥ {cfg.fs_overturning}",
            "OK" if fs_r >= cfg.fs_overturning else "NON OK",
        ),
        Item("Coefficient de frottement sol μ", cfg.friction_coeff, ""),
    ]
