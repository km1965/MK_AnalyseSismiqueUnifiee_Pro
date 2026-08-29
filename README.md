# MK_AnalyseSismiqueUnifiée_Pro

Application de bureau (Python + PySide6) pour l'analyse sismique et le
dimensionnement de structures civiles contenant des liquides, selon la
**méthode de Housner** (modèle à deux masses) couplée aux règlements
**RPS 2011 (Maroc)** et **Eurocode 8**.

## Fonctionnalités

- **Onglet Entrées** : château d'eau surélevé (cuve conique, fût tronconique)
  ou réservoir semi-enterré (circulaire / rectangulaire). L'épaisseur du fût
  et celle de la cuve sont indépendantes. Choix du règlement, de la zone, de la
  classe de sol et du facteur de comportement `q`.
- **Onglet Fondations** : radier général (circulaire / tronconique pour les
  châteaux d'eau et réservoirs circulaires ; rectangulaire / carré pour les
  réservoirs rectangulaires). Vérification des contraintes de contact, du
  décollement (noyau), du glissement et du renversement, ainsi que du
  poinçonnement pour les charges concentrées. **Auto-dimensionnement** du radier.
- **Onglet Armatures** (activé uniquement si stabilité **et** fondation sont
  conformes) : ferraillage du radier et des parois/coque. La norme est **couplée
  automatiquement** au règlement sismique (**BAEL 91** si RPS 2011, **Eurocode 2**
  si EC8).
- **Export** : note de calcul **PDF**, **DOCX** (avec croquis de coupe) et **CSV**.

## Chaîne de validation

```
Analyse sismique ──▶ Vérification stabilité (préliminaire)
        │
        ▼
  Onglet Fondations ──▶ Vérification radier (σ, noyau, glissement, poinçonnement)
        │  (conforme ?)
        ▼
  Onglet Armatures ──▶ Ferraillage radier + parois/coque
```

## Structure du projet

```
core/
  results.py          Modèle de rapport structuré (Report / Item)
  reglements.py       RPS 2011 & EC8 + spectre de calcul (branches complètes)
  housner.py          Paramètres Housner (conique, cylindrique, rectangulaire)
  stability.py        Vérification glissement / renversement (paramétrable)
  analyse_structure.py  Orchestration des analyses
  foundation.py       Dimensionnement & vérification du radier
  reinforcement.py    Calcul des armatures (BAEL 91 / EC2)
gui/
  main_window.py      Interface à onglets (PySide6)
reporting/
  pdf_generator.py    Note de calcul PDF
  docx_generator.py   Note de calcul DOCX (+ croquis)
  sketch.py           Croquis de coupe (Pillow)
tests/
  test_analysis.py    Tests de non-régression & valeurs de référence
```

## Références

- Housner G.W., *Dynamic pressures on fluid containers*, 1963.
- RPS 2011 (Maroc), annexes sismiques.
- Eurocode 8 (EN 1998-1) et Eurocode 2 (EN 1992-1-1).
- BAEL 91 modifié (référence historique Maroc).

## Installation

```bash
python -m venv env
source env/bin/activate        # Windows : env\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Tests

```bash
pytest tests/
```

> Les méthodes de ferraillage et de dimensionnement du radier sont des
> **pré-dimensionnements** documentés (coefficients simplifiés) ; elles ne
> remplacent pas un calcul d'exécution complet.
