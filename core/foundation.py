"""Dimensionnement et vérification du radier général (raft foundation).

Tous les radiers sont de type « radier général » :
  - Château d'eau & réservoir circulaire -> Circulaire ou Tronconique
  - Réservoir rectangulaire            -> Rectangulaire ou Carré

Géométries pris en charge :
  - Tronconique : disque circulaire de base (hauteur constante h_disk) surmonté
    d'un tronc de cône (hauteur h_cone). Grand diamètre = D_base (contact sol),
    petit diamètre = diamètre base tour/cuve + 2·débord (débord ≥ 0,50 m).
  - Circulaire / Rectangulaire / Carré : empreinte = empreinte cuve + 2·débord.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional, Tuple

from core.results import Item, Report

logger = logging.getLogger(__name__)

SHAPES = ["Circulaire", "Tronconique", "Rectangulaire", "Carré"]
MIN_OVERHANG = 0.50


@dataclass
class FoundationInput:
    shape: str = "Rectangulaire"
    D: float = 0.0
    D_base: float = 0.0
    D_sommet: float = 0.0
    L: float = 0.0
    B: float = 0.0
    h_f: float = 1.0
    # géométrie « débord / tronconique »
    overhang: float = MIN_OVERHANG
    h_disk: float = 0.50
    h_cone: float = 1.00
    tower_diameter: float = 0.0
    # matériaux
    q_adm: float = 200.0
    mu: float = 0.5
    fck: float = 25.0
    fy: float = 400.0
    cover: float = 0.05
    bar_diam: float = 0.016


def _punching(f: FoundationInput, load: dict, col_diameter: float):
    """Vérifie le poinçonnement (EC2 §6.4) pour charge concentrée. Retourne vEd, vRd, ok."""
    d = f.h_f - f.cover - f.bar_diam / 2.0
    col_d = col_diameter
    u = math.pi * (col_d + d)
    N = load["N_total_kN"]
    v_ed = N / (u * d) if (u * d) > 0 else 0.0
    gamma_c = 1.5
    k = min(1 + math.sqrt(200 / (d * 1000)), 2.0) if d > 0 else 1.0
    rho_l = 0.01
    v_rd = (0.18 / gamma_c) * k * math.pow(100 * rho_l * f.fck, 1 / 3) * 1e3
    v_rd = max(v_rd, 0.035 * k**1.5 * math.sqrt(f.fck) * 1e3)
    return v_ed, v_rd, v_ed <= v_rd


def _size_punching(f: FoundationInput, load, concentrated: bool,
                   col_diameter: float) -> None:
    """Pour charge concentrée, augmente h_f par pas jusqu'à ce que le poinçonnement passe."""
    if not concentrated:
        return
    loads = _loads_list(load)
    # on dimensionne sur la combinaison la plus lourde (max N) pour le poinçonnement
    load_p = max(loads, key=lambda l: l.get("N_total_kN", 0.0))
    for hf in [round(0.1 * i, 2) for i in range(10, 45)]:  # 1.0 -> 4.4 m
        f.h_f = hf
        _, _, ok = _punching(f, load_p, col_diameter)
        if ok:
            return
    f.h_f = 4.40  # plafond ; l'utilisateur devra rajouter du renfort


def _loads_list(load):
    """Normalise un load (dict unique ou liste de combinaisons) en liste."""
    if isinstance(load, (list, tuple)):
        return list(load)
    return [load]


def _sigma_max_combos(shape, f, loads) -> float:
    return max(_sigma_max(shape, f, l) for l in loads)


def _e_max_combos(loads) -> float:
    return max((l["M_total_kNm"] / l["N_total_kN"]) if l["N_total_kN"] > 0 else 0.0
               for l in loads)


def resolve_foundation(f: FoundationInput, tank: dict) -> FoundationInput:
    """Complète les dimensions effectives du radier (empreinte cuve + débord)."""
    D_tank = tank.get("D", 2.0 * tank.get("R_fut_base", 0.0))
    f.tower_diameter = D_tank
    ov = max(f.overhang, 0.0)
    if f.shape == "Circulaire":
        f.D = max(f.D, D_tank + 2.0 * ov)
    elif f.shape == "Tronconique":
        f.D_sommet = D_tank + 2.0 * ov
        f.D_base = max(f.D_base, f.D_sommet)
    elif f.shape == "Carré":
        side = max(tank.get("L", 0.0), tank.get("B", 0.0)) + 2.0 * ov
        f.L = max(f.L, side)
        f.B = f.L
    else:  # Rectangulaire
        f.L = max(f.L, tank.get("L", 0.0) + 2.0 * ov)
        f.B = max(f.B, tank.get("B", 0.0) + 2.0 * ov)
    return f


