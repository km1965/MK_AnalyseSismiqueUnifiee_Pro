"""Orchestration des analyses sismiques (château d'eau, réservoir semi-enterré / enterré).

Retourne un ``Report`` structuré (plus aucune sentinelle '---').
Les épaisseurs du fût et de la cuve sont distinctes.

Combinaisons de calcul (cas usuels) :
  * Réservoir enterré / semi-enterré
      - CAS VIDE   : poids propre (structure seule) + poussée des terres
                     (statique Rankine + dynamique Mononobe-Okabe) + séisme.
      - CAS PLEIN  : poids propre + eau (hydrostatique + hydrodynamique Housner)
                     + poussée des terres (Mononobe-Okabe) + séisme.
  * Château d'eau surélevé (pas de terre)
      - CAS VIDE   : structure seule + séisme.
      - CAS PLEIN  : structure + eau (Housner) + séisme.

La fondation est vérifiée pour CHAQUE combinaison ; la plus défavorable gouverne.
"""
from __future__ import annotations

import logging
import math

import numpy as np

from core import housner as hs
from core import reglements as rg
from core.results import Item, Report
from core.stability import StabilityConfig, verifier_stabilite

logger = logging.getLogger(__name__)
G = 9.81
RHO_BETON = 2500.0
GAMMA_W = 9.81
E_BETON = 30e9


# --------------------------------------------------------------------------- #
# Poussée des terres : Rankine (statique) et Mononobe-Okabe (sismique)
# --------------------------------------------------------------------------- #
def _rankine_ka(phi_deg: float) -> float:
    """Coefficient de poussée active statique de Rankine (mur vertical, remblai horizontal)."""
    phi = math.radians(phi_deg)
    return (1.0 - math.sin(phi)) / (1.0 + math.sin(phi))


def _mononobe_okabe_ka(phi_deg: float, delta_deg: float, kh: float,
                       kv: float = 0.0, beta_deg: float = 0.0) -> float:
    """Coefficient de poussée active sismique de Mononobe-Okabe.

    Réf. : Mononobe & Okabe (1926/1929). ``kh`` en fraction de g (horizontal),
    ``kv`` vertical (≈ 0). ``psi = atan(kh/(1-kv))`` est l'inclinaison sismique.
    Retourne Ka (total statique + dynamique). Si le domaine n'est pas défini
    (psi trop grande), on retombe sur Rankine.
    """
    if kh <= 0:
        psi = 0.0
    else:
        psi = math.atan2(kh, 1.0 - kv)
    phi = math.radians(phi_deg)
    delta = math.radians(delta_deg)
    beta = math.radians(beta_deg)
    try:
        num = math.cos(phi - psi - beta) ** 2
        sin_a = math.sin(delta + phi - psi)
        sin_b = math.sin(phi - beta - psi)
        sin_c = math.sin(delta + beta + psi)
        sin_d = math.sin(phi - beta)
        if min(sin_a, sin_b, sin_c, sin_d) <= 0:
            return _rankine_ka(phi_deg)
        den = math.cos(psi) * math.cos(beta) ** 2 * math.cos(delta + beta + psi)
        rac = math.sqrt(sin_a * sin_b / (sin_c * sin_d))
        ka = num / (den * (1.0 + rac) ** 2)
        if not math.isfinite(ka) or ka <= 0:
            return _rankine_ka(phi_deg)
        return ka
    except Exception:  # noqa: BLE001
        return _rankine_ka(phi_deg)


def _vol_tronc_cone_creux(H, R_ext_base, R_ext_sommet, e):
    def vol(Rb_, Rs_):
        return (1 / 3) * np.pi * H * (Rb_**2 + Rs_**2 + Rb_ * Rs_)

    return vol(R_ext_base, R_ext_sommet) - vol(R_ext_base - e, R_ext_sommet - e)


