import numpy as np

def calculer_parametres_housner_conique(H_fluide, R_fond, R_surface):
    # ... (Cette fonction reste exactement la même que dans le message précédent)
    if H_fluide <= 0 or R_fond <= 0 or R_surface <= 0: return None
    gamma = R_surface / R_fond
    volume = (1/3) * np.pi * H_fluide * (R_fond**2 + R_surface**2 + R_fond * R_surface)
    masse_totale = volume * 1000
    psi_i = (gamma**2 + 2*gamma + 3) / (gamma**2 + gamma + 1)
    masse_impulsive = masse_totale * (1 - 0.58 * psi_i * np.tanh(1.5 * H_fluide / R_surface) / (H_fluide / R_surface))
    hauteur_impulsive = H_fluide * (0.5 - 0.09 * psi_i)
    masse_convective = masse_totale * 0.29 * (R_surface / H_fluide) * np.tanh(1.84 * H_fluide / R_surface)
    hauteur_convective = H_fluide * (1 - (np.cosh(1.84 * H_fluide / R_surface) - 1.28) / (1.84 * (H_fluide / R_surface) * np.sinh(1.84 * H_fluide / R_surface)))
    omega_c_sq = 1.84 * 9.81 * np.tanh(1.84 * H_fluide / R_surface) / R_surface
    T_convective = 2 * np.pi / np.sqrt(omega_c_sq)
    return {
        "Masse totale (kg)": masse_totale, "Masse impulsive (kg)": masse_impulsive,
        "Masse convective (kg)": masse_convective, "Hauteur impulsive (m)": hauteur_impulsive,
        "Hauteur convective (m)": hauteur_convective, "Période convective (s)": T_convective
    }

def analyser_chateau_eau_complet(params_reservoir, params_fut):
    """
    Analyse la structure complète : réservoir + fût.
    """
    # 1. Obtenir les paramètres du liquide depuis Housner
    params_liquide = calculer_parametres_housner_conique(
        params_reservoir['H_fluide'], params_reservoir['R_fond'], params_reservoir['R_surface']
    )
    if not params_liquide: return None

    # 2. Calculer la masse de la structure vide (fût + coque réservoir)
    rho_beton = 2500  # kg/m3
    # Masse du fût (tronc de cône creux)
    vol_fut = (1/3) * np.pi * params_fut['H_fut'] * (
        (params_fut['R_fut_base']**2 - (params_fut['R_fut_base']-params_fut['epaisseur'])**2) +
        (params_fut['R_fut_sommet']**2 - (params_fut['R_fut_sommet']-params_fut['epaisseur'])**2) +
        (np.sqrt((params_fut['R_fut_base']**2 - (params_fut['R_fut_base']-params_fut['epaisseur'])**2) * (params_fut['R_fut_sommet']**2 - (params_fut['R_fut_sommet']-params_fut['epaisseur'])**2)))
    )
    masse_fut = vol_fut * rho_beton
    
    # Masse de la coque du réservoir (approximation)
    surface_coque = np.pi * (params_reservoir['R_fond'] + params_reservoir['R_surface']) * \
                    np.sqrt((params_reservoir['R_surface'] - params_reservoir['R_fond'])**2 + params_reservoir['H_fluide']**2)
    masse_coque = surface_coque * params_fut['epaisseur'] * rho_beton
    
    masse_structure_vide = masse_fut + masse_coque
    
    # 3. Calculer la masse totale impulsive (Masse liquide impulsive + Masse structure)
    masse_totale_impulsive = params_liquide['Masse impulsive (kg)'] + masse_structure_vide

    # 4. Calculer la rigidité latérale du fût (formule pour une poutre cantilever)
    E_beton = 30e9  # Pa (30 GPa)
    # Moment d'inertie moyen du fût
    I_moyen = np.pi / 4 * (((params_fut['R_fut_base'] + params_fut['R_fut_sommet'])/2)**4 - 
                           (((params_fut['R_fut_base']-params_fut['epaisseur']) + 
                             (params_fut['R_fut_sommet']-params_fut['epaisseur']))/2)**4)
    
    K_fut = 3 * E_beton * I_moyen / (params_fut['H_fut']**3) # N/m

    # 5. Calculer la période impulsive Ti
    if masse_totale_impulsive > 0 and K_fut > 0:
        T_impulsive = 2 * np.pi * np.sqrt(masse_totale_impulsive / K_fut)
    else:
        T_impulsive = 0

    resultats_complets = {
        "--- LIQUIDE (HOUSNER) ---": params_liquide,
        "--- STRUCTURE ---": {
            "Masse du fût (kg)": masse_fut,
            "Masse de la coque (kg)": masse_coque,
            "Masse structure vide (kg)": masse_structure_vide,
            "Rigidité latérale du fût (N/m)": K_fut,
        },
        "--- DYNAMIQUE GLOBALE ---": {
            "Masse totale impulsive (kg)": masse_totale_impulsive,
            "Période impulsive Ti (s)": T_impulsive,
            "Période convective Tc (s)": params_liquide['Période convective (s)']
        }
    }
    return resultats_complets

# --- Exemple d'utilisation ---
if __name__ == "__main__":
    params_reservoir_exemple = {
        "H_fluide": 12.0, "R_fond": 4.0, "R_surface": 8.0
    }
    params_fut_exemple = {
        "H_fut": 30.0, "R_fut_base": 4.0, "R_fut_sommet": 3.0, "epaisseur": 0.4
    }

    analyse = analyser_chateau_eau_complet(params_reservoir_exemple, params_fut_exemple)

    if analyse:
        print("\n--- ANALYSE COMPLÈTE DU CHÂTEAU D'EAU ---")
        for section, data in analyse.items():
            print(f"\n{section}")
            if isinstance(data, dict):
                for cle, valeur in data.items():
                    print(f"{cle}: {valeur:.2f}")