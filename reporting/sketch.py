"""Génération de croquis de coupe (schéma simplifié) via Pillow.

Le croquis est purement indicatif (pré-dimensionnement) : il représente la
géométrie saisie et le radier proposé, sans mise à l'échelle structurale.
"""
from __future__ import annotations

import logging
import math
import os

from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


def draw_sketch(kind: str, geom: dict, fond: dict, path: str) -> str:
    """Dessine une coupe et l'enregistre en PNG. Retourne le chemin."""
    W, H = 800, 500
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    cx = W // 2

    def line(x1, y1, x2, y2):
        d.line([x1, y1, x2, y2], fill="black", width=2)

    def label(x, y, txt):
        d.text((x, y), txt, fill="black")

    # Ligne de sol
    sol_y = int(H * 0.65)

    # Radier
    fshape = fond.get("shape", "Rectangulaire")
    if fshape == "Circulaire":
        fw = fond.get("D", 20.0)
    elif fshape == "Tronconique":
        fw = fond.get("D_base", 20.0)
    elif fshape == "Carré":
        fw = fond.get("L", 20.0)
    else:
        fw = fond.get("L", 30.0)
    fh = fond.get("h_f", 1.0)
    scale = 220.0 / max(fw, 1.0)  # pixels par mètre (largeur radier ~220px)
    radier_w = fw * scale
    radier_h = max(8, fh * scale * 0.5)
    rx0, rx1 = cx - radier_w / 2, cx + radier_w / 2

    if fshape == "Tronconique":
        ftop = fond.get("D_sommet", fw * 0.7)
        rtx0, rtx1 = cx - (ftop * scale) / 2, cx + (ftop * scale) / 2
        d.polygon([(rx0, sol_y), (rx1, sol_y), (rtx1, sol_y + radier_h), (rtx0, sol_y + radier_h)],
                  outline="black", fill="lightgrey")
    else:
        d.rectangle([rx0, sol_y, rx1, sol_y + radier_h], outline="black", fill="lightgrey")

    if kind == "chateau_eau":
        H_f = geom.get("H_fluide", 12.0)
        Rf = geom.get("R_fond", 4.0)
        Rs = geom.get("R_surface", 8.0)
        H_t = geom.get("H_fut", 30.0)
        h_scale = scale
        top_y = sol_y - (H_t + H_f) * h_scale * 0.5
        tank_top = sol_y - H_t * h_scale * 0.5 - H_f * h_scale * 0.5
        # fût (tronc de cône)
        fb = geom.get("R_fut_base", Rf)
        fs = geom.get("R_fut_sommet", Rs)
        fb_px, fs_px = fb * h_scale * 0.5, fs * h_scale * 0.5
        fy0 = sol_y
        fy1 = sol_y - H_t * h_scale * 0.5
        line(cx - fb_px, fy0, cx - fs_px, fy1)
        line(cx + fb_px, fy0, cx + fs_px, fy1)
        # cuve conique
        rf_px, rs_px = Rf * h_scale * 0.5, Rs * h_scale * 0.5
        line(cx - fs_px, fy1, cx - rs_px, fy1 - H_f * h_scale * 0.5)
        line(cx + fs_px, fy1, cx + rs_px, fy1 - H_f * h_scale * 0.5)
        line(cx - rs_px, fy1 - H_f * h_scale * 0.5, cx + rs_px, fy1 - H_f * h_scale * 0.5)
        label(10, 10, "Château d'eau surélevé (coupe)")
        label(10, 30, f"Cuve H={H_f:.1f} m, R_f={Rf:.1f}/{Rs:.1f} m")
        label(10, 50, f"Fût H={H_t:.1f} m")
    elif kind == "reservoir_circulaire":
        H_f = geom.get("H_fluide", 5.0)
        D = geom.get("D", 20.0)
        He = geom.get("H_enterre", 3.0)
        s = scale
        rw = D * s * 0.5
        wall_top = sol_y - H_f * s * 0.5 - He * s * 0.5
        # corps cylindrique
        line(cx - rw, sol_y - He * s * 0.5, cx - rw, wall_top)
        line(cx + rw, sol_y - He * s * 0.5, cx + rw, wall_top)
        line(cx - rw, wall_top, cx + rw, wall_top)
        # enterré (hachuré)
        line(cx - rw, sol_y - He * s * 0.5, cx - rw, sol_y)
        line(cx + rw, sol_y - He * s * 0.5, cx + rw, sol_y)
        label(10, 10, "Réservoir circulaire semi-enterré (coupe)")
        label(10, 30, f"D={D:.1f} m, H_fluide={H_f:.1f} m, H_enterré={He:.1f} m")
    else:  # rectangulaire
        H_f = geom.get("H_fluide", 5.0)
        L = geom.get("L", 30.0)
        B = geom.get("B", 15.0)
        He = geom.get("H_enterre", 3.0)
        s = scale
        half = min(L, B) * s * 0.25
        top = sol_y - H_f * s * 0.5 - He * s * 0.5
        line(cx - half, sol_y - He * s * 0.5, cx - half, top)
        line(cx + half, sol_y - He * s * 0.5, cx + half, top)
        line(cx - half, top, cx + half, top)
        line(cx - half, sol_y - He * s * 0.5, cx - half, sol_y)
        line(cx + half, sol_y - He * s * 0.5, cx + half, sol_y)
        label(10, 10, "Réservoir rectangulaire semi-enterré (coupe)")
        label(10, 30, f"L={L:.1f} x B={B:.1f} m, H_fluide={H_f:.1f} m, H_enterré={He:.1f} m")

    label(W - 260, H - 30, "Échelle indicative – pré-dimensionnement")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    img.save(path)
    return path
