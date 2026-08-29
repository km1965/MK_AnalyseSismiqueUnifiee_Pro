"""Paramètres de Housner pour réservoirs liquides (modèle à 2 masses).

Référence : Housner G.W., « Dynamic pressures on fluid containers », 1963.
"""
from __future__ import annotations

import numpy as np

G = 9.81


def calculer_parametres_housner_conique(H_fluide, R_fond, R_surface):
    if H_fluide <= 0 or R_fond <= 0 or R_surface <= 0:
        return None
    gamma = R_surface / R_fond
    volume = (1 / 3) * np.pi * H_fluide * (R_fond**2 + R_surface**2 + R_fond * R_surface)
    masse_totale = volume * 1000.0
    psi_i = (gamma**2 + 2 * gamma + 3) / (gamma**2 + gamma + 1)
    I_R = H_fluide / R_surface
    m_imp = masse_totale * (1 - 0.58 * psi_i * np.tanh(1.5 * I_R) / I_R)
    h_imp = H_fluide * (0.5 - 0.09 * psi_i)
    m_conv = masse_totale * 0.29 * I_R * np.tanh(1.84 * I_R)
    h_conv = H_fluide * (1 - (np.cosh(1.84 * I_R) - 1.28) / (1.84 * I_R * np.sinh(1.84 * I_R)))
    omega_c = np.sqrt(1.84 * G * np.tanh(1.84 * I_R) / R_surface)
    T_conv = 2 * np.pi / omega_c
    return {
        "Masse totale (kg)": masse_totale,
        "Masse impulsive (kg)": m_imp,
        "Masse convective (kg)": m_conv,
        "Hauteur impulsive (m)": h_imp,
        "Hauteur convective (m)": h_conv,
        "Période convective (s)": T_conv,
    }


def calculer_parametres_housner_circulaire(H_fluide, D):
    masse_totale = (np.pi * D**2 / 4) * H_fluide * 1000.0
    I_R = D / H_fluide
    m_i = masse_totale * np.tanh(0.866 * I_R) / (0.866 * I_R)
    h_i = 0.375 * H_fluide
    m_c = masse_totale * 0.23 * I_R * np.tanh(3.68 * H_fluide / D)
    h_c = H_fluide * (1 - (np.cosh(3.68 * H_fluide / D) - 1) / (3.68 * H_fluide / D * np.sinh(3.68 * H_fluide / D)))
    omega_c = np.sqrt(3.68 * G / D * np.tanh(3.68 * H_fluide / D))
    T_c = 2 * np.pi / omega_c
    return {
        "Masse impulsive (kg)": m_i,
        "Hauteur impulsive (m)": h_i,
        "Masse convective (kg)": m_c,
        "Hauteur convective (m)": h_c,
        "Période convective (s)": T_c,
    }


def calculer_parametres_housner_rectangulaire(H_fluide, L):
    I_R = L / H_fluide
    m_i = H_fluide * L * 1000.0 * np.tanh(1.732 * I_R) / (1.732 * I_R)
    h_i = 0.375 * H_fluide
    m_c = H_fluide * L * 1000.0 * 0.264 * I_R * np.tanh(3.16 * H_fluide / L)
    h_c = H_fluide * (1 - (np.cosh(3.16 * H_fluide / L) - 1) / (3.16 * H_fluide / L * np.sinh(3.16 * H_fluide / L)))
    omega_c = np.sqrt(3.16 * G / L * np.tanh(3.16 * H_fluide / L))
    T_c = 2 * np.pi / omega_c
    return {
        "Masse impulsive (kg/m)": m_i,
        "Hauteur impulsive (m)": h_i,
        "Masse convective (kg/m)": m_c,
        "Hauteur convective (m)": h_c,
        "Période convective (s)": T_c,
    }
