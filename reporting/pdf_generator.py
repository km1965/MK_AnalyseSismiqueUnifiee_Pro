"""Génération de la note de calcul au format PDF (reportlab) à partir d'un Report."""
from __future__ import annotations

import logging
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

from core.results import Report

logger = logging.getLogger(__name__)


def generer_note_calcul_pdf(nom_fichier: str, rapport: Report, sketch_path: str = None):
    c = canvas.Canvas(nom_fichier, pagesize=A4)
    width, height = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 2 * cm, "Note de Calcul d'Analyse Sismique")
    c.setFont("Helvetica", 9)
    c.drawString(2 * cm, height - 3 * cm, f"Date : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    c.drawString(2 * cm, height - 3.6 * cm, f"Titre : {rapport.title}")

    if sketch_path:
        try:
            c.drawImage(sketch_path, width - 7 * cm, height - 8 * cm, width=5 * cm, height=3.5 * cm)
        except Exception as e:  # noqa: BLE001
            logger.warning("Croquis non inclus : %s", e)

    text = c.beginText(2 * cm, height - 4.5 * cm)
    text.setFont("Courier", 9)

    for title, items in rapport.sections:
        text.setFont("Courier-Bold", 11)
        text.textLine(f"\n{title}")
        text.setFont("Courier", 9)
        for it in items:
            val = it.formatted()
            suffix = f" [{it.verdict}]" if it.verdict else ""
            note = f"  ({it.note})" if it.note else ""
            text.textLine(f"  {it.label:<34}: {val} {it.unit}{suffix}{note}")

    c.drawText(text)
    c.showPage()
    c.save()
    logger.info("Note de calcul PDF générée : %s", nom_fichier)