# --------------------------------------------------------------------------- #
# Château d'eau surélevé
# --------------------------------------------------------------------------- #
def analyser_chateau_eau_complet(
    params_reservoir, params_fut, params_sismiques,
    epaisseur_cuve=None, stab_config: StabilityConfig = None,
):
    try:
        H_f = params_reservoir["H_fluide"]
        R_f = params_reservoir["R_fond"]
        R_s = params_reservoir["R_surface"]
        H_t = params_fut["H_fut"]
        Rb = params_fut["R_fut_base"]
        Rs = params_fut["R_fut_sommet"]
        e_fut = params_fut["epaisseur_fut"]
        e_cuve = epaisseur_cuve if epaisseur_cuve is not None else e_fut

        # --- Coupoles (saisies 1re page) : geometrie + epaisseur, defauts Fasc. 74 ---
        D_sup = params_reservoir.get("coupole_sup_D", 2.0 * R_s)
        f_sup = params_reservoir.get("coupole_sup_f", D_sup / 10.0)
        e_csup = params_reservoir.get("coupole_sup_e", max(0.15, D_sup / 35.0))
        d_inf = params_reservoir.get("coupole_inf_d", 2.0 * R_f)
        f_inf = params_reservoir.get("coupole_inf_f", d_inf / 8.0)
        e_cinf = params_reservoir.get("coupole_inf_e", max(0.15, d_inf / 35.0))
        csup_l = params_reservoir.get("ceinture_sup_l", 0.40)
        csup_h = params_reservoir.get("ceinture_sup_h", 0.60)
        cinf_l = params_reservoir.get("ceinture_inf_l", 0.50)
        cinf_h = params_reservoir.get("ceinture_inf_h", 0.70)

        reg = params_sismiques["regulation"]
        zone = params_sismiques["zone"]
        soil = params_sismiques["soil"]
        q = params_sismiques["q"]
        ag = rg.get_ag(zone)

        liq = hs.calculer_parametres_housner_conique(H_f, R_f, R_s)
        if liq is None:
            return None, "Géométrie du réservoir invalide (dimensions ≤ 0)."

        # Masse de la structure vide (fût + coque + coupoles), epaisseurs distinguées
        vol_fut = _vol_tronc_cone_creux(H_t, Rb, Rs, e_fut)
        masse_fut = vol_fut * RHO_BETON
        surf_coque = np.pi * (R_f + R_s) * np.sqrt((R_s - R_f) ** 2 + H_f**2)
        masse_coque = surf_coque * e_cuve * RHO_BETON

        def _masse_couple(D, f, e):
            Rsph = (D**2 / 4.0 + f**2) / (2.0 * f) if f > 0 else D / 2.0
            A_cap = 2.0 * np.pi * Rsph * f          # surface calotte spherique
            return A_cap * e * RHO_BETON

        masse_csup = _masse_couple(D_sup, f_sup, e_csup)
        masse_cinf = _masse_couple(d_inf, f_inf, e_cinf)
        m_struct = masse_fut + masse_coque + masse_csup + masse_cinf   # vide (sans eau)
        m_eau_imp = liq["Masse impulsive (kg)"]
        m_eau_conv = liq["Masse convective (kg)"]

        m_tot_imp = m_eau_imp + m_struct

        Rmoy_ext = (Rb + Rs) / 2.0
        Rmoy_int = (Rb - e_fut + Rs - e_fut) / 2.0
        I_moy = np.pi / 4 * (Rmoy_ext**4 - Rmoy_int**4)
        K_fut = 3 * E_BETON * I_moy / (H_t**3)
        T_imp = 2 * np.pi * np.sqrt(m_tot_imp / K_fut) if (m_tot_imp > 0 and K_fut > 0) else 0.0
        T_conv = liq["Période convective (s)"]

        Sa_i = rg.design_spectrum(reg, soil, ag, T_imp, q)
        Sa_c = rg.design_spectrum(reg, soil, ag, T_conv, q)
        kh = Sa_i  # coefficient sismique horizontal (en g)

        # Forces dynamiques Housner (liquide)
        F_i = m_tot_imp * Sa_i * G / 1000.0
        F_c = m_eau_conv * Sa_c * G / 1000.0
        h_i_s = H_t
        h_c_l = H_t + liq["Hauteur convective (m)"]
        M_i = F_i * h_i_s
        M_c = F_c * h_c_l

        # ---- Combinaisons ----
        # CAS VIDE : structure seule + séisme (pas d'eau, pas de terre -> pas de poussée)
        N_vide = m_struct * G / 1000.0
        V_vide = m_struct * Sa_i * G / 1000.0
        M_vide = V_vide * H_t

        # CAS PLEIN : structure + eau (Housner)
        N_plein = (m_struct + m_eau_imp + m_eau_conv) * G / 1000.0
        V_plein = float(np.sqrt(F_i**2 + F_c**2))
        M_plein = float(np.sqrt(M_i**2 + M_c**2))

        combinaisons = [
            {"case": "VIDE", "N_total_kN": N_vide, "V_total_kN": V_vide, "M_total_kNm": M_vide,
             "col_diameter_m": 2.0 * Rb,
             "note": "structure seule + séisme (sans eau, sans terre)"},
            {"case": "PLEIN", "N_total_kN": N_plein, "V_total_kN": V_plein, "M_total_kNm": M_plein,
             "col_diameter_m": 2.0 * Rb,
             "note": "structure + eau (hydrostatique + hydrodynamique Housner) + séisme"},
        ]

        largeur_fond = 2 * Rb
        report = Report("Analyse château d'eau surélevé")
        report.add_meta("type", "chateau_eau")
        # métadonnées de pilotage (gouverneur = CAS PLEIN pour l'armature/cuve)
        report.add_meta("N_total_kN", N_plein)
        report.add_meta("V_total_kN", V_plein)
        report.add_meta("M_total_kNm", M_plein)
        report.add_meta("largeur_fondation_m", largeur_fond)
        report.add_meta("R_fut_base_m", Rb)
        report.add_meta("epaisseur_fut_m", e_fut)
        report.add_meta("epaisseur_cuve_m", e_cuve)
        report.add_meta("H_fut_m", H_t)
        report.add_meta("combinaisons", combinaisons)
        report.add_meta("geometry", {
            "H_fluide": H_f, "R_fond": R_f, "R_surface": R_s,
            "H_fut": H_t, "R_fut_base": Rb, "R_fut_sommet": Rs,
            "epaisseur_cuve_m": e_cuve, "epaisseur_fut_m": e_fut,
            "coupole_sup_D": D_sup, "coupole_sup_f": f_sup, "coupole_sup_e": e_csup,
            "coupole_inf_d": d_inf, "coupole_inf_f": f_inf, "coupole_inf_e": e_cinf,
            "ceinture_sup_l": csup_l, "ceinture_sup_h": csup_h,
            "ceinture_inf_l": cinf_l, "ceinture_inf_h": cinf_h,
        })

        report.section("PARAMÈTRES HOUSNER (liquide)", [
            Item("Masse totale (kg)", liq["Masse totale (kg)"], "kg"),
            Item("Masse impulsive (kg)", m_eau_imp, "kg"),
            Item("Masse convective (kg)", m_eau_conv, "kg"),
            Item("Hauteur impulsive (m)", liq["Hauteur impulsive (m)"], "m"),
            Item("Hauteur convective (m)", liq["Hauteur convective (m)"], "m"),
            Item("Période convective Tc (s)", liq["Période convective (s)"], "s"),
        ])
        report.section("STRUCTURE (masse & rigidité)", [
            Item("Masse fût (kg)", masse_fut, "kg", f"épaisseur fût {e_fut} m"),
            Item("Masse coque cuve (kg)", masse_coque, "kg", f"épaisseur cuve {e_cuve} m"),
            Item("Masse coupole sup (kg)", masse_csup, "kg",
                 f"D={D_sup:.1f} m, f={f_sup:.2f} m, e={e_csup:.2f} m"),
            Item("Masse coupole inf (kg)", masse_cinf, "kg",
                 f"d={d_inf:.1f} m, f={f_inf:.2f} m, e={e_cinf:.2f} m"),
            Item("Masse structure vide (kg)", m_struct, "kg"),
            Item("Rigidité latérale fût K (N/m)", K_fut, "N/m"),
        ])
        report.section("DYNAMIQUE GLOBALE", [
            Item("Période impulsive Ti (s)", T_imp, "s"),
            Item("Période convective Tc (s)", T_conv, "s"),
            Item("Coefficient sismique kh = Sa(Ti) (g)", kh, "g"),
        ])
        report.section("SPECTRE DE CALCUL", [
            Item("Sa(Ti) (g)", Sa_i, "g"),
            Item("Sa(Tc) (g)", Sa_c, "g"),
        ])
        report.section("FORCES SISMIQUES (kN)", [
            Item("Force impulsive Fi (kN)", F_i, "kN"),
            Item("Force convective Fc (kN)", F_c, "kN"),
        ])
        report.section("MOMENTS À LA BASE (kN·m)", [
            Item("Moment impulsif Mi (kN·m)", M_i, "kN·m"),
            Item("Moment convectif Mc (kN·m)", M_c, "kN·m"),
        ])
        # ---- Combinaisons ----
        items_combos = []
        for c in combinaisons:
            items_combos += [
                Item(f"[{c['case']}] Poids total N (kN)", c["N_total_kN"], "kN", c["note"]),
                Item(f"[{c['case']}] Effort tranchant V (kN)", c["V_total_kN"], "kN"),
                Item(f"[{c['case']}] Moment M (kN·m)", c["M_total_kNm"], "kN·m"),
            ]
        report.section("COMBINAISONS DE CALCUL (vide / plein)", items_combos)
        report.section("STABILITÉ (préliminaire – semelle fût)", verifier_stabilite(N_plein, V_plein, M_plein, largeur_fond, stab_config))
        report.section("NOTE", [Item("Vérification définitive", "Effectuée à l'onglet Fondations avec le radier général (les 2 cas sont vérifiés).", "",
                                     "la largeur de retournement réelle y est prise en compte")])
        return report, None
    except KeyError as e:
        logger.error("Paramètre manquant: %s", e)
        return None, f"Paramètre manquant ou invalide : {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("Erreur analyse château d'eau")
        return None, f"Erreur de calcul : {e}"