def _area_section(shape: str, f: FoundationInput) -> Tuple[float, float, float, float]:
    """Retourne (Aire m², Module W m³, demi-noye L/6 m, dimension caract. m)."""
    if shape == "Circulaire":
        R = f.D / 2.0
        A = math.pi * R**2
        W = math.pi * R**3 / 4.0
        return A, W, R / 4.0, f.D          # noyau circulaire = R/4 = D/8
    if shape == "Tronconique":
        Rb = f.D_base / 2.0
        A = math.pi * Rb**2                # surface de contact (disque de base)
        W = math.pi * Rb**3 / 4.0
        return A, W, Rb / 4.0, f.D_base
    if shape == "Carré":
        A = f.L**2
        W = f.L**3 / 6.0
        return A, W, f.L / 6.0, f.L
    A = f.L * f.B
    W = f.L * f.B**2 / 6.0
    return A, W, f.B / 6.0, f.B


def _sigma_max(shape: str, f: FoundationInput, load: dict) -> float:
    N = load["N_total_kN"]
    M = load["M_total_kNm"]
    A, W, _, _ = _area_section(shape, f)
    return N / A + (M / W if W > 0 else 0.0)


def _verifier_load(load: dict, f: FoundationInput, concentrated: bool):
    """Vérifie une combinaison de charge et retourne un dict de résultats."""
    N = load["N_total_kN"]
    V = load["V_total_kN"]
    M = load["M_total_kNm"]
    A, W, kern, Lc = _area_section(f.shape, f)
    sigma_moy = N / A
    sigma_diff = M / W if W > 0 else 0.0
    sigma_max = sigma_moy + sigma_diff
    sigma_min = sigma_moy - sigma_diff
    e = M / N if N > 0 else 0.0
    f_stab = N * f.mu
    fs_g = f_stab / V if V > 0 else float("inf")
    m_stab = N * (Lc / 2.0)
    fs_r = m_stab / M if M > 0 else float("inf")
    res = {"N": N, "V": V, "M": M, "A": A, "W": W, "kern": kern, "Lc": Lc,
           "sigma_moy": sigma_moy, "sigma_max": sigma_max, "sigma_min": sigma_min,
           "e": e, "m_stab": m_stab, "fs_g": fs_g, "fs_r": fs_r}
    if concentrated:
        col_d = load.get("col_diameter_m", Lc * 0.3)
        v_ed, v_rd, ok = _punching(f, load, col_d)
        res["punch"] = (v_ed, v_rd, ok)
        res["col_d"] = col_d
    return res


