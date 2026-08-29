"""Tests de non-régression et de validation des formules (valeurs de référence)."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import reglements as rg
from core import housner as hs
from core.analyse_structure import analyser_chateau_eau_complet, analyser_reservoir_semi_enterre
from core.foundation import FoundationInput, analyser_fondation, auto_dimensionner, resolve_foundation
from core.reinforcement import calculer_armatures


# ----------------------------- Spectre -----------------------------
def test_spectrum_analytic_points():
    ag = 0.17
    # RPS 2011 S4 : S=1.8, TB=0.30, TC=1.0, TD=2.0, BETA=2.5
    assert abs(rg.design_spectrum("RPS 2011", "S4 (1.80)", ag, 0.0, 1.0) - ag) < 1e-9
    assert abs(rg.design_spectrum("RPS 2011", "S4 (1.80)", ag, 0.30, 1.0) - ag * 2.5 * 1.8) < 1e-9
    assert abs(rg.design_spectrum("RPS 2011", "S4 (1.80)", ag, 1.0, 1.0) - ag * 2.5 * 1.8) < 1e-9
    # branche longue période T > TD
    sa_td = ag * 2.5 * 1.8 * 1.0 * 2.0 / (4.0 ** 2)
    assert abs(rg.design_spectrum("RPS 2011", "S4 (1.80)", ag, 4.0, 1.0) - sa_td) < 1e-9
    # réduction par q avec plancher
    sa_q = max(ag * 2.5 * 1.8 / 2.0, 0.2 * ag)
    assert abs(rg.design_spectrum("RPS 2011", "S4 (1.80)", ag, 1.0, 2.0) - sa_q) < 1e-9


def test_spectrum_long_period_decreases():
    # la branche T>TD doit être strictement décroissante (bug historique corrigé)
    vals = [rg.design_spectrum("RPS 2011", "S4 (1.80)", 0.17, T, 1.0) for T in (2.0, 3.0, 4.0, 6.0)]
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))


# ----------------------------- Housner -----------------------------
def test_housner_conique_bounds():
    d = hs.calculer_parametres_housner_conique(10.0, 5.0, 9.0)
    assert d is not None
    M = d["Masse totale (kg)"]
    assert d["Masse impulsive (kg)"] > 0
    assert d["Masse convective (kg)"] > 0
    # masse impulsive + convective doit rester < masse totale
    assert d["Masse impulsive (kg)"] + d["Masse convective (kg)"] < M
    assert 0 < d["Hauteur impulsive (m)"] < 10.0
    assert 0 < d["Hauteur convective (m)"] < 10.0
    assert d["Période convective (s)"] > 0


def test_housner_invalid_returns_none():
    assert hs.calculer_parametres_housner_conique(0, 5, 9) is None
    assert hs.calculer_parametres_housner_circulaire(10, 20) is not None
    assert hs.calculer_parametres_housner_rectangulaire(10, 30) is not None


# ----------------------------- Analyse -----------------------------
def test_analyse_chateau_eau_runs():
    pr = {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0}
    pf = {"H_fut": 25.0, "R_fut_base": 8.0, "R_fut_sommet": 5.0, "epaisseur_fut": 0.5}
    ps = {"regulation": "RPS 2011", "zone": "Zone 4 (0.17g)", "soil": "S4 (1.80)", "q": 2.0}
    rep, err = analyser_chateau_eau_complet(pr, pf, ps, epaisseur_cuve=0.4)
    assert err is None and rep is not None
    assert rep.find("Période convective Tc (s)") > 0
    assert rep.find("Sa(Ti) (g)") > 0


def test_analyse_reservoir_circulaire_runs():
    pg = {"type": "Circulaire", "H_fluide": 5.0, "H_enterre": 3.0, "soil_gamma": 18.0, "D": 20.0}
    ps = {"regulation": "EC8", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 1.5}
    rep, err = analyser_reservoir_semi_enterre(pg, ps)
    assert err is None and rep is not None
    assert rep.meta["type"] == "reservoir"


# ----------------------------- Fondation -----------------------------
def test_fondation_auto_dim_feasible():
    # charge réaliste d'un réservoir circulaire
    load = {"N_total_kN": 8000.0, "V_total_kN": 1200.0, "M_total_kNm": 12000.0}
    fi = auto_dimensionner(load, "Circulaire", q_adm=200.0, mu=0.5)
    rep, err = analyser_fondation(load, fi, concentrated=False)
    assert err is None and rep is not None
    # après auto-dimensionnement les contraintes doivent être vérifiées
    assert rep.find("Contrainte max σmax (kPa)") <= 200.0
    assert rep.ok


def test_fondation_small_raft_fails():
    load = {"N_total_kN": 8000.0, "V_total_kN": 1200.0, "M_total_kNm": 50000.0}
    fi = FoundationInput(shape="Circulaire", D=6.0, h_f=1.0, q_adm=200.0)
    rep, _ = analyser_fondation(load, fi, concentrated=False)
    assert not rep.ok  # excentricité hors noyau -> non conforme


def test_tronconique_raft_geometry():
    # cuve circulaire de diamètre 20 m ; tour/cuve base = 20 m
    tank = {"D": 20.0}
    fi = FoundationInput(shape="Tronconique", D_base=24.0, overhang=0.50, h_disk=0.6, h_cone=1.2)
    resolve_foundation(fi, tank)
    # petit diamètre = diamètre base tour + 2*débord
    assert abs(fi.D_sommet - (20.0 + 2 * 0.50)) < 1e-9
    assert fi.D_base >= fi.D_sommet
    rep, err = analyser_fondation({"N_total_kN": 5000.0, "V_total_kN": 800.0, "M_total_kNm": 6000.0},
                                  fi, concentrated=False, tank=tank)
    assert err is None and rep is not None
    assert rep.find("Volume béton (m³)") is not None
    assert rep.find("Diamètre sommet D_sommet (m)") == fi.D_sommet


def test_overhang_applied_rectangulaire():
    tank = {"L": 30.0, "B": 15.0}
    fi = FoundationInput(shape="Rectangulaire", overhang=1.0)
    resolve_foundation(fi, tank)
    assert abs(fi.L - (30.0 + 2 * 1.0)) < 1e-9
    assert abs(fi.B - (15.0 + 2 * 1.0)) < 1e-9


def test_auto_dimensionner_respects_overhang():
    load = {"N_total_kN": 8000.0, "V_total_kN": 1200.0, "M_total_kNm": 12000.0}
    tank = {"D": 20.0}
    fi = auto_dimensionner(load, "Tronconique", 200.0, 0.5, overhang=0.75, tank=tank)
    assert fi.D_sommet == 20.0 + 2 * 0.75
    assert fi.D_base >= fi.D_sommet


def test_ceintures_circulaire_chateau_et_reservoir():
    # château d'eau (cuve circulaire conique)
    ce, _ = analyser_chateau_eau_complet(
        {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0},
        {"H_fut": 25.0, "R_fut_base": 3.0, "R_fut_sommet": 2.0, "epaisseur_fut": 0.4},
        {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0},
        0.35,
    )
    load = {"N_total_kN": ce.meta["N_total_kN"], "V_total_kN": ce.meta["V_total_kN"],
            "M_total_kNm": ce.meta["M_total_kNm"]}
    fi = auto_dimensionner(load, "Tronconique", 200.0, 0.5, tank={"D": 18.0})
    fr, _ = analyser_fondation(load, fi, concentrated=False, tank={"D": 18.0})
    arm, _ = calculer_armatures(ce, fr, fi, "RPS 2011",
                                {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0})
    ceint_items = [it for _, items in arm.sections for it in items if "Ceinture" in it.label]
    assert ceint_items, "ceintures (armatures annulaires) manquantes pour cuve circulaire"
    T_max = arm.find("Tension annulaire max T (kN/m)")
    assert isinstance(T_max, (int, float)) and T_max > 0.0

    # reservoir circulaire
    re, _ = analyser_reservoir_semi_enterre(
        {"type": "Circulaire", "H_fluide": 5.0, "H_enterre": 3.0, "soil_gamma": 18.0, "D": 20.0},
        {"regulation": "EC8", "zone": "Zone 3 (0.13g)", "soil": "S2 (1.20)", "q": 2.0},
    )
    load2 = {"N_total_kN": re.meta["N_total_kN"], "V_total_kN": re.meta["V_total_kN"],
             "M_total_kNm": re.meta["M_total_kNm"]}
    fi2 = auto_dimensionner(load2, "Circulaire", 200.0, 0.5, tank={"D": 20.0})
    fr2, _ = analyser_fondation(load2, fi2, concentrated=False, tank={"D": 20.0})
    arm2, _ = calculer_armatures(re, fr2, fi2, "EC8", {"H_fluide": 5.0, "D": 20.0})
    ceint2 = [it for _, items in arm2.sections for it in items if "Ceinture" in it.label]
    assert ceint2, "ceintures manquantes pour reservoir circulaire"


def test_coupoles_et_couverture_fasc74():
    # chateau d'eau -> coupoles sup/inf (Fasc. 74 : fleche >= D/10 et >= d/8)
    ce, _ = analyser_chateau_eau_complet(
        {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0},
        {"H_fut": 25.0, "R_fut_base": 3.0, "R_fut_sommet": 2.0, "epaisseur_fut": 0.4},
        {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0},
        0.35,
    )
    load = {"N_total_kN": ce.meta["N_total_kN"], "V_total_kN": ce.meta["V_total_kN"],
            "M_total_kNm": ce.meta["M_total_kNm"]}
    fi = auto_dimensionner(load, "Tronconique", 200.0, 0.5, tank={"D": 18.0})
    fr, _ = analyser_fondation(load, fi, concentrated=False, tank={"D": 18.0})
    arm, _ = calculer_armatures(ce, fr, fi, "RPS 2011",
                                {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0,
                                 "epaisseur_cuve_m": 0.35},
                                {"w_max": 0.2, "q_couv": 1.5, "Q_lanterneau": 10.0})
    labels = [it.label for _, items in arm.sections for it in items]
    assert any("COUPOLE SUP" in l for l in labels)
    assert any("COUPOLE INF" in l for l in labels)
        # fleche sup >= D_sup/10 = 2*9/10 = 1.8 ; inf >= d/8 = 2*5/8 = 1.25
    fleches = [it.value for _, items in arm.sections for it in items
               if "Flèche f (m)" in it.label]
    assert len(fleches) == 2, "deux coupoles attendues"
    assert fleches[0] >= 1.8 - 1e-6   # sup
    assert fleches[1] >= 1.25 - 1e-6  # inf
    # verif fissuration presente (element en contact d'eau)
    assert any("Ouverture fissure" in l for l in labels)

    # reservoir rectangulaire -> dalle de couverture + lanterneaux
    re, _ = analyser_reservoir_semi_enterre(
        {"type": "Rectangulaire", "H_fluide": 5.0, "H_enterre": 3.0, "soil_gamma": 18.0,
         "L": 30.0, "B": 15.0},
        {"regulation": "EC8", "zone": "Zone 3 (0.13g)", "soil": "S2 (1.20)", "q": 2.0},
    )
    load2 = {"N_total_kN": re.meta["N_total_kN"], "V_total_kN": re.meta["V_total_kN"],
             "M_total_kNm": re.meta["M_total_kNm"]}
    fi2 = auto_dimensionner(load2, "Rectangulaire", 200.0, 0.5, tank={"L": 30.0, "B": 15.0})
    fr2, _ = analyser_fondation(load2, fi2, concentrated=False, tank={"L": 30.0, "B": 15.0})
    arm2, _ = calculer_armatures(re, fr2, fi2, "EC8",
                                 {"H_fluide": 5.0, "L": 30.0, "B": 15.0},
                                 {"w_max": 0.2, "q_couv": 1.5, "Q_lanterneau": 10.0})
    lab2 = [it.label for _, items in arm2.sections for it in items]
    assert any("DALLE DE COUVERTURE" in l for l in lab2)
    assert any("Note lanterneaux" in l for l in lab2)


def test_ceintures_sup_inf_chateau():
    # Ceinture sup (cuve<->coupole sup) et ceinture inf (fut<->cuve<->coupole inf)
    ce, _ = analyser_chateau_eau_complet(
        {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0,
         "coupole_sup_D": 18.0, "coupole_sup_f": 1.80, "coupole_sup_e": 0.30,
         "coupole_inf_d": 10.0, "coupole_inf_f": 1.25, "coupole_inf_e": 0.30},
        {"H_fut": 25.0, "R_fut_base": 3.0, "R_fut_sommet": 2.0, "epaisseur_fut": 0.4},
        {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0},
        0.35,
    )
    load = {"N_total_kN": ce.meta["N_total_kN"], "V_total_kN": ce.meta["V_total_kN"],
            "M_total_kNm": ce.meta["M_total_kNm"]}
    fi = auto_dimensionner(load, "Tronconique", 200.0, 0.5, tank={"D": 18.0})
    fr, _ = analyser_fondation(load, fi, concentrated=True, tank={"D": 18.0})
    arm, _ = calculer_armatures(ce, fr, fi, "RPS 2011",
                                {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0,
                                 "coupole_sup_D": 18.0, "coupole_sup_f": 1.80, "coupole_sup_e": 0.30,
                                 "coupole_inf_d": 10.0, "coupole_inf_f": 1.25, "coupole_inf_e": 0.30,
                                 "epaisseur_cuve_m": 0.35},
                                {"w_max": 0.2})
    labels = [it.label for _, items in arm.sections for it in items]
    # Les 2 ceintures de raccord (base + sommet de la cuve) reprennent la traction
    # combinée cuve + coupoles (aucun anneau de liaison distinct).
    assert any("Ceinture base" in l and "coupole inf" in l for l in labels), "ceinture base manquante"
    assert any("Ceinture sommet" in l and "coupole sup" in l for l in labels), "ceinture sommet manquante"
    # ces ceintures (raccord cuve, contact eau) -> fissuration verifiee
    assert any(("Ceinture base" in l or "Ceinture sommet" in l) and "Ouverture fissure" in l
               for l in labels)


def test_masse_coupoles_alimente_chargement():
    # Coupole saisie 1re page -> poids propre ajoute a N_total (securite fondation)
    base = {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0}
    leg, _ = analyser_chateau_eau_complet({**base,
        "coupole_sup_D": 18.0, "coupole_sup_f": 1.80, "coupole_sup_e": 0.20,
        "coupole_inf_d": 10.0, "coupole_inf_f": 1.25, "coupole_inf_e": 0.20},
        {"H_fut": 25.0, "R_fut_base": 3.0, "R_fut_sommet": 2.0, "epaisseur_fut": 0.4},
        {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0}, 0.35)
    lourd, _ = analyser_chateau_eau_complet({**base,
        "coupole_sup_D": 22.0, "coupole_sup_f": 2.20, "coupole_sup_e": 0.45,
        "coupole_inf_d": 12.0, "coupole_inf_f": 1.50, "coupole_inf_e": 0.45},
        {"H_fut": 25.0, "R_fut_base": 3.0, "R_fut_sommet": 2.0, "epaisseur_fut": 0.4},
        {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0}, 0.35)
    assert lourd.meta["N_total_kN"] > leg.meta["N_total_kN"]
    # les masses de coupoles figurent dans le rapport STRUCTURE
    lab_leg = [it.label for _, items in leg.sections for it in items]
    assert any("Masse coupole sup" in l for l in lab_leg)
    assert any("Masse coupole inf" in l for l in lab_leg)


def test_fissuration_scope_fp_fpp():
    # Fissuration UNIQUEMENT pour elements en contact d'eau.
    ce, _ = analyser_chateau_eau_complet(
        {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0},
        {"H_fut": 25.0, "R_fut_base": 3.0, "R_fut_sommet": 2.0, "epaisseur_fut": 0.4},
        {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0},
        0.35,
    )
    load = {"N_total_kN": ce.meta["N_total_kN"], "V_total_kN": ce.meta["V_total_kN"],
            "M_total_kNm": ce.meta["M_total_kNm"]}
    fi = auto_dimensionner(load, "Tronconique", 200.0, 0.5, tank={"D": 18.0})
    fr, _ = analyser_fondation(load, fi, concentrated=False, tank={"D": 18.0})
    arm, _ = calculer_armatures(ce, fr, fi, "RPS 2011",
                                {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0,
                                 "epaisseur_cuve_m": 0.35, "epaisseur_fut_m": 0.4},
                                {"w_max": 0.2, "q_couv": 1.5, "Q_lanterneau": 10.0})
    radier_titles = [t for t, _ in arm.sections if "RADIER" in t]
    assert any("FP/FPP max" in t for t in radier_titles)   # chateau radier hors eau
    assert not any("fissuration" in t for t in radier_titles)
    flat = [(t, it.label, it.value) for t, items in arm.sections for it in items]
    # coupole sup : FP/FPP max, PAS de fissure
    sup = [l for _, l, _ in flat if "Coupole sup" in l]
    assert any("FP/FPP max" in l or "hors contact" in l for l in sup) or \
        any("FP/FPP max" in v for _, l, v in flat if "Coupole sup" in l)
    assert not any("Ouverture fissure" in l for _, l, _ in flat if "Coupole sup" in l)
    # coupole inf : fissure presente (contact eau)
    assert any("Ouverture fissure" in l for _, l, _ in flat if "Coupole inf" in l)
    # parois/ceintures de raccord cuve : fissure presente (contact eau)
    assert any("Ouverture fissure" in l for _, l, _ in flat
               if ("Ceinture base" in l or "Ceinture sommet" in l))
    # reservoir : radier EN contact eau -> fissure
    re, _ = analyser_reservoir_semi_enterre(
        {"type": "Rectangulaire", "H_fluide": 5.0, "H_enterre": 3.0, "soil_gamma": 18.0,
         "L": 30.0, "B": 15.0},
        {"regulation": "EC8", "zone": "Zone 3 (0.13g)", "soil": "S2 (1.20)", "q": 2.0},
    )
    l2 = {"N_total_kN": re.meta["N_total_kN"], "V_total_kN": re.meta["V_total_kN"],
          "M_total_kNm": re.meta["M_total_kNm"]}
    fi2 = auto_dimensionner(l2, "Rectangulaire", 200.0, 0.5, tank={"L": 30.0, "B": 15.0})
    fr2, _ = analyser_fondation(l2, fi2, concentrated=False, tank={"L": 30.0, "B": 15.0})
    arm2, _ = calculer_armatures(re, fr2, fi2, "EC8", {"H_fluide": 5.0, "L": 30.0, "B": 15.0},
                                 {"w_max": 0.2, "q_couv": 1.5, "Q_lanterneau": 10.0})
    # reservoir radier EN contact eau -> titre contient 'fissuration' et items fissure
    rad_titles2 = [t for t, _ in arm2.sections if "RADIER" in t]
    assert any("fissuration" in t for t in rad_titles2)
    flat2 = [(t, it.label) for t, items in arm2.sections for it in items]
    assert any("Ouverture fissure" in l for t, l in flat2 if "RADIER" in t)
    # couverture reservoir : FP/FPP max (hors eau)
    assert any("FP/FPP max" in l for t, l in flat2 if "Couverture" in l)


# ----------------- Mononobe-Okabe & combinaisons -----------------
def test_mononobe_okabe_coefficient():
    from core.analyse_structure import _mononobe_okabe_ka, _rankine_ka
    phi = 30.0
    delta = 0.66 * phi
    ka0 = _rankine_ka(phi)
    # sans séisme et sans frottement -> Rankine
    assert abs(_mononobe_okabe_ka(phi, 0.0, 0.0) - ka0) < 1e-9
    # baseline statique avec frottement mural (Coulomb) : Ka augmente avec le séisme
    ka_static = _mononobe_okabe_ka(phi, delta, 0.0)   # = Coulomb statique (δ)
    ka_mo = _mononobe_okabe_ka(phi, delta, 0.20)
    assert ka_mo > ka_static, "la poussée active sismique doit dépasser la statique"
    # la composante HORIZONTALE de la poussée doit aussi augmenter
    psi = math.atan(0.20)
    Pa_h_stat = 0.5 * ka_static * math.cos(math.radians(delta))
    Pa_h_mo = 0.5 * ka_mo * math.cos(math.radians(delta) + psi)
    assert Pa_h_mo > Pa_h_stat
    # borne raisonnable
    assert 0.1 < ka_mo < 1.0


def test_reservoir_combinaisons_vide_plein():
    pg = {"type": "Circulaire", "H_fluide": 5.0, "H_enterre": 3.0, "soil_gamma": 18.0,
          "D": 20.0, "soil_phi": 30.0}
    ps = {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0}
    re, err = analyser_reservoir_semi_enterre(pg, ps)
    assert err is None
    combos = re.meta["combinaisons"]
    assert len(combos) == 2
    cases = {c["case"] for c in combos}
    assert cases == {"VIDE", "PLEIN"}
    vide = next(c for c in combos if c["case"] == "VIDE")
    plein = next(c for c in combos if c["case"] == "PLEIN")
    # plein plus lourd que vide (eau en plus)
    assert plein["N_total_kN"] > vide["N_total_kN"]
    # poussée des terres (Mononobe-Okabe) présente dans le rapport
    assert any("Mononobe" in t for t, _ in re.sections)
    # la fondation doit être vérifiée pour LES DEUX combinaisons (liste)
    fi = auto_dimensionner(combos, "Circulaire", 200.0, 0.5, tank={"D": 20.0})
    fr, err2 = analyser_fondation(combos, fi, concentrated=False, tank={"D": 20.0})
    assert err2 is None
    assert fr.ok, "les 2 combinaisons (vide+plein) doivent être vérifiées"


def test_chateau_combinaisons_vide_plein():
    pr = {"H_fluide": 10.0, "R_fond": 5.0, "R_surface": 9.0}
    pf = {"H_fut": 25.0, "R_fut_base": 3.0, "R_fut_sommet": 2.0, "epaisseur_fut": 0.4}
    ps = {"regulation": "RPS 2011", "zone": "Zone 3 (0.13g)", "soil": "S3 (1.40)", "q": 2.0}
    ce, err = analyser_chateau_eau_complet(pr, pf, ps, epaisseur_cuve=0.35)
    assert err is None
    combos = ce.meta["combinaisons"]
    assert {c["case"] for c in combos} == {"VIDE", "PLEIN"}
    vide = next(c for c in combos if c["case"] == "VIDE")
    plein = next(c for c in combos if c["case"] == "PLEIN")
    assert plein["N_total_kN"] > vide["N_total_kN"]   # eau en plus
    # pas de poussée de terre pour un château surélevé
    assert not any("Mononobe" in t for t, _ in ce.sections)


