"""Paramètres des règlements sismiques et spectre de réponse normalisé.

Références :
  - RPS 2011 (Maroc), annexes nationales.
  - Eurocode 8 (EN 1998-1).
"""
from __future__ import annotations

from typing import Dict, List

REGULATIONS: List[str] = ["RPS 2011", "EC8"]
ZONES: List[str] = ["Zone 1 (0.07g)", "Zone 2 (0.10g)", "Zone 3 (0.13g)", "Zone 4 (0.17g)"]
SOILS: List[str] = ["S1 (1.00)", "S2 (1.20)", "S3 (1.40)", "S4 (1.80)"]

RPS_ACCELERATIONS: Dict[str, float] = {
    "Zone 1 (0.07g)": 0.07,
    "Zone 2 (0.10g)": 0.10,
    "Zone 3 (0.13g)": 0.13,
    "Zone 4 (0.17g)": 0.17,
}
RPS_SITES: Dict[str, dict] = {
    "S1 (1.00)": {"S": 1.00, "TB": 0.15, "TC": 0.4, "TD": 2.0},
    "S2 (1.20)": {"S": 1.20, "TB": 0.20, "TC": 0.6, "TD": 2.0},
    "S3 (1.40)": {"S": 1.40, "TB": 0.25, "TC": 0.9, "TD": 2.0},
    "S4 (1.80)": {"S": 1.80, "TB": 0.30, "TC": 1.0, "TD": 2.0},
}
EC8_ACCELERATIONS = RPS_ACCELERATIONS
EC8_SITES: Dict[str, dict] = {
    "S1 (1.00)": {"classe": "B", "S": 1.20, "TB": 0.15, "TC": 0.5, "TD": 2.0},
    "S2 (1.20)": {"classe": "C", "S": 1.15, "TB": 0.20, "TC": 0.6, "TD": 2.0},
    "S3 (1.40)": {"classe": "D", "S": 1.35, "TB": 0.20, "TC": 0.8, "TD": 2.0},
    "S4 (1.80)": {"classe": "E", "S": 1.40, "TB": 0.25, "TC": 0.9, "TD": 2.0},
}

BETA = 2.5  # facteur d'amplification du plateau du spectre


def get_site(regulation: str, soil: str) -> dict:
    if regulation == "RPS 2011":
        return RPS_SITES[soil]
    if regulation == "EC8":
        return EC8_SITES[soil]
    raise KeyError(f"Règlement inconnu : {regulation}")


def get_ag(zone: str) -> float:
    return RPS_ACCELERATIONS[zone]


def design_spectrum(regulation: str, soil: str, ag: float, T: float, q: float) -> float:
    """Spectre de calcul Sa(T) en fraction de g.

    Branches (EC8 / RPS) :
      T < TB   : Sa = ag * (1 + (BETA*S - 1) * T/TB)        (branche montante)
      TB<=T<=TC: Sa = ag * BETA * S                         (plateau)
      TC<T<=TD : Sa = ag * BETA * S * TC / T                (descendante)
      T > TD   : Sa = ag * BETA * S * TC * TD / T**2        (longue période)
    Réduction par le facteur de comportement q, avec plancher 0.2*ag.
    """
    sp = get_site(regulation, soil)
    S, TB, TC, TD = sp["S"], sp["TB"], sp["TC"], sp["TD"]
    if T < TB:
        sa_el = ag * (1.0 + (BETA * S - 1.0) * T / TB)
    elif T <= TC:
        sa_el = ag * BETA * S
    elif T <= TD:
        sa_el = ag * BETA * S * TC / T
    else:
        sa_el = ag * BETA * S * TC * TD / (T * T)
    if q > 1.0:
        return max(sa_el / q, 0.2 * ag)
    return sa_el