# --------------------------------------------------------------------------- #
# Réservoir semi-enterré / enterré
# --------------------------------------------------------------------------- #
def analyser_reservoir_semi_enterre(params_geom, params_sismiques, stab_config: StabilityConfig = None):
    try:
        H_f = params_geom["H_fluide"]
        H_e = params_geom["H_enterre"]
        soil_gamma = params_geom["soil_gamma"]
        reg = params_sismiques["regulation"]
        zone = params_sismiques["zone"]
        soil = params_sismiques["soil"]
        q = params_sismiques["q"]
        ag = rg.get_ag(zone)

        # Géométrie du remblai / structure (avec défauts raisonnables)
        phi = params_geom.get("soil_phi", 30.0)
        delta = params_geom.get("soil_delta", 0.66 * phi)
        e_paroi = params_geom.get("e_paroi", 0.30)
        h_radier = params_geom.get("h_radier", 0.40)
        e_couv = params_geom.get("e_couv", 0.25)
        H_couv = params_geom.get("H_couverture", 0.0)

        if params_geom["type"] == "Circulaire":
            D = params_geom["D"]
            liq = hs.calculer_parametres_housner_circulaire(H_f, D)
            largeur_poussee = D
            largeur_fond = D
            A_paroi = math.pi * D * H_f
            A_radier = math.pi / 4.0 * D**2
            A_toit = A_radier
            geom_summary = {"H_fluide": H_f, "D": D, "H_enterre": H_e}
        elif params_geom["type"] == "Rectangulaire":
            L = params_geom["L"]
            B = params_geom["B"]
            pm = hs.calculer_parametres_housner_rectangulaire(H_f, L)
            liq = {
                "Masse impulsive (kg)": pm["Masse impulsive (kg/m)"] * B,
                "Masse convective (kg)": pm["Masse convective (kg/m)"] * B,
                "Hauteur impulsive (m)": pm["Hauteur impulsive (m)"],
                "Hauteur convective (m)": pm["Hauteur convective (m)"],
                "Période convective (s)": pm["Période convective (s)"],
            }
            largeur_poussee = B
            largeur_fond = L
            A_paroi = 2.0 * (L + B) * H_f
            A_radier = L * B
            A_toit = L * B
            geom_summary = {"H_fluide": H_f, "L": L, "B": B, "H_enterre": H_e}
        else:
            return None, "Type de géométrie non supporté."

        m_parois = A_paroi * e_paroi * RHO_BETON
        m_radier = A_radier * h_radier * RHO_BETON
        m_toit = A_toit * e_couv * RHO_BETON
        m_struct = m_parois + m_radier + m_toit          # structure vide (sans eau)
        overburden_kN = soil_gamma * A_toit * H_couv     # charge verticale du sol de couverture
        m_eau_imp = liq["Masse impulsive (kg)"]
        m_eau_conv = liq["Masse convective (kg)"]

        T_i = 0.0
        T_c = liq["Période convective (s)"]
        Sa_i = rg.design_spectrum(reg, soil, ag, T_i, q)
        Sa_c = rg.design_spectrum(reg, soil, ag, T_c, q)
        kh = Sa_i

        # ---- Poussée des terres (partie enterrée H_e) ----
        Ka0 = _rankine_ka(phi)
        Ka_mo = _mononobe_okabe_ka(phi, delta, kh)
        psi = math.atan2(kh, 1.0) if kh > 0 else 0.0
        # Effort total (statique + dynamique) par unité de largeur, composante horizontale
        P_ae_unit = 0.5 * soil_gamma * H_e**2 * Ka_mo            # kN/m (MO total)
        P_a0_unit = 0.5 * soil_gamma * H_e**2 * Ka0             # kN/m (Rankine statique)
        F_earth = P_ae_unit * largeur_poussee * math.cos(delta + psi)
        F_earth0 = P_a0_unit * largeur_poussee
        M_earth = F_earth * (H_e / 3.0)

        # ---- Poussée de l'eau (CAS PLEIN uniquement) ----
        F_water = 0.5 * GAMMA_W * H_f**2 * largeur_poussee      # hydrostatique (kN)
        M_water = F_water * (H_f / 3.0)

        # Forces dynamiques Housner (liquide)
        F_i = m_eau_imp * Sa_i * G / 1000.0
        F_c = m_eau_conv * Sa_c * G / 1000.0
        h_i = liq["Hauteur impulsive (m)"]
        h_c = liq["Hauteur convective (m)"]
        M_i = F_i * h_i
        M_c = F_c * h_c

        # Séisme de la structure (inertie propre)
        h_struct = H_f / 2.0
        F_struct_seis = m_struct * Sa_i * G / 1000.0

        # ---- Combinaison VIDE : structure + terre (MO) + séisme ----
        N_vide = m_struct * G / 1000.0 + overburden_kN
        V_vide = F_earth + F_struct_seis
        M_vide = M_earth + F_struct_seis * h_struct

        # ---- Combinaison PLEIN : structure + eau + terre (MO) + séisme ----
        N_plein = N_vide + (m_eau_imp + m_eau_conv) * G / 1000.0
        V_plein = F_earth + F_water + F_i + F_c
        M_plein = M_earth + M_water + M_i + M_c + F_struct_seis * h_struct

        combinaisons = [
            {"case": "VIDE",
             "N_total_kN": N_vide, "V_total_kN": V_vide, "M_total_kNm": M_vide,
             "note": "structure + poussée terres (Rankine+Mononobe-Okabe) + séisme"},
            {"case": "PLEIN",
             "N_total_kN": N_plein, "V_total_kN": V_plein, "M_total_kNm": M_plein,
             "note": "structure + eau (hydrostatique+Housner) + terres (MO) + séisme"},
        ]

        report = Report("Analyse réservoir semi-enterré / enterré")
        report.add_meta("type", "reservoir")
        report.add_meta("sous_type", params_geom["type"])
        report.add_meta("N_total_kN", N_plein)
        report.add_meta("V_total_kN", V_plein)
        report.add_meta("M_total_kNm", M_plein)
        report.add_meta("largeur_fondation_m", largeur_fond)
        report.add_meta("H_enterre_m", H_e)
        report.add_meta("combinaisons", combinaisons)
        report.add_meta("geometry", geom_summary)

        report.section("PARAMÈTRES HOUSNER", [
            Item("Masse impulsive (kg)", m_eau_imp, "kg"),
            Item("Masse convective (kg)", m_eau_conv, "kg"),
            Item("Hauteur impulsive (m)", h_i, "m"),
            Item("Hauteur convective (m)", h_c, "m"),
            Item("Période convective Tc (s)", liq["Période convective (s)"], "s"),
        ])
        report.section("POUSSÉE DES TERRES (Mononobe-Okabe)", [
            Item("Angle frottement sol φ (°)", phi, "°"),
            Item("Angle frottement mur δ (°)", delta, "°"),
            Item("Coefficient sismique kh = Sa(Ti) (g)", kh, "g"),
            Item("Ka Rankine statique", round(Ka0, 4), ""),
            Item("Ka Mononobe-Okabe", round(Ka_mo, 4), "", "statique + dynamique"),
            Item("Poussée statique Pa0 (kN)", F_earth0, "kN"),
            Item("Poussée sismique Pa (MO) (kN)", F_earth, "kN",
                 "horizontale = Pa·cos(δ+ψ)"),
            Item("Moment terres (kN·m)", M_earth, "kN·m"),
        ])
        report.section("POUSSÉE DE L'EAU (plein)", [
            Item("Force hydrostatique eau (kN)", F_water, "kN", "0.5·γw·H²"),
            Item("Moment eau (kN·m)", M_water, "kN·m"),
            Item("Force impulsive Fi (kN)", F_i, "kN"),
            Item("Force convective Fc (kN)", F_c, "kN"),
        ])
        report.section("FORCES SISMIQUES STRUCTURE", [
            Item("Force inertie structure (kN)", F_struct_seis, "kN"),
        ])
        items_combos = []
        for c in combinaisons:
            items_combos += [
                Item(f"[{c['case']}] Poids total N (kN)", c["N_total_kN"], "kN", c["note"]),
                Item(f"[{c['case']}] Effort tranchant V (kN)", c["V_total_kN"], "kN"),
                Item(f"[{c['case']}] Moment M (kN·m)", c["M_total_kNm"], "kN·m"),
            ]
        report.section("COMBINAISONS DE CALCUL (vide / plein)", items_combos)
        report.section("STABILITÉ (préliminaire)", verifier_stabilite(N_plein, V_plein, M_plein, largeur_fond, stab_config))
        report.section("NOTE", [Item("Vérification définitive", "Effectuée à l'onglet Fondations avec le radier général (les 2 cas sont vérifiés).", "",
                                     "la largeur de retournement réelle y est prise en compte")])
        return report, None
    except KeyError as e:
        logger.error("Paramètre manquant: %s", e)
        return None, f"Paramètre manquant ou invalide : {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("Erreur analyse réservoir")
        return None, f"Erreur de calcul : {e}"
