"""Calcul des armatures du radier, des parois/coque, des coupoles et des dalles de couverture.

Norme couplée automatiquement au règlement sismique :
  - RPS 2011 -> BAEL 91 modifié
  - EC8      -> Eurocode 2 (EN 1992-1-1)

Méthodes de PRÉDIMENSIONNEMENT documentées (hypothèses explicites, à titre indicatif) :
  - Radier : moment par m de largeur M = p·L²/10 (méthode des coefficients).
  - Parois circulaires : CEINTURES (armatures annulaires horizontales, tension T = p·R)
    distribuées sur la hauteur + flexion verticale en console.
  - Châteaux d'eau (surélevés, circulaires/tronconiques) : COUPOLES sup et inf,
    flèche minimale selon Fascicule 74 du CCAGT : flèche_sup ≥ D/10, flèche_inf ≥ d/8.
  - Réservoirs rectangulaires/carrés (au sol, semi-enterrés, enterrés) : DALLES DE
    COUVERTURE (toit) soumises à leur poids propre + charge d'exploitation + charge des
    LANTERNEAUX (ouvertures/aérations).
  - FISSURATION : tous les éléments en contact de l'eau font l'objet d'une vérification
    d'ouverture de fissure (Fascicule 74 / EC2 7.3.4). L'armature retenue est la
    PLUS PRÉPONDÉRANTE entre l'effort (flexion ou tension) et la fissuration.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

from core.foundation import FoundationInput, _area_section
from core.results import Item, Report

logger = logging.getLogger(__name__)
GAMMA_W = 9.81    # kN/m³
GAMMA_B = 25.0    # kN/m³ (béton)
E_S = 200000.0    # MPa


def _norme(regulation: str) -> str:
    return "BAEL 91" if regulation == "RPS 2011" else "EC2"


def _fctm(fck_mpa: float, norme: str) -> float:
    """Résistance tensile moyenne (MPa)."""
    if norme == "EC2":
        return 0.3 * fck_mpa ** (2 / 3)
    return 0.8 * math.sqrt(fck_mpa)          # BAEL (approche conservative)


def _as_per_m(M_kNm: float, d_mm: float, fy_mpa: float) -> float:
    """Acier nécessaire (mm²/m) pour un moment M par m de largeur."""
    fyd = fy_mpa / 1.15
    M = M_kNm * 1e6                          # N·mm
    z = 0.9 * d_mm
    return M / (fyd * z)


def _as_min_per_m(fck_mpa: float, norme: str) -> float:
    if norme == "EC2":
        fctm = 0.3 * fck_mpa ** (2 / 3)
        return max(0.26 * fctm / 400.0, 0.0013) * 1e6  # mm²/m
    return 0.0023 * 1e6  # BAEL (approche conservative)


def _choisir_barres(As_mm2_m: float) -> Tuple[str, str, float]:
    """Choisit Ø et enrobage/espacement minimaux couvrant As (mm²/m)."""
    best = None
    for diam in (8, 10, 12, 14, 16, 20, 25):
        a = math.pi / 4 * (diam / 1000.0) ** 2        # m²/barre
        for s in (0.30, 0.25, 0.20, 0.15, 0.12, 0.10):
            n = 1.0 / s                                # barres par mètre
            As_prov = a * n * 1e6                      # mm²/m
            if As_prov >= As_mm2_m:
                if best is None or As_prov < best[2]:
                    best = (f"Ø{diam}", f"{int(s*1000)} cm", As_prov)
    if best is None:
        return "Ø25", "10 cm", As_mm2_m
    return best


# ============================================================== FISSURATION
def _as_crack(X: float, d_mm: float, h_mm: float, fck_mpa: float, norme: str,
              w_max: float, mode: str) -> float:
    """Acier (mm²/m) nécessaire pour limiter l'ouverture de fissure à w_max.

    X = effort : M (N·mm/m) en flexion, ou N (N/m) en traction pure.
    Formule simplifiée EC2 7.3.4 (indicative) : w = s_r,max·(ε_sm − ε_cm).
    """
    fctm = _fctm(fck_mpa, norme)
    h_c_eff = min(2.5 * (h_mm - d_mm), h_mm / 2.0)
    if h_c_eff <= 0:
        h_c_eff = max(h_mm * 0.5, 1.0)
    A_c_eff = h_c_eff          # aire tendue efficace par m (b = 1000 mm)
    s_r = 1.3 * h_c_eff        # mm
    Y = X / (0.9 * d_mm) if mode == "flexion" else X   # N/m
    num = (s_r / E_S) * (Y - 0.4 * fctm * A_c_eff)
    return max(num / w_max, 0.0) if num > 0 else 0.0


def _w_k(As: float, X: float, d_mm: float, h_mm: float, fck_mpa: float,
         norme: str, mode: str) -> Tuple[float, float]:
    """Retourne (σs MPa, w_k mm) pour une armature As (mm²/m)."""
    fctm = _fctm(fck_mpa, norme)
    h_c_eff = min(2.5 * (h_mm - d_mm), h_mm / 2.0)
    if h_c_eff <= 0:
        h_c_eff = max(h_mm * 0.5, 1.0)
    A_c_eff = h_c_eff
    rho_eff = As / A_c_eff if As > 0 else 1e9
    if mode == "flexion":
        sigma_s = X / (0.9 * d_mm * As) if As > 0 else 0.0
    else:
        sigma_s = X / As if As > 0 else 0.0
    eps = max(sigma_s - 0.4 * fctm / rho_eff, 0.0) / E_S
    w = 1.3 * h_c_eff * eps
    return sigma_s, w


def _gouverne(items: List[Item], titre: str, M_des, M_serv, d_mm: float, h_mm: float,
              fy: float, fck: float, norme: str, w_max: float, as_min: float,
              mode: str = "flexion", crack: bool = True) -> float:
    """Retient l'armature prépondérante.

    - crack=True  : élément en contact d'eau -> flexion + fissuration (Fasc. 74),
                    armature la + exigeante des deux.
    - crack=False : hors contact d'eau -> armature de flexion FP/FPP max (ELU-ELA),
                    sans vérification de fissure.
    """
    fyd = fy / 1.15
    if mode == "flexion":
        As_flex = _as_per_m(M_des, d_mm, fy)
        X_des = M_des * 1e6
        X_serv = M_serv * 1e6
    else:
        As_flex = M_des * 1000.0 / fyd          # M_des = T (kN/m)
        X_des = M_des * 1000.0                  # N/m
        X_serv = M_serv * 1000.0
    if not crack:
        As_gov = max(As_flex, as_min)
        bars = _choisir_barres(As_gov)
        items += [
            Item(f"{titre} - As flexion (mm²/m)", As_flex, "mm²/m"),
            Item(f"{titre} - As retenue FP/FPP max (mm²/m)", As_gov, "mm²/m",
                 "ELU-ELA (hors contact eau : pas de fissuration)"),
            Item(f"{titre} - Armatures proposées", f"{bars[0]} / {bars[1]}", "",
                 f"As = {bars[2]:.0f} mm²/m",
                 "OK" if bars[2] >= As_gov else "NON OK"),
        ]
        return As_gov
    As_crack = _as_crack(X_serv, d_mm, h_mm, fck, norme, w_max, mode)
    As_gov = max(As_flex, As_crack, as_min)
    case = "fissuration" if As_crack >= As_flex else "flexion"
    bars = _choisir_barres(As_gov)
    sigma_s, w = _w_k(As_gov, X_serv, d_mm, h_mm, fck, norme, mode)
    items += [
        Item(f"{titre} - As flexion (mm²/m)", As_flex, "mm²/m"),
        Item(f"{titre} - σs service (MPa)", round(sigma_s, 1), "MPa"),
        Item(f"{titre} - Ouverture fissure w_k (mm)", round(w, 3), "mm",
             f"limite {w_max} mm (Fasc. 74)"),
        Item(f"{titre} - As fissuration (mm²/m)", As_crack, "mm²/m"),
        Item(f"{titre} - As GOUVERNANT (mm²/m)", As_gov, "mm²/m",
             f"cas prépondérant : {case}"),
        Item(f"{titre} - Armatures proposées", f"{bars[0]} / {bars[1]}", "",
             f"As = {bars[2]:.0f} mm²/m",
             "OK" if bars[2] >= As_gov else "NON OK"),
    ]
    return As_gov


def _d_eff(e_mm: float, f: FoundationInput) -> float:
    c = f.cover * 1000.0
    b = f.bar_diam * 1000.0
    return max(e_mm - c - b / 2.0, 0.10 * e_mm)


def _section_radierr(items: List[Item], nom: str, p, L, e_mm, d_mm, fy, norme, fck, Mx, My=None, crack=True):
    as_min = _as_min_per_m(fck, norme)
    items.append(Item(f"Moment Mx ({nom}) (kN·m/m)", Mx, "kN·m/m"))
    _gouverne(items, f"Radier x ({nom})", Mx, Mx / 1.5, d_mm, e_mm, fy, fck, norme, 0.20, as_min, crack=crack)
    if My is not None:
        items.append(Item(f"Moment My ({nom}) (kN·m/m)", My, "kN·m/m"))
        _gouverne(items, f"Radier y ({nom})", My, My / 1.5, d_mm, e_mm, fy, fck, norme, 0.20, as_min, crack=crack)


# ============================================================== CEINTURES
def _section_ceintures(items: List[Item], R: float, H: float, kh: float, fy: float,
                        norme: str, fck: float, e_mm: float, f: FoundationInput) -> None:
    """Ceintures = armatures annulaires HORIZONTALES (tension circulaire T = p·R).

    Réparties sur la hauteur (max à la base). Vérification fissuration car la cuve
    est en contact permanent de l'eau (Fasc. 74).
    """
    as_min = _as_min_per_m(fck, norme)
    d_mm = _d_eff(e_mm, f)

    def tension(z: float) -> float:
        return GAMMA_W * (H - z) * (1.0 + kh) * R   # kN/m

    T_base = tension(0.0)
    items.append(Item("Rayon paroi R (m)", R, "m", "cuve circulaire"))
    items.append(Item("Tension annulaire max T (kN/m)", T_base, "kN/m",
                      "T = γ·H·(1+kh)·R  [base]"))
    # fissure en traction pure : effort de service = hydrostatique seul
    _gouverne(items, "Ceintures (base)", T_base, GAMMA_W * H * R, d_mm, e_mm, fy, fck,
              norme, 0.20, as_min, mode="tension")
    niv = max(4, min(20, int(round(H))))
    items.append(Item("Nombre de niveaux de ceintures", niv + 1, "",
                      "réparties sur toute la hauteur H"))
    for i in range(1, niv):
        z = H * i / niv
        Tz = tension(z)
        _gouverne(items, f"Ceintures z={z:.1f} m", Tz, GAMMA_W * (H - z) * R, d_mm, e_mm,
                  fy, fck, norme, 0.20, as_min, mode="tension")
    btop = _choisir_barres(as_min)
    items.append(Item("Ceinture sommet (couronnement)", f"As mini = {as_min:.0f} mm²/m", "mm²/m",
                      f"répartition minimale {btop[0]}/{btop[1]}", "OK"))


# ============================================================== COUPOLES
def _coupole_geom(R: float, flc: float):
    """R, rayon de portée ; flc = flèche/diamètre minimale (Fasc. 74)."""
    D = 2.0 * R
    f = flc * D                 # flèche (m)
    Rs = (D**2 / 4.0 + f**2) / (2.0 * f)   # rayon de la sphère
    e = max(0.15, D / 35.0)     # épaisseur indicative (m)
    return D, f, Rs, e


def _section_coupoles(items: List[Item], geom: dict, H_eau: float,
                      fy: float, fck: float, norme: str, f: FoundationInput) -> None:
    """Coupoles sup/inf (saisies 1re page) + ceintures sup/inf (anneaux de liaison).

    Fasc. 74 : flèche sup ≥ D/10, flèche inf ≥ d/8. Membrane sphérique : tension
    annulaire ≈ p·Rs/2.
      - Coupole SUP : hors contact eau -> FP/FPP max (ELU).
      - Ceinture SUP : anneau cuve ↔ coupole sup (en limite d'eau) -> fissuration.
      - Coupole INF : contact eau -> fissuration.
      - Ceinture INF : anneau fût ↔ cuve ↔ coupole inf -> fissuration.
    """
    as_min = _as_min_per_m(fck, norme)
    Rf = geom.get("R_fond", 0.0); Rs = geom.get("R_surface", 0.0)
    D_sup = geom.get("coupole_sup_D", 2.0 * Rs)
    f_sup = geom.get("coupole_sup_f", D_sup / 10.0)
    e_csup = geom.get("coupole_sup_e", max(0.15, D_sup / 35.0))
    d_inf = geom.get("coupole_inf_d", 2.0 * Rf)
    f_inf = geom.get("coupole_inf_f", d_inf / 8.0)
    e_cinf = geom.get("coupole_inf_e", max(0.15, d_inf / 35.0))
    # Ceintures sup/inf : anneaux de liaison à section rectangulaire (largeur l, hauteur h)
    csup_l = geom.get("ceinture_sup_l", 0.40)
    csup_h = geom.get("ceinture_sup_h", 0.60)
    cinf_l = geom.get("ceinture_inf_l", 0.50)
    cinf_h = geom.get("ceinture_inf_h", 0.70)
    Rs_s = (D_sup**2 / 4.0 + f_sup**2) / (2.0 * f_sup) if f_sup > 0 else D_sup / 2.0
    Rs_i = (d_inf**2 / 4.0 + f_inf**2) / (2.0 * f_inf) if f_inf > 0 else d_inf / 2.0
    d_s = _d_eff(e_csup * 1000.0, f)
    d_i = _d_eff(e_cinf * 1000.0, f)
    d_cs = _d_eff(csup_h * 1000.0, f)
    d_ci = _d_eff(cinf_h * 1000.0, f)

    # ---- COUPOLE SUPERIEURE (hors eau) ----
    T_s = GAMMA_B * e_csup * Rs_s / 2.0     # poids propre (kPa->kN/m)
    items += [
        Item("COUPOLE SUPÉRIEURE", "", "", "Fasc. 74 : flèche ≥ D/10 — hors contact eau"),
        Item("  Diamètre sommet D (m)", round(D_sup, 3), "m"),
        Item("  Flèche f (m)", round(f_sup, 3), "m", f"≥ D/10 = {D_sup/10:.3f} m"),
        Item("  Rayon sphère Rs (m)", round(Rs_s, 3), "m"),
        Item("  Épaisseur e (m)", round(e_csup, 3), "m", "saisie 1re page (poids pris en compte)"),
    ]
    _gouverne(items, "Coupole sup (coque)", T_s, T_s, d_s, e_csup * 1000.0, fy, fck,
              norme, 0.20, as_min, mode="tension", crack=False)
    # ---- CEINTURE SUP (anneau liaison cuve ↔ coupole sup) ----
    items += [
        Item("CEINTURE SUP (cuve ↔ coupole sup)", "", "", "anneau de liaison — limite eau"),
        Item("  Tension anneau T (kN/m)", round(T_s, 1), "kN/m"),
        Item("  Largeur anneau l (m)", round(csup_l, 3), "m", "saisie 1re page"),
        Item("  Hauteur anneau h (m)", round(csup_h, 3), "m", "saisie 1re page"),
    ]
    _gouverne(items, "Ceinture sup (anneau)", T_s, T_s, d_cs, csup_h * 1000.0, fy, fck,
              norme, 0.20, as_min, mode="tension", crack=True)

    # ---- COUPOLE INFÉRIEURE (contact eau) ----
    T_i = (GAMMA_W * H_eau + GAMMA_B * e_cinf) * Rs_i / 2.0
    items += [
        Item("COUPOLE INFÉRIEURE", "", "", "Fasc. 74 : flèche ≥ d/8 — contact eau"),
        Item("  Diamètre base d (m)", round(d_inf, 3), "m"),
        Item("  Flèche f (m)", round(f_inf, 3), "m", f"≥ d/8 = {d_inf/8:.3f} m"),
        Item("  Rayon sphère Rs (m)", round(Rs_i, 3), "m"),
        Item("  Épaisseur e (m)", round(e_cinf, 3), "m", "saisie 1re page (poids pris en compte)"),
    ]
    _gouverne(items, "Coupole inf (coque)", T_i, (GAMMA_W * H_eau + GAMMA_B * e_cinf) * Rs_i / 2.0,
              d_i, e_cinf * 1000.0, fy, fck, norme, 0.20, as_min, mode="tension", crack=True)
    # ---- CEINTURE INF (anneau liaison fût ↔ cuve ↔ coupole inf) ----
    T_inf_anneau = T_i + GAMMA_W * H_eau * (d_inf / 2.0)   # coupole + culot paroi
    items += [
        Item("CEINTURE INF (fût ↔ cuve ↔ coupole inf)", "", "", "anneau de liaison — contact eau"),
        Item("  Tension anneau T (kN/m)", round(T_inf_anneau, 1), "kN/m"),
        Item("  Largeur anneau l (m)", round(cinf_l, 3), "m", "saisie 1re page"),
        Item("  Hauteur anneau h (m)", round(cinf_h, 3), "m", "saisie 1re page"),
    ]
    _gouverne(items, "Ceinture inf (anneau)", T_inf_anneau, T_inf_anneau, d_ci, cinf_h * 1000.0,
              fy, fck, norme, 0.20, as_min, mode="tension", crack=True)


# ============================================================== COUVERTURE + LANTERNEAUX
def _section_couverture(items: List[Item], span_x: float, span_y: float, H_eau: float,
                        fy: float, fck: float, norme: str, f: FoundationInput,
                        q_couv: float, Q_lanterneau: float, e_couv: float) -> None:
    """Dalle de couverture (toit) d'un réservoir + charge des lanterneaux.

    Dalle bidirectionnelle : M = q·L²/10. q = poids propre + charge d'exploitation.
    Toit hors contact d'eau -> FP/FPP max (ELU). Épaisseur saisie par l'opérateur.
    """
    as_min = _as_min_per_m(fck, norme)
    e = e_couv
    d_c = _d_eff(e * 1000.0, f)
    poids = GAMMA_B * e
    q = poids + q_couv
    Mx = q * span_x**2 / 10.0
    My = q * span_y**2 / 10.0
    items += [
        Item("DALLE DE COUVERTURE", "", "", "toit du réservoir — hors contact eau"),
        Item("  Épaisseur dalle e (m)", round(e, 3), "m", "saisie opérateur (poids pris en compte)"),
        Item("  Charge d'exploitation q_couv (kN/m²)", q_couv, "kN/m²"),
        Item("  Charge lanterneau Q (kN)", Q_lanterneau, "kN",
             "charge concentrée localisée (aération/ouverture)"),
        Item("  Moment Mx (kN·m/m)", round(Mx, 2), "kN·m/m"),
    ]
    _gouverne(items, "Couverture x", Mx, Mx / 1.5, d_c, e * 1000.0, fy, fck,
              norme, 0.20, as_min, crack=False)
    items.append(Item("  Moment My (kN·m/m)", round(My, 2), "kN·m/m"))
    _gouverne(items, "Couverture y", My, My / 1.5, d_c, e * 1000.0, fy, fck,
              norme, 0.20, as_min, crack=False)
    items.append(Item("Note lanterneaux",
                      f"Renforcer localement sous chaque lanterneau (manchons/chaînages) pour Q = {Q_lanterneau:.0f} kN.",
                      "", "vérification à l'effort tranchant local recommandée"))


def _section_fut(items: List[Item], R_base: float, e_fut: float, M_base: float,
                fy: float, fck: float, norme: str, f: FoundationInput) -> None:
    """Fût/colonne du château d'eau (porte la cuve surélevée).

    Hors contact d'eau -> FP/FPP max (ELU-ELA). Colonne : As TOTALE = M/(0.9·d·fyd),
    armature minimale = 0.0023·A_gross (BAEL). Moment M_base = moment total à la base.
    """
    fyd = fy / 1.15
    d_fut = _d_eff(e_fut * 1000.0, f)
    A_gross = math.pi * (R_base ** 2) * 1e6        # mm² (section brute)
    as_min = 0.0023 * A_gross if norme == "BAEL 91" else 0.0013 * A_gross
    As_flex = M_base * 1e6 / (fyd * 0.9 * d_fut)   # mm² (totale)
    As_gov = max(As_flex, as_min)
    # choix de barres (Ø puis nombre) couvrant l'As totale
    best = None
    for diam in (25, 32, 40, 50):
        a = math.pi / 4 * (diam / 1000.0) ** 2 * 1e6   # mm²/barre
        n = max(1, math.ceil(As_gov / a))
        prov = a * n
        if best is None or prov < best[2]:
            best = (f"Ø{diam}", n, prov)
    items += [
        Item("TOUR / FÛT", "", "", "hors contact eau -> FP/FPP max (ELU)"),
        Item("  Rayon base fût R (m)", R_base, "m"),
        Item("  Épaisseur fût e (m)", round(e_fut, 3), "m", "saisie opérateur"),
        Item("  Moment base M (kN·m)", round(M_base, 1), "kN·m"),
        Item("  As flexion totale (mm²)", As_flex, "mm²"),
        Item("  As mini colonne (mm²)", round(as_min, 0), "mm²"),
        Item("  As retenue FP/FPP max (mm²)", As_gov, "mm²",
             "ELU-ELA (pas de fissuration)"),
        Item("  Armatures proposées", f"{best[0]} x{best[1]}", "",
             f"As = {best[2]:.0f} mm²", "OK" if best[2] >= As_gov else "NON OK"),
    ]


# ============================================================== CALCUL GLOBAL
def calculer_armatures(analysis_report: Report, foundation_report: Report,
                        f: FoundationInput, regulation: str, geom: dict,
                        opts: Optional[Dict] = None
                        ) -> Tuple[Optional[Report], Optional[str]]:
    try:
        norme = _norme(regulation)
        fy = f.fy
        w_max = (opts or {}).get("w_max", 0.20)
        q_couv = (opts or {}).get("q_couv", 1.50)
        Q_lan = (opts or {}).get("Q_lanterneau", 10.0)
        # épaisseurs saisies en m par l'opérateur -> converties en mm
        e_cuve = (opts or {}).get("e_cuve", None)
        e_csup = (opts or {}).get("e_csup", None)
        e_cinf = (opts or {}).get("e_cinf", None)
        e_couv = (opts or {}).get("e_couv", None)
        e_cuve_mm = e_cuve * 1000.0 if e_cuve is not None else None
        e_csup_mm = e_csup * 1000.0 if e_csup is not None else None
        e_cinf_mm = e_cinf * 1000.0 if e_cinf is not None else None
        e_couv_mm = e_couv * 1000.0 if e_couv is not None else None

        sigma_max = foundation_report.find("Contrainte max σmax (kPa)")
        p = max(sigma_max if isinstance(sigma_max, (int, float)) else f.q_adm, 0.0)

        e_radier = f.h_f * 1000.0
        d_radier = _d_eff(e_radier, f)

        report = Report("Calcul des armatures")
        report.add_meta("type", "armatures")
        report.section("NORME", [
            Item("Norme de ferraillage", norme, "", "couplée automatiquement au règlement sismique"),
            Item("Acier fy (MPa)", fy, "MPa"),
            Item("Enrobage (m)", f.cover, "m", "contact eau -> Cf. Fasc. 74"),
            Item("Hauteur utile radier d (mm)", round(d_radier, 1), "mm"),
            Item("Limite fissuration w_max (mm)", w_max, "mm", "Fasc. 74 CCAGT"),
        ])

        # ---------------- RADIER ----------------
        # Fissuration (contact eau) uniquement si le radier est en contact direct de l'eau
        # (cas des réservoirs). Pour les châteaux d'eau (radier sous tour) -> FP/FPP max.
        radier_contact = (type_s := analysis_report.meta.get("type")) == "reservoir"
        items_radier: List[Item] = []
        if f.shape in ("Circulaire", "Tronconique"):
            R = (f.D / 2.0) if f.shape == "Circulaire" else (f.D_base + f.D_sommet) / 4.0
            Leq = math.sqrt(math.pi * R**2)
            M = p * Leq**2 / 10.0
            _section_radierr(items_radier, "équivalent carré", p, Leq, e_radier, d_radier, fy, norme, f.fck, M, crack=radier_contact)
        else:
            Mx = p * f.B**2 / 10.0
            My = p * f.L**2 / 10.0
            _section_radierr(items_radier, "rectangulaire", p, f.B, e_radier, d_radier, fy, norme, f.fck, Mx, My, crack=radier_contact)
        titre_rad = "RADIER (armatures + fissuration)" if radier_contact else "RADIER (armatures FP/FPP max — hors contact eau)"
        report.section(titre_rad, items_radier)

        # ---------------- PAROIS / COQUE ----------------
        type_s = analysis_report.meta.get("type")
        Sa_i = analysis_report.find("Sa(Ti) (g)")
        Sa_c = analysis_report.find("Sa(Tc) (g)")
        kh = max(Sa_i if isinstance(Sa_i, (int, float)) else 0.0,
                 Sa_c if isinstance(Sa_c, (int, float)) else 0.0)

        items_paroi: List[Item] = []
        if type_s == "chateau_eau":
            H = geom["H_fluide"]
            Rf, Rs = geom["R_fond"], geom["R_surface"]
            e_cuve_mm = e_cuve_mm if e_cuve_mm is not None else geom.get("epaisseur_cuve_m", 0.35) * 1000.0
            e_fut = geom.get("epaisseur_fut_m", 0.40)
            M_base = analysis_report.meta.get("M_total_kNm", 0.0)
            p_stat = GAMMA_W * H
            p_dyn = GAMMA_W * H * kh
            p_des = p_stat + p_dyn
            d_v = _d_eff(e_cuve_mm, f)
            Mv = p_des * H**2 / 6.0
            Mv_serv = p_stat * H**2 / 6.0
            items_paroi += [
                Item("Pression de calcul paroi (kPa)", p_des, "kPa",
                     f"hydrostatique + dynamique (kh={kh:.3f}g)"),
                Item("Épaisseur paroi cuve (m)", round(e_cuve_mm / 1000.0, 3), "m",
                     "saisie opérateur (poids pris en compte)"),
                Item("Moment flexion verticale Mv (kN·m/m)", Mv, "kN·m/m"),
            ]
            _gouverne(items_paroi, "Paroi verticale", Mv, Mv_serv, d_v, e_cuve_mm, fy, f.fck,
                      norme, w_max, _as_min_per_m(f.fck, norme))
            _section_ceintures(items_paroi, Rf, H, kh, fy, norme, f.fck, e_cuve_mm, f)
            # Tour / fût (hors contact eau -> FP/FPP max)
            _section_fut(items_paroi, geom.get("R_fut_base", Rf), e_fut, M_base, fy, f.fck, norme, f)
            # Coupoles sup/inf + ceintures sup/inf (géométrie & épaisseurs saisies 1re page)
            _section_coupoles(items_paroi, geom, H, fy, f.fck, norme, f)
        elif type_s == "reservoir":
            sous = analysis_report.meta.get("sous_type")
            H = geom["H_fluide"]
            p_stat = GAMMA_W * H
            p_dyn = GAMMA_W * H * kh
            p_des = p_stat + p_dyn
            items_paroi.append(Item("Pression de calcul paroi (kPa)", p_des, "kPa",
                                    f"hydrostatique + dynamique (kh={kh:.3f}g)"))
            if sous == "Circulaire":
                R = geom["D"] / 2.0
                e_paroi = e_cuve_mm if e_cuve_mm is not None else geom.get("epaisseur_paroi_m", max(0.25, H / 15.0)) * 1000.0
                d_v = _d_eff(e_paroi, f)
                Mv = p_des * H**2 / 6.0
                Mv_serv = p_stat * H**2 / 6.0
                items_paroi += [
                    Item("Épaisseur paroi (m)", round(e_paroi / 1000.0, 3), "m"),
                    Item("Moment flexion verticale Mv (kN·m/m)", Mv, "kN·m/m"),
                ]
                _gouverne(items_paroi, "Paroi verticale", Mv, Mv_serv, d_v, e_paroi, fy,
                          f.fck, norme, w_max, _as_min_per_m(f.fck, norme))
                _section_ceintures(items_paroi, R, H, kh, fy, norme, f.fck, e_paroi, f)
                # toit circulaire (couverture)
                e_couv_def = geom["D"] / 30.0 * 1000.0
                e_couv_mm = e_couv_mm if e_couv_mm is not None else e_couv_def
                _section_couverture(items_paroi, geom["D"], geom["D"], H, fy, f.fck, norme, f,
                                    q_couv, Q_lan, e_couv_mm / 1000.0)
            else:
                e_paroi = e_cuve_mm if e_cuve_mm is not None else geom.get("epaisseur_paroi_m", max(0.25, H / 15.0)) * 1000.0
                d_v = _d_eff(e_paroi, f)
                Mx = p_des * H**2 / 6.0
                My = p_des * H**2 / 6.0
                Mx_s = p_stat * H**2 / 6.0
                items_paroi += [
                    Item("Épaisseur paroi (m)", round(e_paroi / 1000.0, 3), "m"),
                    Item("Moment Mx (kN·m/m)", Mx, "kN·m/m"),
                ]
                _gouverne(items_paroi, "Paroi x", Mx, Mx_s, d_v, e_paroi, fy, f.fck,
                          norme, w_max, _as_min_per_m(f.fck, norme))
                items_paroi.append(Item("Moment My (kN·m/m)", My, "kN·m/m"))
                _gouverne(items_paroi, "Paroi y", My, Mx_s, d_v, e_paroi, fy, f.fck,
                          norme, w_max, _as_min_per_m(f.fck, norme))
                # dalle de couverture + lanterneaux (réservoir au sol / enterré)
                e_couv_def = min(geom["L"], geom["B"]) / 30.0 * 1000.0
                e_couv_mm = e_couv_mm if e_couv_mm is not None else e_couv_def
                _section_couverture(items_paroi, geom["L"], geom["B"], H, fy, f.fck, norme, f,
                                    q_couv, Q_lan, e_couv_mm / 1000.0)
        else:
            items_paroi.append(Item("Info", "Géométrie non reconnue pour les parois.", ""))

        report.section("PAROIS / COQUE / COUPOLES / COUVERTURE", items_paroi)
        return report, None
    except Exception as e:  # noqa: BLE001
        logger.exception("Erreur armatures")
        return None, f"Erreur armatures : {e}"
