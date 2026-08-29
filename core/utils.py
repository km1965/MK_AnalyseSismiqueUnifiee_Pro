"""Utilitaires de saisie et de formatage."""
from __future__ import annotations


def lire_valeur(champ, nom_champ):
    texte = champ.text().strip().replace(",", ".")
    try:
        valeur = float(texte)
        if valeur <= 0:
            raise ValueError
        return valeur
    except ValueError:
        raise ValueError(f"Le champ « {nom_champ} » contient une valeur invalide : « {texte} »")


def lire_valeur_strict(champ, nom_champ, strict_positive=True, default=None):
    """Lit un float, tolère une valeur vide si ``default`` est fourni."""
    texte = champ.text().strip().replace(",", ".")
    if texte == "" and default is not None:
        return default
    try:
        valeur = float(texte)
    except ValueError:
        raise ValueError(f"Le champ « {nom_champ} » contient une valeur invalide : « {texte} »")
    if strict_positive and valeur <= 0:
        raise ValueError(f"Le champ « {nom_champ} » doit être strictement positif.")
    return valeur