def analyser_fondation(load: dict, f: FoundationInput, concentrated: bool = False,
                       tank: dict = None) -> Tuple[Optional[Report], Optional[str]]:
    try:
        if tank is not None:
            resolve_foundation(f, tank)
        loads = _loads_list(load)
        verifs = [_verifier_load(l, f, concentrated) for l in loads]
        worst = max(verifs, key=lambda r: r["sigma_max"])

        vol_beton = None
        if f.shape == "Tronconique":
            Rb, Rs = f.D_base / 2.0, f.D_sommet / 2.0
            vol_disk = math.pi * Rb**2 * f.h_disk
            vol_frust = math.pi / 12.0 * f.h_cone * (f.D_base**2 + f.D_base * f.D_sommet + f.D_sommet**2)
            vol_beton = vol_disk + vol_frust

        report = Report("Vérification fondation (radier)")
        report.add_meta("type", "fondation")
        report.add_meta("sigma_max_kPa", worst["sigma_max"])
        report.add_meta("sigma_min_kPa", worst["sigma_min"])
        report.add_meta("combinaisons_verifiees", len(verifs))

        geom_items = [
            Item("Forme", f.shape),
            Item("Débord par côté (m)", f.overhang, "m", f"≥ {MIN_OVERHANG} m"),
            Item("Aire A (m²)", worst["A"], "m²"),
            Item("Module résistant W (m³)", worst["W"], "m³"),
            Item("Épaisseur h_f (m)", f.h_f, "m"),
        ]
        if f.shape == "Tronconique":
            geom_items += [
                Item("Diamètre base D_base (m)", f.D_base, "m", "contact sol"),
                Item("Diamètre sommet D_sommet (m)", f.D_sommet, "m", "= tour + 2·débord"),
                Item("Hauteur disque base (m)", f.h_disk, "m"),
                Item("Hauteur tronc (m)", f.h_cone, "m"),
                Item("Volume béton (m³)", vol_beton, "m³"),
            ]
        elif f.shape == "Circulaire":
            geom_items.append(Item("Diamètre D (m)", f.D, "m"))
        else:
            geom_items.append(Item("Dimensions L x B (m)", f"{f.L:.2f} x {f.B:.2f}", ""))
        report.section("GÉOMÉTRIE RADIER", geom_items)

        if len(verifs) == 1:
            # Rétro-compatibilité : section unique intitulée comme avant
            v = verifs[0]
            report.section("PRESSIONS DE CONTACT", [
                Item("Contrainte moyenne σm (kPa)", v["sigma_moy"], "kPa"),
                Item("Contrainte max σmax (kPa)", v["sigma_max"], "kPa",
                     f"q_adm = {f.q_adm} kPa", "OK" if v["sigma_max"] <= f.q_adm else "NON OK"),
                Item("Contrainte min σmin (kPa)", v["sigma_min"], "kPa",
                     "≥ 0 (pas de décollement)", "OK" if v["sigma_min"] >= -1e-6 else "NON OK"),
                Item("Excentricité e (m)", v["e"], "m",
                     f"≤ noyau {v['kern']:.3f} m", "OK" if v["e"] <= v["kern"] + 1e-6 else "NON OK"),
            ])
            report.section("STABILITÉ GLOBALE", [
                Item("Moment stabilisant N·L/2 (kN·m)", v["m_stab"], "kN·m"),
                Item("FS renversement (radier)", round(v["fs_r"], 3), "", "≥ 1.5",
                     "OK" if v["fs_r"] >= 1.5 else "NON OK"),
                Item("FS glissement", round(v["fs_g"], 3), "", "≥ 1.5",
                     "OK" if v["fs_g"] >= 1.5 else "NON OK"),
            ])
            if concentrated:
                v_ed, v_rd, ok = v["punch"]
                report.section("POINÇONNEMENT (charge concentrée)", [
                    Item("Diamètre colonne équiv. (m)", v["col_d"], "m"),
                    Item("Effort tranchant vEd (kPa)", v_ed, "kPa",
                         "EC2 §6.4 (ρl≈1 %)", "OK" if ok else "NON OK"),
                    Item("Résistance vRd,c (kPa)", v_rd, "kPa"),
                ])
        else:
            # Toutes les combinaisons sont vérifiées individuellement
            for idx, (l, v) in enumerate(zip(loads, verifs)):
                case = l.get("case", f"Combo {idx+1}")
                report.section(f"VÉRIFICATION COMBINAISON — {case}", [
                    Item("Poids total N (kN)", v["N"], "kN"),
                    Item("Effort tranchant V (kN)", v["V"], "kN"),
                    Item("Moment M (kN·m)", v["M"], "kN·m"),
                    Item("Contrainte max σmax (kPa)", v["sigma_max"], "kPa",
                         f"q_adm = {f.q_adm} kPa", "OK" if v["sigma_max"] <= f.q_adm else "NON OK"),
                    Item("Contrainte min σmin (kPa)", v["sigma_min"], "kPa",
                         "≥ 0", "OK" if v["sigma_min"] >= -1e-6 else "NON OK"),
                    Item("Excentricité e (m)", v["e"], "m",
                         f"≤ noyau {v['kern']:.3f} m", "OK" if v["e"] <= v["kern"] + 1e-6 else "NON OK"),
                    Item("FS renversement", round(v["fs_r"], 3), "", "≥ 1.5",
                         "OK" if v["fs_r"] >= 1.5 else "NON OK"),
                    Item("FS glissement", round(v["fs_g"], 3), "", "≥ 1.5",
                         "OK" if v["fs_g"] >= 1.5 else "NON OK"),
                ])
                if concentrated:
                    v_ed, v_rd, ok = v["punch"]
                    report.section(f"POINÇONNEMENT — {case}", [
                        Item("Diamètre colonne équiv. (m)", v["col_d"], "m"),
                        Item("Effort tranchant vEd (kPa)", v_ed, "kPa",
                             "EC2 §6.4 (ρl≈1 %)", "OK" if ok else "NON OK"),
                        Item("Résistance vRd,c (kPa)", v_rd, "kPa"),
                    ])
            report.section("SYNTHÈSE (cas le plus défavorable)", [
                Item("σmax max toutes combos (kPa)", worst["sigma_max"], "kPa",
                     f"q_adm = {f.q_adm} kPa", "OK" if worst["sigma_max"] <= f.q_adm else "NON OK"),
                Item("σmin min toutes combos (kPa)", worst["sigma_min"], "kPa",
                     "≥ 0", "OK" if worst["sigma_min"] >= -1e-6 else "NON OK"),
                Item("e max toutes combos (m)", worst["e"], "m",
                     f"≤ noyau {worst['kern']:.3f} m", "OK" if worst["e"] <= worst["kern"] + 1e-6 else "NON OK"),
            ])
        return report, None
    except Exception as e:  # noqa: BLE001
        logger.exception("Erreur fondation")
        return None, f"Erreur fondation : {e}"


