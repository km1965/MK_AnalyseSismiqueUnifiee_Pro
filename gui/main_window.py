# gui/main_window.py
from __future__ import annotations

import logging
import os
import tempfile

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QComboBox, QTextEdit, QGroupBox, QFormLayout, QGridLayout, QTabWidget,
    QFileDialog, QMessageBox, QMenu, QMenuBar,
)
import csv

from core.analyse_structure import analyser_chateau_eau_complet, analyser_reservoir_semi_enterre
from core.foundation import FoundationInput, analyser_fondation, auto_dimensionner, SHAPES
from core.reinforcement import calculer_armatures
from core.utils import lire_valeur
from core.results import Report
from reporting.pdf_generator import generer_note_calcul_pdf
from reporting.docx_generator import generer_note_calcul_docx
from reporting.sketch import draw_sketch

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Analyse Sismique Unifiée Pro")
        self.setMinimumSize(1100, 720)
        self._apply_style()

        icon_path = os.path.join(os.path.dirname(__file__), "..", "assets", "icone.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # État
        self.rapport_analyse: Report | None = None
        self.rapport_fondation: Report | None = None
        self.rapport_armatures: Report | None = None
        self.foundation_input: FoundationInput | None = None
        self.fondation_ok = False
        self.armatures_ok = False
        self.regulation = "RPS 2011"

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.tabs = QTabWidget()
        self.tab_entrees = QWidget()
        self.tab_fondations = QWidget()
        self.tab_armatures = QWidget()
        self.tabs.addTab(self.tab_entrees, "1. Entrées")
        self.tabs.addTab(self.tab_fondations, "2. Fondations")
        self.tabs.addTab(self.tab_armatures, "3. Armatures")
        self.tabs.setTabEnabled(1, False)
        self.tabs.setTabEnabled(2, False)
        root.addWidget(self.tabs, 1)

        self._build_entrees()
        self._build_fondations()
        self._build_armatures()
        self._build_menu()
        self._refresh_fond_shape()

        # Résultats + actions
        root.addWidget(QLabel("<h3>Résultats :</h3>"))
        self.results_display = QTextEdit()
        self.results_display.setReadOnly(True)
        root.addWidget(self.results_display, 2)

        actions = QHBoxLayout()
        self.pdf_button = QPushButton("Générer PDF")
        self.csv_button = QPushButton("Exporter CSV")
        self.docx_button = QPushButton("Générer DOCX")
        for b in (self.pdf_button, self.csv_button, self.docx_button):
            b.setEnabled(False)
        actions.addStretch()
        actions.addWidget(self.pdf_button)
        actions.addWidget(self.csv_button)
        actions.addWidget(self.docx_button)
        actions.addStretch()
        root.addLayout(actions)

        self.pdf_button.clicked.connect(self.generer_pdf)
        self.csv_button.clicked.connect(self.exporter_csv)
        self.docx_button.clicked.connect(self.generer_docx)

    # ------------------------------------------------------------------ style
    def _apply_style(self):
        self.setStyleSheet("""
        QWidget { background-color: #fdfcfb; font-family: 'Segoe UI','Arial'; font-size: 11pt; color: #2c2c2c; }
        QLabel { font-weight: bold; color: #1e3d59; }
        QComboBox, QLineEdit, QTextEdit { background-color: #ffffff; border: 1px solid #cccccc; border-radius: 4px; padding: 4px; }
        QPushButton { background-color: #0078d7; color: white; border: none; border-radius: 5px; padding: 6px 12px; }
        QPushButton:hover { background-color: #005a9e; }
        QPushButton:disabled { background-color: #cccccc; color: #666666; }
        QGroupBox { font-weight: bold; color: #1e3d59; border: 1px solid #cccccc; border-radius: 6px; margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; }
        QTabWidget::pane { border: 1px solid #cccccc; border-radius: 6px; }
        """)

    # --------------------------------------------------------------- Entrées
    def _build_entrees(self):
        layout = QVBoxLayout(self.tab_entrees)
        layout.addWidget(QLabel("<h3>Type de structure :</h3>"))
        self.struct_type_combo = QComboBox()
        self.struct_type_combo.addItems(["Château d'Eau Surélevé", "Réservoir Semi-Enterré"])
        layout.addWidget(self.struct_type_combo)

        self.setup_chateau_eau_group()
        self.setup_reservoir_enterre_group()
        self.setup_sismique_group()
        layout.addWidget(self.chateau_eau_group)
        layout.addWidget(self.reservoir_enterre_group)
        layout.addWidget(self.sismique_group)

        calc = QPushButton("Lancer l'Analyse")
        calc.clicked.connect(self.run_analysis)
        layout.addWidget(calc)
        layout.addStretch()

        self.struct_type_combo.currentTextChanged.connect(self.update_ui_for_structure)
        self.geom_combo_re.currentTextChanged.connect(self.update_re_geom_fields)
        self.geom_combo_re.currentTextChanged.connect(self._refresh_fond_shape)
        self.update_ui_for_structure(self.struct_type_combo.currentText())

    def setup_chateau_eau_group(self):
        self.chateau_eau_group = QGroupBox("Paramètres du Château d'Eau")
        g = QGridLayout()
        self.h_fluide_ce = QLineEdit("10.0"); self.r_fond_ce = QLineEdit("5.0"); self.r_surface_ce = QLineEdit("9.0")
        self.h_fut_ce = QLineEdit("25.0"); self.r_fut_base_ce = QLineEdit("8.0")
        self.r_fut_sommet_ce = QLineEdit("5.0"); self.ep_fut_ce = QLineEdit("0.5")
        self.ep_cuve_ce = QLineEdit("0.4")
        # Coupoles (saisies 1re page -> poids dans le dimensionnement)
        self.cs_d = QLineEdit("18.0"); self.cs_f = QLineEdit("1.80"); self.cs_e = QLineEdit("0.30")
        self.ci_d = QLineEdit("10.0"); self.ci_f = QLineEdit("1.25"); self.ci_e = QLineEdit("0.30")
        # Ceintures de liaison (section rectangulaire : largeur l, hauteur h)
        self.cs_l = QLineEdit("0.40"); self.cs_h = QLineEdit("0.60")
        self.ci_l = QLineEdit("0.50"); self.ci_h = QLineEdit("0.70")

        def add_row(row, specs):
            for i, (lbl, w) in enumerate(specs):
                g.addWidget(QLabel(lbl), row, i * 2)
                g.addWidget(w, row, i * 2 + 1)

        add_row(0, [("H_fluide (m)", self.h_fluide_ce), ("R_fond (m)", self.r_fond_ce),
                    ("R_surface (m)", self.r_surface_ce), ("Épais. cuve (m)", self.ep_cuve_ce)])
        add_row(1, [("H_fût (m)", self.h_fut_ce), ("R_fût base (m)", self.r_fut_base_ce),
                    ("R_fût sommet (m)", self.r_fut_sommet_ce), ("Épais. fût (m)", self.ep_fut_ce)])
        g.addWidget(QLabel("<b>Coupole sup</b> (flèche ≥ D/10, Fasc.74)"), 2, 0, 1, 6)
        add_row(3, [("D base = 2·R_surface (m)", self.cs_d), ("flèche f (m)", self.cs_f),
                    ("épais. e (m)", self.cs_e)])
        g.addWidget(QLabel("<b>Coupole inf</b> (flèche ≥ d/8, Fasc.74)"), 4, 0, 1, 6)
        add_row(5, [("d base = 2·R_fond (m)", self.ci_d), ("flèche f (m)", self.ci_f),
                    ("épais. e (m)", self.ci_e)])
        g.addWidget(QLabel("<b>Ceinture sup</b> (anneau cuve ↔ coupole sup)"), 6, 0, 1, 6)
        add_row(7, [("largeur l (m)", self.cs_l), ("hauteur h (m)", self.cs_h)])
        g.addWidget(QLabel("<b>Ceinture inf</b> (anneau fût ↔ cuve ↔ coupole inf)"), 8, 0, 1, 6)
        add_row(9, [("largeur l (m)", self.ci_l), ("hauteur h (m)", self.ci_h)])
        self.chateau_eau_group.setLayout(g)
        # D base et d base suivent les rayons (formules) mais restent éditables
        self.r_surface_ce.textChanged.connect(
            lambda _: self._maj_diametre_coupole(self.r_surface_ce, self.cs_d))
        self.r_fond_ce.textChanged.connect(
            lambda _: self._maj_diametre_coupole(self.r_fond_ce, self.ci_d))

    def _maj_diametre_coupole(self, radius_edit, diam_edit):
        try:
            r = float(radius_edit.text())
        except ValueError:
            return
        diam_edit.setText(f"{2.0 * r:.2f}")

    def setup_reservoir_enterre_group(self):
        self.reservoir_enterre_group = QGroupBox("Paramètres du Réservoir Semi-Enterré")
        g = QGridLayout()
        self.geom_combo_re = QComboBox(); self.geom_combo_re.addItems(["Circulaire", "Rectangulaire"])
        self.h_fluide_re = QLineEdit("5.0"); self.h_enterre_re = QLineEdit("3.0"); self.soil_gamma_re = QLineEdit("18.0")
        self.diam_re = QLineEdit("20.0"); self.long_re = QLineEdit("30.0"); self.larg_re = QLineEdit("15.0")
        self.soil_phi_re = QLineEdit("30.0"); self.e_paroi_re = QLineEdit("0.30")
        self.h_radier_re = QLineEdit("0.40"); self.e_couv_re = QLineEdit("0.25")
        self.h_couv_re = QLineEdit("0.0")
        self.lbl_d = QLabel("Diamètre D (m):"); self.lbl_l = QLabel("Longueur L (dir. séisme) (m):")
        self.lbl_b = QLabel("Largeur B (m):")
        g.addWidget(QLabel("Géométrie:"), 0, 0); g.addWidget(self.geom_combo_re, 0, 1)
        g.addWidget(QLabel("H_fluide (m):"), 1, 0); g.addWidget(self.h_fluide_re, 1, 1)
        g.addWidget(QLabel("H_enterre (m):"), 1, 2); g.addWidget(self.h_enterre_re, 1, 3)
        g.addWidget(QLabel("γ sol (kN/m³):"), 2, 0); g.addWidget(self.soil_gamma_re, 2, 1)
        g.addWidget(QLabel("φ sol (°):"), 2, 2); g.addWidget(self.soil_phi_re, 2, 3)
        g.addWidget(self.lbl_d, 3, 0); g.addWidget(self.diam_re, 3, 1)
        g.addWidget(self.lbl_l, 3, 2); g.addWidget(self.long_re, 3, 3)
        g.addWidget(self.lbl_b, 4, 0); g.addWidget(self.larg_re, 4, 1)
        g.addWidget(QLabel("Épais. paroi (m):"), 4, 2); g.addWidget(self.e_paroi_re, 4, 3)
        g.addWidget(QLabel("Épais. radier (m):"), 5, 0); g.addWidget(self.h_radier_re, 5, 1)
        g.addWidget(QLabel("Épais. couverture (m):"), 5, 2); g.addWidget(self.e_couv_re, 5, 3)
        g.addWidget(QLabel("H couverture sol (m):"), 6, 0); g.addWidget(self.h_couv_re, 6, 1)
        self.reservoir_enterre_group.setLayout(g)

    def setup_sismique_group(self):
        self.sismique_group = QGroupBox("Paramètres Sismiques")
        g = QGridLayout()
        self.regulation_combo = QComboBox(); self.regulation_combo.addItems(["RPS 2011", "EC8"])
        self.zone_combo = QComboBox(); self.zone_combo.addItems(
            ["Zone 1 (0.07g)", "Zone 2 (0.10g)", "Zone 3 (0.13g)", "Zone 4 (0.17g)"])
        self.soil_combo = QComboBox(); self.soil_combo.addItems(["S1 (1.00)", "S2 (1.20)", "S3 (1.40)", "S4 (1.80)"])
        self.q_input = QLineEdit("2.0")
        g.addWidget(QLabel("Règlement:"), 0, 0); g.addWidget(self.regulation_combo, 0, 1)
        g.addWidget(QLabel("Zone:"), 0, 2); g.addWidget(self.zone_combo, 0, 3)
        g.addWidget(QLabel("Sol:"), 0, 4); g.addWidget(self.soil_combo, 0, 5)
        g.addWidget(QLabel("q:"), 0, 6); g.addWidget(self.q_input, 0, 7)
        self.sismique_group.setLayout(g)
        self.regulation_combo.currentTextChanged.connect(lambda t: setattr(self, "regulation", t))

    def update_ui_for_structure(self, struct_type):
        is_ce = struct_type == "Château d'Eau Surélevé"
        self.chateau_eau_group.setVisible(is_ce)
        self.reservoir_enterre_group.setVisible(not is_ce)
        if not is_ce:
            self.update_re_geom_fields(self.geom_combo_re.currentText())

    def update_re_geom_fields(self, geom_type):
        is_circ = geom_type == "Circulaire"
        self.lbl_d.setVisible(is_circ); self.diam_re.setVisible(is_circ)
        self.lbl_l.setVisible(not is_circ); self.long_re.setVisible(not is_circ)
        self.lbl_b.setVisible(not is_circ); self.larg_re.setVisible(not is_circ)

    # ------------------------------------------------------------- Fondations
    def _build_fondations(self):
        layout = QVBoxLayout(self.tab_fondations)
        self.fond_shape_combo = QComboBox()
        layout.addWidget(QLabel("Forme du radier général :"))
        layout.addWidget(self.fond_shape_combo)

        f = QFormLayout()
        self.f_D = QLineEdit("0"); self.f_Db = QLineEdit("20.0"); self.f_Ds = QLineEdit("0")
        self.f_L = QLineEdit("0"); self.f_B = QLineEdit("0"); self.f_hf = QLineEdit("1.0")
        self.f_over = QLineEdit("0.50"); self.f_hdisk = QLineEdit("0.50"); self.f_hcone = QLineEdit("1.00")
        self.f_qadm = QLineEdit("200.0"); self.f_mu = QLineEdit("0.5")
        self.f_fck = QLineEdit("25.0"); self.f_fy = QLineEdit("400.0")
        self.f_cover = QLineEdit("0.05"); self.f_bar = QLineEdit("0.016")
        self.lbl_fd = QLabel("Diamètre D (m):"); self.lbl_fdb = QLabel("Diamètre base D_base (m):")
        self.lbl_fds = QLabel("Diamètre sommet (m):"); self.lbl_fl = QLabel("Longueur L (m):")
        self.lbl_fb = QLabel("Largeur B (m):")
        self.lbl_over = QLabel("Débord par côté (m):"); self.lbl_hdisk = QLabel("Hauteur disque base (m):")
        self.lbl_hcone = QLabel("Hauteur tronc (m):")
        f.addRow(self.lbl_fd, self.f_D)
        f.addRow(self.lbl_fdb, self.f_Db); f.addRow(self.lbl_fds, self.f_Ds)
        f.addRow(self.lbl_fl, self.f_L); f.addRow(self.lbl_fb, self.f_B)
        f.addRow(self.lbl_over, self.f_over)
        f.addRow(self.lbl_hdisk, self.f_hdisk); f.addRow(self.lbl_hcone, self.f_hcone)
        f.addRow("Épaisseur radier h_f (m):", self.f_hf)
        f.addRow("Contrainte admissible sol q_adm (kPa):", self.f_qadm)
        f.addRow("Coefficient frottement μ:", self.f_mu)
        f.addRow("Béton fck (MPa):", self.f_fck)
        f.addRow("Acier fy (MPa):", self.f_fy)
        f.addRow("Enrobage (m):", self.f_cover)
        f.addRow("Diamètre barre princi. (m):", self.f_bar)
        self.fond_form = QGroupBox("Géométrie & matériaux du radier")
        self.fond_form.setLayout(f)
        layout.addWidget(self.fond_form)

        h = QHBoxLayout()
        self.btn_verif_fond = QPushButton("Vérifier la fondation")
        self.btn_auto_fond = QPushButton("Auto-dimensionner")
        h.addStretch(); h.addWidget(self.btn_verif_fond); h.addWidget(self.btn_auto_fond); h.addStretch()
        layout.addLayout(h)
        layout.addStretch()

        self.btn_verif_fond.clicked.connect(self.run_foundation)
        self.btn_auto_fond.clicked.connect(self.auto_foundation)
        self.struct_type_combo.currentTextChanged.connect(self._refresh_fond_shape)
        self.fond_shape_combo.currentTextChanged.connect(self.update_fond_fields)

    def _refresh_fond_shape(self, *_):
        if self.struct_type_combo.currentText() == "Château d'Eau Surélevé":
            self.fond_shape_combo.clear()
            self.fond_shape_combo.addItems(["Circulaire", "Tronconique"])
            self.fond_shape_combo.setCurrentText("Tronconique")
        else:
            if self.geom_combo_re.currentText() == "Circulaire":
                self.fond_shape_combo.clear()
                self.fond_shape_combo.addItems(["Circulaire", "Tronconique"])
                self.fond_shape_combo.setCurrentText("Circulaire")
            else:
                self.fond_shape_combo.clear()
                self.fond_shape_combo.addItems(["Rectangulaire", "Carré"])
                self.fond_shape_combo.setCurrentText("Rectangulaire")
        self.update_fond_fields(self.fond_shape_combo.currentText())

    def update_fond_fields(self, shape):
        is_circ = shape == "Circulaire"
        is_tronc = shape == "Tronconique"
        is_carre = shape == "Carré"
        # D dérivé (empreinte cuve + débord) -> masqué, sauf tronconique (D_base libre)
        self.lbl_fd.setVisible(False); self.f_D.setVisible(False)
        self.lbl_fds.setVisible(False); self.f_Ds.setVisible(False)
        self.lbl_fdb.setVisible(is_tronc); self.f_Db.setVisible(is_tronc)
        self.lbl_over.setVisible(True); self.f_over.setVisible(True)
        self.lbl_hdisk.setVisible(is_tronc); self.f_hdisk.setVisible(is_tronc)
        self.lbl_hcone.setVisible(is_tronc); self.f_hcone.setVisible(is_tronc)
        # L/B dérivés pour rectangulaire/carré -> masqués
        self.lbl_fl.setVisible(False); self.f_L.setVisible(False)
        self.lbl_fb.setVisible(False); self.f_B.setVisible(False)

    # -------------------------------------------------------------- Armatures
    def _build_armatures(self):
        layout = QVBoxLayout(self.tab_armatures)
        self.arm_label = QLabel("Norme de ferraillage : <b>couplée automatiquement</b> au règlement sismique "
                                "(BAEL 91 si RPS 2011, EC2 si EC8).\n\n"
                                "Le calcul des armatures (radier + parois/coque + coupoles ou couverture) "
                                "n'est possible qu'après conformité des vérifications de stabilité ET de fondation.")
        layout.addWidget(self.arm_label)

        fopt = QFormLayout()
        self.arm_wmax = QLineEdit("0.20")
        self.arm_qcouv = QLineEdit("1.50")
        self.arm_qlan = QLineEdit("10.0")
        self.arm_ecouv = QLineEdit("")
        fopt.addRow("Limite fissuration w_max (mm) :", self.arm_wmax)
        fopt.addRow("Charge couverture q_couv (kN/m²) :", self.arm_qcouv)
        fopt.addRow("Charge lanterneau Q (kN) :", self.arm_qlan)
        fopt.addRow("Épaisseur dalle couverture (m) :", self.arm_ecouv)
        layout.addLayout(fopt)

        self.btn_arm = QPushButton("Calculer les armatures")
        self.btn_arm.setEnabled(False)
        self.btn_arm.clicked.connect(self.run_armatures)
        h = QHBoxLayout(); h.addStretch(); h.addWidget(self.btn_arm); h.addStretch()
        layout.addLayout(h)
        layout.addStretch()

    # -------------------------------------------------------------- Menu
    def _build_menu(self):
        menubar = self.menuBar()

        def a_venir(msg):
            QMessageBox.information(self, "À venir", f"Fonctionnalité prévue (feuille de route) :\n{msg}")

        # ---- Fichier ----
        fichier = menubar.addMenu("Fichier")
        fichier.addAction("Nouveau…", lambda: a_venir("Nouveau projet (fichier .mkpro)"))
        fichier.addAction("Ouvrir…", lambda: a_venir("Ouvrir un projet (.mkpro)"))
        fichier.addAction("Enregistrer", lambda: a_venir("Enregistrer le projet (.mkpro)"))
        fichier.addSeparator()
        fichier.addAction("Lancer l'Analyse", self.run_analysis)
        fichier.addAction("Exporter PDF…", self.generer_pdf)
        fichier.addAction("Exporter DOCX…", self.generer_docx)
        fichier.addAction("Exporter CSV…", self.exporter_csv)
        fichier.addSeparator()
        fichier.addAction("Quitter", self.close)

        # ---- Édition ----
        edition = menubar.addMenu("Édition")
        edition.addAction("Annuler", lambda: a_venir("Annuler / Rétablir"))
        edition.addAction("Rétablir", lambda: a_venir("Annuler / Rétablir"))
        edition.addAction("Copier les paramètres", lambda: a_venir("Copier les paramètres d'un ouvrage à l'autre"))
        edition.addAction("Paramètres par défaut", lambda: a_venir("Restaurer les usines"))

        # ---- Analyse ----
        analyse = menubar.addMenu("Analyse")
        analyse.addAction("Lancer l'analyse sismique", self.run_analysis)
        analyse.addAction("Vérifier la fondation", self.run_foundation)
        analyse.addAction("Auto-dimensionner le radier", self.auto_foundation)
        analyse.addAction("Calculer les armatures", self.run_armatures)
        analyse.addAction("Réinitialiser les résultats", self.reinitialiser_resultats)

        # ---- Affichage ----
        affichage = menubar.addMenu("Affichage")
        affichage.addAction("Agrandir les croquis", lambda: a_venir("Zoom des croquis"))
        affichage.addAction("Thème clair / sombre", lambda: a_venir("Bascule thème clair/sombre"))

        # ---- Outils ----
        outils = menubar.addMenu("Outils")
        outils.addAction("Règlements (RPS 2011 / EC8)", lambda: a_venir("Éditeur de règlements & spectres"))
        outils.addAction("Bibliothèque de sols", lambda: a_venir("Bibliothèque de sols (φ, γ, δ)"))
        outils.addAction("Bibliothèque bétons/aciers", lambda: a_venir("Bibliothèque de bétons & aciers"))
        outils.addAction("Comparateur de scénarios", lambda: a_venir("Comparateur vide vs plein / plusieurs géométries"))

        # ---- Langue ----
        langue = menubar.addMenu("Langue")
        langue.addAction("Français", lambda: a_venir("Basculer l'interface en français"))
        langue.addAction("English", lambda: a_venir("Switch interface to English"))
        langue.addAction("العربية", lambda: a_venir("تبديل الواجهة إلى العربية"))

        # ---- Aide ----
        aide = menubar.addMenu("?")
        aide.addAction("À propos", self.a_propos)
        aide.addAction("Guide de prise en main", lambda: a_venir("Guide de prise en main"))
        aide.addAction("Références", self.references)

    def a_propos(self):
        QMessageBox.about(
            self, "À propos — MK_AnalyseSismiqueUnifiée_Pro",
            "Outil d'analyse sismique et de dimensionnement pour châteaux d'eau "
            "surélevés et réservoirs (semi-)enterrés.\n\n"
            "Méthodes : Housner (liquide), Mononobe–Okabe (terres), combinaisons "
            "VIDE / PLEIN. Règlements : RPS 2011 (Maroc) et Eurocode 8.\n\n"
            "Pré-dimensionnement documenté — à vérifier par un ingénieur.")

    def references(self):
        QMessageBox.information(
            self, "Références",
            "• Housner G.W., Dynamic pressures on fluid containers, 1963.\n"
            "• Mononobe N. & Okabe S., Earth pressure during earthquakes, 1929.\n"
            "• RPS 2011 (Maroc), annexes sismiques.\n"
            "• Eurocode 8 (EN 1998-1) et Eurocode 2 (EN 1992-1-1).\n"
            "• BAEL 91 modifié (référence historique Maroc).\n"
            "• Fascicule 74 (cuves en béton armé, fissuration).")

    def reinitialiser_resultats(self):
        self.rapport_analyse = None
        self.rapport_fondation = None
        self.rapport_armatures = None
        self.foundation_input = None
        self.fondation_ok = False
        self.armatures_ok = False
        self.tabs.setTabEnabled(1, False)
        self.tabs.setTabEnabled(2, False)
        self.btn_arm.setEnabled(False)
        self._disable_exports()
        self.results_display.clear()

    # ------------------------------------------------------------- Analyse
    def _read_analysis(self):
        struct = self.struct_type_combo.currentText()
        params_sismiques = {
            "regulation": self.regulation_combo.currentText(),
            "zone": self.zone_combo.currentText(),
            "soil": self.soil_combo.currentText(),
            "q": lire_valeur(self.q_input, "q"),
        }
        if struct == "Château d'Eau Surélevé":
            params_reservoir = {
                "H_fluide": lire_valeur(self.h_fluide_ce, "H_fluide"),
                "R_fond": lire_valeur(self.r_fond_ce, "R_fond"),
                "R_surface": lire_valeur(self.r_surface_ce, "R_surface"),
                # Coupoles saisies 1re page -> poids dans le dimensionnement
                "coupole_sup_D": lire_valeur(self.cs_d, "D coupole sup"),
                "coupole_sup_f": lire_valeur(self.cs_f, "flèche coupole sup"),
                "coupole_sup_e": lire_valeur(self.cs_e, "épais. coupole sup"),
                "coupole_inf_d": lire_valeur(self.ci_d, "d coupole inf"),
                "coupole_inf_f": lire_valeur(self.ci_f, "flèche coupole inf"),
                "coupole_inf_e": lire_valeur(self.ci_e, "épais. coupole inf"),
                "ceinture_sup_l": lire_valeur(self.cs_l, "largeur ceinture sup"),
                "ceinture_sup_h": lire_valeur(self.cs_h, "hauteur ceinture sup"),
                "ceinture_inf_l": lire_valeur(self.ci_l, "largeur ceinture inf"),
                "ceinture_inf_h": lire_valeur(self.ci_h, "hauteur ceinture inf"),
            }
            params_fut = {
                "H_fut": lire_valeur(self.h_fut_ce, "H_fut"),
                "R_fut_base": lire_valeur(self.r_fut_base_ce, "R_fut_base"),
                "R_fut_sommet": lire_valeur(self.r_fut_sommet_ce, "R_fut_sommet"),
                "epaisseur_fut": lire_valeur(self.ep_fut_ce, "épaisseur fût"),
            }
            ep_cuve = lire_valeur(self.ep_cuve_ce, "épaisseur cuve")
            return struct, params_reservoir, params_fut, params_sismiques, ep_cuve
        params_geom = {
            "type": self.geom_combo_re.currentText(),
            "H_fluide": lire_valeur(self.h_fluide_re, "H_fluide"),
            "H_enterre": lire_valeur(self.h_enterre_re, "H_enterre"),
            "soil_gamma": lire_valeur(self.soil_gamma_re, "γ sol"),
            "soil_phi": lire_valeur(self.soil_phi_re, "φ sol"),
            "e_paroi": lire_valeur(self.e_paroi_re, "épais. paroi"),
            "h_radier": lire_valeur(self.h_radier_re, "épais. radier"),
            "e_couv": lire_valeur(self.e_couv_re, "épais. couverture"),
            "H_couverture": lire_valeur(self.h_couv_re, "H couverture sol"),
        }
        if params_geom["type"] == "Circulaire":
            params_geom["D"] = lire_valeur(self.diam_re, "D")
        else:
            params_geom["L"] = lire_valeur(self.long_re, "L")
            params_geom["B"] = lire_valeur(self.larg_re, "B")
        return struct, params_geom, None, params_sismiques, None

    def run_analysis(self):
        try:
            struct, p1, p2, ps, ep = self._read_analysis()
            if struct == "Château d'Eau Surélevé":
                report, err = analyser_chateau_eau_complet(p1, p2, ps, epaisseur_cuve=ep)
            else:
                report, err = analyser_reservoir_semi_enterre(p1, ps)
        except ValueError as e:
            QMessageBox.warning(self, "Saisie invalide", str(e))
            return

        if err or report is None:
            self.rapport_analyse = None
            self.tabs.setTabEnabled(1, False)
            self.tabs.setTabEnabled(2, False)
            self._disable_exports()
            self.results_display.setText(err or "Erreur inconnue.")
            return

        self.rapport_analyse = report
        self.rapport_fondation = None
        self.rapport_armatures = None
        self.fondation_ok = False
        self.armatures_ok = False
        self.tabs.setTabEnabled(1, True)
        self.tabs.setTabEnabled(2, False)
        self.btn_arm.setEnabled(False)
        self._refresh_fond_shape()
        self._enable_exports()
        self._show_report(report)
        self.tabs.setCurrentIndex(1)

    # ------------------------------------------------------------- Fondation
    def _read_foundation(self):
        shape = self.fond_shape_combo.currentText()
        fi = FoundationInput(shape=shape)
        fi.q_adm = lire_valeur(self.f_qadm, "q_adm")
        fi.mu = lire_valeur(self.f_mu, "μ")
        fi.fck = lire_valeur(self.f_fck, "fck")
        fi.fy = lire_valeur(self.f_fy, "fy")
        fi.cover = lire_valeur(self.f_cover, "enrobage")
        fi.bar_diam = lire_valeur(self.f_bar, "diamètre barre")
        fi.h_f = lire_valeur(self.f_hf, "h_f")
        fi.overhang = lire_valeur(self.f_over, "débord")
        fi.h_disk = lire_valeur(self.f_hdisk, "hauteur disque base")
        fi.h_cone = lire_valeur(self.f_hcone, "hauteur tronc")
        if shape == "Tronconique":
            fi.D_base = lire_valeur(self.f_Db, "D_base")
        tank = self.rapport_analyse.meta.get("geometry", {}) if self.rapport_analyse else {}
        from core.foundation import resolve_foundation
        resolve_foundation(fi, tank)
        return fi

    def _foundation_load(self):
        m = self.rapport_analyse.meta
        # On vérifie CHAQUE combinaison (vide / plein) ; la pire gouverne.
        if "combinaisons" in m and m["combinaisons"]:
            return m["combinaisons"]
        return {
            "N_total_kN": m["N_total_kN"], "V_total_kN": m["V_total_kN"],
            "M_total_kNm": m["M_total_kNm"],
            "col_diameter_m": 2 * m.get("R_fut_base_m", m.get("largeur_fondation_m", 6.0) / 2 * 0.3),
        }

    def run_foundation(self):
        if self.rapport_analyse is None:
            QMessageBox.warning(self, "Analyse requise", "Lancez d'abord l'analyse sismique.")
            return
        try:
            fi = self._read_foundation()
        except ValueError as e:
            QMessageBox.warning(self, "Saisie invalide", str(e))
            return
        concentrated = self.rapport_analyse.meta.get("type") == "chateau_eau"
        report, err = analyser_fondation(self._foundation_load(), fi, concentrated)
        if err or report is None:
            QMessageBox.critical(self, "Erreur fondation", err or "Erreur.")
            return
        self.foundation_input = fi
        self.rapport_fondation = report
        self.fondation_ok = report.ok
        self.armatures_ok = False
        self.tabs.setTabEnabled(2, self.fondation_ok)
        self.btn_arm.setEnabled(self.fondation_ok)
        self._show_report(report)
        if not self.fondation_ok:
            QMessageBox.warning(self, "Fondation non conforme",
                                "Vérifications de fondation non satisfaites. Revoir les dimensions.")

    def auto_foundation(self):
        if self.rapport_analyse is None:
            QMessageBox.warning(self, "Analyse requise", "Lancez d'abord l'analyse sismique.")
            return
        try:
            shape = self.fond_shape_combo.currentText()
            q_adm = lire_valeur(self.f_qadm, "q_adm")
            mu = lire_valeur(self.f_mu, "μ")
            overhang = lire_valeur(self.f_over, "débord")
        except ValueError as e:
            QMessageBox.warning(self, "Saisie invalide", str(e))
            return
        fi = auto_dimensionner(self._foundation_load(), shape, q_adm, mu, overhang,
                                tank=self.rapport_analyse.meta.get("geometry", {}),
                                concentrated=self.rapport_analyse.meta.get("type") == "chateau_eau")
        # reporte les valeurs proposées dans l'interface
        self.f_over.setText(f"{fi.overhang:.2f}")
        self.f_hf.setText(f"{fi.h_f:.2f}")
        self.f_qadm.setText(f"{fi.q_adm:.1f}")
        self.f_mu.setText(f"{fi.mu:.2f}")
        self.f_fck.setText(f"{fi.fck:.1f}")
        self.f_fy.setText(f"{fi.fy:.1f}")
        self.f_hdisk.setText(f"{fi.h_disk:.2f}")
        self.f_hcone.setText(f"{fi.h_cone:.2f}")
        if fi.shape == "Tronconique":
            self.f_Db.setText(f"{fi.D_base:.1f}")
        QMessageBox.information(self, "Auto-dimensionnement",
                                "Dimensions proposées chargées. Cliquez sur « Vérifier la fondation ».")
        self.run_foundation()

    # ------------------------------------------------------------- Armatures
    def run_armatures(self):
        if not self.fondation_ok or self.rapport_fondation is None or self.foundation_input is None:
            QMessageBox.warning(self, "Fondation requise", "La fondation doit être conforme.")
            return
        geom = self.rapport_analyse.meta.get("geometry", {})
        try:
            opts = {
                "w_max": lire_valeur(self.arm_wmax, "w_max"),
                "q_couv": lire_valeur(self.arm_qcouv, "q_couv"),
                "Q_lanterneau": lire_valeur(self.arm_qlan, "Q_lanterneau"),
                "e_couv": lire_valeur(self.arm_ecouv, "e_couv") if self.arm_ecouv.text().strip() else None,
            }
        except ValueError as e:
            QMessageBox.warning(self, "Saisie invalide", str(e))
            return
        report, err = calculer_armatures(
            self.rapport_analyse, self.rapport_fondation, self.foundation_input,
            self.regulation_combo.currentText(), geom, opts)
        if err or report is None:
            QMessageBox.critical(self, "Erreur armatures", err or "Erreur.")
            return
        self.rapport_armatures = report
        self.armatures_ok = report.ok
        self._show_report(report)

    # ------------------------------------------------------------- Affichage
    def _combined_report(self) -> Report:
        r = Report(self.rapport_analyse.title if self.rapport_analyse else "Rapport")
        if self.rapport_analyse:
            r.merge(self.rapport_analyse)
        if self.rapport_fondation:
            r.merge(self.rapport_fondation)
        if self.rapport_armatures:
            r.merge(self.rapport_armatures)
        return r

    def _show_report(self, report: Report):
        txt = ""
        for title, items in report.sections:
            txt += f"\n{title}\n"
            for it in items:
                suffix = f"  [{it.verdict}]" if it.verdict else ""
                note = f"  ({it.note})" if it.note else ""
                txt += f"  {it.label:<34}: {it.formatted()} {it.unit}{suffix}{note}\n"
        self.results_display.setText(txt)

    def _enable_exports(self):
        for b in (self.pdf_button, self.csv_button, self.docx_button):
            b.setEnabled(True)

    def _disable_exports(self):
        for b in (self.pdf_button, self.csv_button, self.docx_button):
            b.setEnabled(False)

    # ------------------------------------------------------------- Export
    def _current_sketch(self):
        if not self.rapport_analyse:
            return None
        m = self.rapport_analyse.meta
        kind = ("reservoir_circulaire" if (m.get("type") == "reservoir" and m.get("sous_type") == "Circulaire")
                else "reservoir_rectangulaire" if m.get("type") == "reservoir" else "chateau_eau")
        geom = m.get("geometry", {})
        fond = {}
        if self.foundation_input:
            fi = self.foundation_input
            fond = {"shape": fi.shape, "D": fi.D, "D_base": fi.D_base, "D_sommet": fi.D_sommet,
                    "L": fi.L, "B": fi.B, "h_f": fi.h_f}
        try:
            fd, path = tempfile.mkstemp(suffix=".png", prefix="croquis_")
            os.close(fd)
            return draw_sketch(kind, geom, fond, path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Sketch impossible : %s", e)
            return None

    def generer_pdf(self):
        if not self.rapport_analyse:
            QMessageBox.warning(self, "Erreur", "Aucun rapport disponible.")
            return
        nom, _ = QFileDialog.getSaveFileName(self, "Sauvegarder PDF", "", "PDF (*.pdf)")
        if nom:
            try:
                generer_note_calcul_pdf(nom, self._combined_report(), self._current_sketch())
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Erreur PDF", str(e))

    def generer_docx(self):
        if not self.rapport_analyse:
            QMessageBox.warning(self, "Erreur", "Aucun rapport disponible.")
            return
        nom, _ = QFileDialog.getSaveFileName(self, "Sauvegarder DOCX", "", "DOCX (*.docx)")
        if nom:
            try:
                generer_note_calcul_docx(nom, self._combined_report(), self._current_sketch())
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Erreur DOCX", f"Installez python-docx : {e}")

    def exporter_csv(self):
        if not self.rapport_analyse:
            QMessageBox.warning(self, "Erreur", "Aucun rapport disponible.")
            return
        nom, _ = QFileDialog.getSaveFileName(self, "Exporter CSV", "", "CSV (*.csv)")
        if nom:
            try:
                with open(nom, "w", newline="", encoding="utf-8") as fcsv:
                    w = csv.writer(fcsv)
                    for title, items in self._combined_report().sections:
                        w.writerow([title])
                        for it in items:
                            w.writerow([it.label, it.formatted(), it.unit, it.verdict or "", it.note])
                        w.writerow([])
            except Exception as e:  # noqa: BLE001
                QMessageBox.critical(self, "Erreur CSV", str(e))