def auto_dimensionner(load: dict, shape: str, q_adm: float, mu: float = 0.5,
                       overhang: float = MIN_OVERHANG, tank: dict = None,
                       concentrated: bool = False) -> FoundationInput:
    """Propose un radier vérifiant σmax ≤ q_adm et e ≤ noyau, pour TOUTES les combinaisons.

    ``load`` peut être un dict unique (rétro-compatibilité) ou une liste de
    combinaisons (cas vide / plein). La dimension retenue est la plus défavorable.
    """
    loads = _loads_list(load)
    N_ref = max(max(l["N_total_kN"], 1.0) for l in loads)
    M_ref = max(l["M_total_kNm"] for l in loads)
    e = M_ref / N_ref
    e_max = _e_max_combos(loads)
    A_req = 1.3 * N_ref / q_adm
    D_tank = tank.get("D", 2.0 * tank.get("R_fut_base", 0.0)) if tank else 0.0
    ov = max(overhang, 0.0)
    col_d = load.get("col_diameter_m", 2.0 * (tank.get("R_fut_base", 0.0) if tank else 0.0)) if not isinstance(load, list) else \
        max((l.get("col_diameter_m", 2.0 * (tank.get("R_fut_base", 0.0) if tank else 0.0)) for l in loads))

    if shape in ("Circulaire", "Tronconique"):
        c_min = 8.0 * e_max if e_max > 0 else 1.0      # noyau circulaire = D/8
        D_area = 2.0 * math.sqrt(A_req / math.pi)
        D_min = D_tank + 2.0 * ov
        D_base = max(D_area, c_min, D_min)
        f = FoundationInput(shape=shape, D_base=D_base, overhang=ov, tower_diameter=D_tank,
                            h_disk=0.50, h_cone=1.00, q_adm=q_adm, mu=mu)
        if shape == "Circulaire":
            f.D = D_base
        else:
            f.D_sommet = D_tank + 2.0 * ov
        guard = 0
        while _sigma_max_combos(shape, f, loads) > q_adm and guard < 200:
            if shape == "Circulaire":
                f.D *= 1.05
                f.D_base = f.D
            else:
                f.D_base *= 1.05
            guard += 1
        f.D_base = math.ceil(f.D_base * 2) / 2
        f.D_base = max(f.D_base, 8.0 * e_max if e_max > 0 else 0.0)
        if shape == "Circulaire":
            f.D = f.D_base
        _size_punching(f, load, concentrated, col_d)
        return f
    elif shape == "Carré":
        c_min = 6.0 * e_max if e_max > 0 else 1.0        # noyau carré = côté/6
        side_area = math.sqrt(A_req)
        side_min = (max(tank.get("L", 0.0), tank.get("B", 0.0)) + 2.0 * ov) if tank else side_area
        side = max(side_area, c_min * 1.2, side_min)
        f = FoundationInput(shape="Carré", L=side, B=side, overhang=ov, q_adm=q_adm, mu=mu)
        guard = 0
        while _sigma_max_combos("Carré", f, loads) > q_adm and guard < 200:
            f.L *= 1.05
            f.B = f.L
            guard += 1
        f.L = math.ceil(f.L * 2) / 2
        f.B = f.L
        f.B = max(f.B, 6.0 * e_max if e_max > 0 else 0.0)
        _size_punching(f, load, concentrated, col_d)
        return f
    else:
        c_min = 6.0 * e_max if e_max > 0 else 1.0        # noyau rect. = B/6
        L_area = math.sqrt(A_req)
        L_min = (tank.get("L", 0.0) + 2.0 * ov) if tank else L_area
        B_min = (tank.get("B", 0.0) + 2.0 * ov) if tank else L_area
        L = max(L_area, c_min * 1.2, L_min)
        B = max(A_req / L, c_min, B_min)
        f = FoundationInput(shape="Rectangulaire", L=L, B=B, overhang=ov, q_adm=q_adm, mu=mu)
        guard = 0
        while _sigma_max_combos("Rectangulaire", f, loads) > q_adm and guard < 200:
            f.L *= 1.05
            f.B *= 1.05
            guard += 1
        f.L = math.ceil(f.L * 2) / 2
        f.B = math.ceil(f.B * 2) / 2
        f.B = max(f.B, 6.0 * e_max if e_max > 0 else 0.0)
        _size_punching(f, load, concentrated, col_d)
        return f
