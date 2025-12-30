# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import QCoreApplication, Qt, QSize
from qgis.PyQt.QtGui import QIcon, QPixmap, QPalette
from qgis.PyQt.QtWidgets import (
    QAction,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QHBoxLayout,
    QLabel,
    QProgressDialog,
    QApplication,
    QWidget,
    QGroupBox,
    QRadioButton,
    QButtonGroup,
    QSplitter,
    QLineEdit,
)

from qgis.core import QgsProject, QgsRasterLayer

# Vector tiles (kan mangle i veldig gamle QGIS)
try:
    from qgis.core import QgsVectorTileLayer  # type: ignore
except Exception:
    QgsVectorTileLayer = None  # type: ignore

import os
from typing import Optional, List, Dict, Tuple


# -------------------------------------------------------------------------
# Qt5/Qt6 enum helper + felles konstanter
# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
# Qt5/Qt6 safe enum/attr helper
# -------------------------------------------------------------------------
def _qt_try(path: str):
    """Returner Qt-objektet for en 'scoped enum' path, eller None."""
    obj = Qt
    for part in path.split("."):
        if not hasattr(obj, part):
            return None
        obj = getattr(obj, part)
    return obj

def palette_role(name: str):
    # Qt5: QPalette.Window
    v = getattr(QPalette, name, None)
    if v is not None:
        return v
    # Qt6: QPalette.ColorRole.Window
    cr = getattr(QPalette, "ColorRole", None)
    if cr is not None and hasattr(cr, name):
        return getattr(cr, name)
    # PyQt6 kan ha lowercase alias
    low = name[:1].lower() + name[1:]
    if hasattr(QPalette, low):
        return getattr(QPalette, low)
    raise AttributeError(f"Fant ikke QPalette role: {name}")

def dialog_accepted_code():
    v = getattr(QDialog, "Accepted", None)  # Qt5
    if v is not None:
        return v
    return QDialog.DialogCode.Accepted      # Qt6

def qt_pick(*paths: str, default=None):
    """
    Prøv flere Qt-paths i rekkefølge.
    Eksempel: qt_pick("Orientation.Horizontal", "Horizontal", default=1)
    """
    for p in paths:
        v = _qt_try(p)
        if v is not None:
            return v
    return default


# ---- Vanlige enums/flags vi bruker i pluginen ----
QT_HORIZONTAL = qt_pick("Orientation.Horizontal", "Horizontal", default=1)
QT_VERTICAL   = qt_pick("Orientation.Vertical",   "Vertical",   default=2)

# AlignCenter = AlignHCenter (0x0004) | AlignVCenter (0x0080) = 0x0084
QT_ALIGN_CENTER = qt_pick("AlignmentFlag.AlignCenter", "AlignCenter", default=0x0084)

# TextBrowserInteraction finnes som scoped i Qt6
QT_TEXT_BROWSER = qt_pick(
    "TextInteractionFlag.TextBrowserInteraction",
    "TextBrowserInteraction",
    default=0
)

# AspectRatio / Transformation
# AspectRatioMode.KeepAspectRatioByExpanding = 2
QT_KEEP_ASPECT_EXPAND = qt_pick(
    "AspectRatioMode.KeepAspectRatioByExpanding",
    "KeepAspectRatioByExpanding",
    default=2
)

# TransformationMode.SmoothTransformation = 1
QT_SMOOTH_TRANSFORM = qt_pick(
    "TransformationMode.SmoothTransformation",
    "SmoothTransformation",
    default=1
)

# TextFormat.RichText = 1
QT_RICHTEXT = qt_pick("TextFormat.RichText", "RichText", default=1)

# ItemDataRole.UserRole = 0x0100
QT_USER_ROLE = qt_pick("ItemDataRole.UserRole", "UserRole", default=0x0100)

# -------------------------------------------------------------------------
# Dialog
# -------------------------------------------------------------------------
class ServicePickerDialog(QDialog):
    """
    Dialog:
      - Venstre: søk + liste over tjenester (thumb-ikon)
      - Høyre: stor preview + navn + beskrivelse
      - Radioknapper for tjenestetype (WMTS/WMS/Vector tiles)
      - Radioknapper for variants (tileset / CRS)
    Returnerer (service_dict, type_key, variant_dict) eller (None, None, None)
    """

    PREVIEW_W = 550
    PREVIEW_H = 220

    TYPE_ORDER = ["wmts", "wms", "vectortile"]  # stabil rekkefølge

    def __init__(self, parent, services: List[Dict], plugin_dir: str, icon_size: int = 50):
        super().__init__(parent)
        self.setWindowTitle("Bakgrunnskart")
        self.setMinimumWidth(900)
        self.setMinimumHeight(580)

        self.services = services
        self.plugin_dir = plugin_dir
        self.icon_size = icon_size

        self._selected_service: Optional[Dict] = None
        self._selected_type_key: Optional[str] = None
        self._selected_variant: Optional[Dict] = None

        root = QVBoxLayout(self)

        header = QLabel("Velg et bakgrunnskart:")
        header.setWordWrap(True)
        root.addWidget(header)

        splitter = QSplitter()
        splitter.setOrientation(QT_HORIZONTAL)
        root.addWidget(splitter, 1)

        # ---------------- LEFT ----------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Søk…")
        left_layout.addWidget(self.search)

        self.lw = QListWidget()
        self.lw.setIconSize(QSize(self.icon_size, self.icon_size))
        left_layout.addWidget(self.lw, 1)
        splitter.addWidget(left)

        # ---------------- RIGHT ----------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(right)

        # Stor preview
        self.preview_big = QLabel()
        self.preview_big.setAlignment(QT_ALIGN_CENTER)
        self.preview_big.setMinimumHeight(self.PREVIEW_H)
        self.preview_big.setStyleSheet("QLabel { border: 1px solid rgba(255,255,255,0.15); }")
        right_layout.addWidget(self.preview_big)

        # Tittel
        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(QT_RICHTEXT)
        right_layout.addWidget(self.title_label)

        # Beskrivelse
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setTextFormat(QT_RICHTEXT)
        self.desc.setTextInteractionFlags(QT_TEXT_BROWSER)
        self.desc.setOpenExternalLinks(True)
        right_layout.addWidget(self.desc)

        self._apply_desc_colors()

        # --- Tjenestetype ---
        self.types_box = QGroupBox("Velg tjenestetype")
        self.types_layout = QHBoxLayout(self.types_box)
        right_layout.addWidget(self.types_box)

        self.type_group = QButtonGroup(self)
        self.type_group.setExclusive(True)
        self.type_group.buttonClicked.connect(self._on_type_clicked)

        # --- Variantvalg ---
        self.variants_box = QGroupBox("Velg tileset / projeksjon")
        self.variants_layout = QVBoxLayout(self.variants_box)
        right_layout.addWidget(self.variants_box)

        self.variant_group = QButtonGroup(self)
        self.variant_group.setExclusive(True)
        self.variant_group.buttonClicked.connect(self._on_variant_clicked)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_ok = QPushButton("Legg til")
        self.btn_cancel = QPushButton("Avbryt")
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_cancel)
        root.addLayout(btn_row)

        self.btn_ok.clicked.connect(self._accept)
        self.btn_cancel.clicked.connect(self.reject)

        # Fill list
        self._populate_services()
        self.lw.currentItemChanged.connect(self._on_service_changed)

        # Søk/filter
        self.search.textChanged.connect(self._apply_filter)

        if self.lw.count() > 0:
            self.lw.setCurrentRow(0)
            self._on_service_changed(self.lw.currentItem(), None)

    # -------------------------
    # Theme-aware colors
    # -------------------------
    def _apply_desc_colors(self):
        pal = self.palette()
        bg = pal.color(palette_role("Window"))
        is_dark = bg.lightness() < 128

        text_color = "#ffffff" if is_dark else "#222222"
        link_color = "#4ea3ff" if is_dark else "#0b57d0"

        self.title_label.setStyleSheet(f"QLabel {{ color: {text_color}; font-size: 13px; }}")
        self.desc.setStyleSheet(
            f"QLabel {{ color: {text_color}; }}"
            f"QLabel a {{ color: {link_color}; text-decoration: underline; }}"
        )

    # -------------------------
    # Offerings (bakoverkompat)
    # -------------------------
    def _normalize_offerings(self, svc: Dict) -> Dict:
        """
        Returnerer alltid et dict:
          { "wmts": {"label":"...", "variants":[...]}, "wms": {...}, "vectortile": {...} }

        Hvis svc har 'offerings', brukes den.
        Hvis svc bare har 'variants', grupperes de etter type (wmts/wms/xyz/...)
        """
        offerings = svc.get("offerings")
        if isinstance(offerings, dict) and offerings:
            return offerings

        variants = svc.get("variants") or []
        out: Dict[str, Dict] = {}

        # grupper litt smart: xyz regnes under "wmts" (praktisk for brukeren)
        wmts_like: List[Dict] = []
        wms_like: List[Dict] = []
        vt_like: List[Dict] = []

        for v in variants:
            if not isinstance(v, dict):
                continue
            t = (v.get("type") or "").lower()
            if t in ("wmts", "xyz"):
                wmts_like.append(v)
            elif t == "wms":
                wms_like.append(v)
            elif t in ("vectortile", "vt", "mvt", "arcgis_vt", "arcgisvectortile"):
                vt_like.append(v)
            else:
                # ukjent -> legg i wmts-blokka (så det i det minste dukker opp)
                wmts_like.append(v)

        if wmts_like:
            out["wmts"] = {"label": "WMTS / XYZ", "variants": wmts_like}
        if wms_like:
            out["wms"] = {"label": "WMS", "variants": wms_like}
        if vt_like:
            out["vectortile"] = {"label": "Vector tiles", "variants": vt_like}

        # Hvis fortsatt tomt
        if not out:
            out["wmts"] = {"label": "WMTS / XYZ", "variants": [{"label": "Standard", "key": "default"}]}

        return out

    # -------------------------
    # HiDPI + crop helper
    # -------------------------
    def _scaled_crop_top_pixmap(self, pm: QPixmap, target_w: int, target_h: int) -> QPixmap:
        if pm.isNull():
            return pm

        dpr = self.devicePixelRatioF() or 1.0
        tw = max(1, int(target_w * dpr))
        th = max(1, int(target_h * dpr))

        scaled = pm.scaled(tw, th, QT_KEEP_ASPECT_EXPAND, QT_SMOOTH_TRANSFORM)

        x = int((scaled.width() - tw) / 2) if scaled.width() > tw else 0
        y = 0
        cropped = scaled.copy(x, y, tw, th)
        cropped.setDevicePixelRatio(dpr)
        return cropped

    # -------------------------
    # Populate + search filter
    # -------------------------
    def _populate_services(self):
        self.lw.clear()

        for svc in self.services:
            name = svc.get("name", "(uten navn)")
            item = QListWidgetItem(name)

            offerings = self._normalize_offerings(svc)

            # søkeblob: navn + desc + typelabels + variantlabels
            type_labels = []
            variant_labels = []
            for tkey, off in offerings.items():
                if isinstance(off, dict):
                    type_labels.append((off.get("label") or tkey))
                    for v in (off.get("variants") or []):
                        if isinstance(v, dict):
                            variant_labels.append(v.get("label") or "")

            search_blob = " ".join(
                [
                    (svc.get("name") or ""),
                    (svc.get("description") or ""),
                    " ".join(type_labels),
                    " ".join(variant_labels),
                ]
            ).lower()

            item.setData(QT_USER_ROLE, svc)
            item.setData(QT_USER_ROLE + 1, search_blob)

            # thumb ikon (liste)
            thumb_rel = svc.get("thumb") or svc.get("preview")  # fallback
            if thumb_rel:
                p = os.path.join(self.plugin_dir, thumb_rel)
                if os.path.exists(p):
                    pm = QPixmap(p)
                    if not pm.isNull():
                        dpr = self.devicePixelRatioF() or 1.0
                        s = max(1, int(self.icon_size * dpr))
                        icon_pm = pm.scaled(s, s, QT_KEEP_ASPECT_EXPAND, QT_SMOOTH_TRANSFORM)
                        icon_pm.setDevicePixelRatio(dpr)
                        item.setIcon(QIcon(icon_pm))

            self.lw.addItem(item)

    def _apply_filter(self, text: str):
        q = (text or "").strip().lower()

        any_visible = False
        for i in range(self.lw.count()):
            it = self.lw.item(i)
            blob = (it.data(QT_USER_ROLE + 1) or "")
            show = (q in blob) if q else True
            it.setHidden(not show)
            if show:
                any_visible = True

        cur = self.lw.currentItem()
        if cur is None or cur.isHidden():
            if any_visible:
                for i in range(self.lw.count()):
                    it = self.lw.item(i)
                    if not it.isHidden():
                        self.lw.setCurrentItem(it)
                        break
            else:
                self.preview_big.clear()
                self.title_label.setText("")
                self.desc.setText("")
                self._clear_types()
                self._clear_variants()

    # -------------------------
    # Types + Variants
    # -------------------------
    def _clear_types(self):
        for b in list(self.type_group.buttons()):
            self.type_group.removeButton(b)
            b.setParent(None)
            b.deleteLater()

        while self.types_layout.count():
            it = self.types_layout.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        self._selected_type_key = None

    def _clear_variants(self):
        for b in list(self.variant_group.buttons()):
            self.variant_group.removeButton(b)
            b.setParent(None)
            b.deleteLater()

        while self.variants_layout.count():
            it = self.variants_layout.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        self._selected_variant = None

    def _populate_types(self, svc: Dict):
        self._clear_types()
        offerings = self._normalize_offerings(svc)

        keys = [k for k in self.TYPE_ORDER if k in offerings] + sorted(
            [k for k in offerings.keys() if k not in self.TYPE_ORDER]
        )

        first_enabled = None
        for k in keys:
            off = offerings.get(k) or {}
            label = (off.get("label") if isinstance(off, dict) else None) or k.upper()

            rb = QRadioButton(label)
            rb.setProperty("type_key", k)

            disabled = bool(off.get("disabled")) if isinstance(off, dict) else False
            if disabled:
                rb.setEnabled(False)
                rb.setToolTip((off.get("disabled_reason") if isinstance(off, dict) else None) or "Ikke tilgjengelig")
            else:
                if first_enabled is None:
                    first_enabled = k

            self.type_group.addButton(rb)
            self.types_layout.addWidget(rb)

        self.types_layout.addStretch(1)

        # Velg første enabled
        if first_enabled:
            for b in self.type_group.buttons():
                if b.property("type_key") == first_enabled:
                    b.setChecked(True)
                    self._selected_type_key = first_enabled
                    break

    def _populate_variants_for_type(self, svc: Dict, type_key: Optional[str]):
        self._clear_variants()
        offerings = self._normalize_offerings(svc)
        off = (offerings.get(type_key) if type_key else None) or {}

        variants = off.get("variants") if isinstance(off, dict) else None
        if not variants:
            variants = [{"label": "Standard", "key": "default"}]

        first = True
        for i, v in enumerate(variants):
            if not isinstance(v, dict):
                continue
            label = v.get("label", f"Variant {i+1}")

            rb = QRadioButton(label)
            rb.setProperty("variant_dict", v)
            self.variant_group.addButton(rb)
            self.variants_layout.addWidget(rb)

            if first:
                rb.setChecked(True)
                self._selected_variant = v
                first = False

        self.variants_layout.addStretch(1)

    def _on_service_changed(self, current: QListWidgetItem, _prev: QListWidgetItem):
        if current is None or current.isHidden():
            return

        svc = current.data(QT_USER_ROLE)
        self._selected_service = svc

        # Preview (stor)
        preview_rel = svc.get("preview")
        if preview_rel:
            p = os.path.join(self.plugin_dir, preview_rel)
            if os.path.exists(p):
                pm = QPixmap(p)
                if not pm.isNull():
                    banner = self._scaled_crop_top_pixmap(pm, self.PREVIEW_W, self.PREVIEW_H)
                    self.preview_big.setPixmap(banner)
                else:
                    self.preview_big.clear()
            else:
                self.preview_big.clear()
        else:
            self.preview_big.clear()

        # Title + description
        name = svc.get("name", "")
        self.title_label.setText(f"<b>{name}</b>")
        self.desc.setText(svc.get("description", ""))

        # Types + variants
        self._populate_types(svc)
        self._populate_variants_for_type(svc, self._selected_type_key)

    def _on_type_clicked(self, btn: QRadioButton):
        k = btn.property("type_key")
        if isinstance(k, str):
            self._selected_type_key = k
            if self._selected_service:
                self._populate_variants_for_type(self._selected_service, k)

    def _on_variant_clicked(self, btn: QRadioButton):
        v = btn.property("variant_dict")
        if isinstance(v, dict):
            self._selected_variant = v

    def _accept(self):
        if not self._selected_service:
            QMessageBox.information(self, "Bakgrunnskart", "Velg en tjeneste først.")
            return
        if not self._selected_type_key:
            QMessageBox.information(self, "Bakgrunnskart", "Velg en tjenestetype først.")
            return
        if not self._selected_variant:
            QMessageBox.information(self, "Bakgrunnskart", "Velg et tileset / projeksjon først.")
            return
        self.accept()

    def get_selection(self) -> Tuple[Optional[Dict], Optional[str], Optional[Dict]]:
        if self.result() != dialog_accepted_code():
            return None, None, None
        return self._selected_service, self._selected_type_key, self._selected_variant


# -------------------------------------------------------------------------
# Plugin
# -------------------------------------------------------------------------
class BakgrunnskartPlugin:
    """
    QGIS plugin:
    - Velg tjeneste + tjenestetype + variant i samme dialog
    - Alle lag samles i én gruppe: "Bakgrunnskart"
    """

    MAIN_GROUP_NAME = "Bakgrunnskart"
    PREVIEW_ICON_SIZE = 50  # px

    # ---------------------------------------------------------------------
    # SERVICES (samme innhold som du startet på – kan utvides videre)
    # NB: I RichText i QLabel anbefales <br> for linjeskift.
    # ---------------------------------------------------------------------
    SERVICES = [
        {
        "name": "Fjellskygge",
        "description": "Denne tjenesten inneholder fjellskygger. Den er ment for å kombineres med andre tjenester. <a href=\"https://kartkatalog.geonorge.no/metadata/fjellskygge-wms/57bcf66a-1333-498f-a1f1-13f27a9cee1f\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/shadow.png",
        "thumb": "previews/shadow_thumb.png",
        "offerings": {
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.fjellskygge?service=wms&request=getcapabilities",
                "layers": "fjellskygge_wms",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.fjellskygge?service=wms&request=getcapabilities",
                "layers": "fjellskygge_wms",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.fjellskygge?service=wms&request=getcapabilities",
                "layers": "fjellskygge_wms",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.fjellskygge?service=wms&request=getcapabilities",
                "layers": "fjellskygge_wms",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.fjellskygge?service=wms&request=getcapabilities",
                "layers": "fjellskygge_wms",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            }
        }
        },
        {
        "name": "Flybilder (OBS! Fjernes 1. mars 2026)",
        "description": "Ortofoto (Norge i bilder). <a href=\"https://kartkatalog.geonorge.no/metadata/norge-i-bilder-wmts-mercator/1b690a65-4fed-4e5e-ad77-1218e2bf315f\">Se mer informasjon</a>. OBS! Tjenesten stenges fra 1. mars 2026. <a href=\"https://register.geonorge.no/varsler/norge-i-bilder-wmts-mercator/f0dd601a-54d9-40f1-bfeb-3a8f672ccd6c\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/aerial.png",
        "thumb": "previews/aerial_thumb.png",
        "offerings": {
            "wmts": {
            "label": "WMTS /XYZ",
            "variants": [
                {
                    "type": "xyz",
                    "label": "WebMercator (EPSG:3857)",
                    "xyz_url": (
                        "https://opencache.statkart.no/gatekeeper/gk/gk.open_nib_web_mercator_wmts_v2"
                        "?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
                        "&LAYER=Nibcache_web_mercator_v2"
                        "&STYLE=default"
                        "&FORMAT=image/jpgpng"
                        "&tileMatrixSet=default028mm"
                        "&tileMatrix={z}"
                        "&tileRow={y}"
                        "&tileCol={x}"
                    ),
                    "zmin": 0,
                    "zmax": 21,
                }
            ]
            }
        }
        },
        {
        "name": "Forenklet europakart",
        "description": "Forenklet bakgrunnskart for Nord-Europa. Egner seg godt som bakgrunnskart under ett av de andre bakgrunnskartene om du skal lage kart som strekker seg utover Norges landegrenser. <a href=\"https://kartkatalog.geonorge.no/metadata/europakart-forenklet-wms/4e904a49-e2dc-4099-b271-9463bdab7846\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/europe.png",
        "thumb": "previews/europe_thumb.png",
        "offerings": {
            "wmts": {
            "label": "WMTS",
            "variants": [
                {
                    "type": "wmts",
                    "label": "UTM 32N (EPSG:25832)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "europaForenklet",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm32n",
                    "crs": "EPSG:25832",
                },
                {
                    "type": "wmts",
                    "label": "UTM 33N (EPSG:25833)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "europaForenklet",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm33n",
                    "crs": "EPSG:25833",
                },
                {
                    "type": "wmts",
                    "label": "UTM 35N (EPSG:25835)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "europaForenklet",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm35n",
                    "crs": "EPSG:25835",
                },
                {
                    "type": "wmts",
                    "label": "WebMercator (EPSG:3857)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "europaForenklet",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "webmercator",
                    "crs": "EPSG:3857",
                }
            ]
            }
        }
        },
        {
        "name": "Norges grunnkart",
        "description": "Tjenesten inneholder topografiske kart i målestokken 1:500 til 1:10M. <a href=\"https://kartkatalog.geonorge.no/metadata/norges-grunnkart-wms/8ecaa2d5-8b0a-46cf-a2a7-2584f78b12e2\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/basemap.png",
        "thumb": "previews/basemap_thumb.png",
        "offerings": {
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            }
        }
        },
        {
        "name": "Norges grunnkart gråtone",
        "description": "Tjenesten inneholder topografiske kart i målestokken 1:500 til 1:10M i gråskala. <a href=\"https://kartkatalog.geonorge.no/metadata/norges-grunnkart-graatone-wms/d24a0bf9-1398-4bc4-a4ba-63896b0a599c\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/basemapgrey.png",
        "thumb": "previews/basemapgrey_thumb.png",
        "offerings": {
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart_graatone?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart_graatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart_graatone?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart_graatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart_graatone?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart_graatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart_graatone?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart_graatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.norges_grunnkart_graatone?service=wms&request=getcapabilities",
                "layers": "Norges_grunnkart_graatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            }
        }
        },
        {
        "name": "Sjøkart",
        "description": "Sjøkart i rasterformat med sjødata fra overseilingskart, hovedkart, kystkart, havnekart samt Svalbardkart. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/ocean.png",
        "thumb": "previews/ocean_thumb.png",
        "offerings": {
            "wmts": {
            "label": "WMTS",
            "variants": [
                {
                    "type": "wmts",
                    "label": "UTM 32N (EPSG:25832)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "sjokartraster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm32n",
                    "crs": "EPSG:25832",
                },
                {
                    "type": "wmts",
                    "label": "UTM 33N (EPSG:25833)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "sjokartraster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm33n",
                    "crs": "EPSG:25833",
                },
                {
                    "type": "wmts",
                    "label": "UTM 35N (EPSG:25835)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "sjokartraster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm35n",
                    "crs": "EPSG:25835",
                },
                {
                    "type": "wmts",
                    "label": "WebMercator (EPSG:3857)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "sjokartraster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "webmercator",
                    "crs": "EPSG:3857",
                }
            ]
            },
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.sjokartraster2?service=wms&request=getcapabilities",
                "layers": "all",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.sjokartraster2?service=wms&request=getcapabilities",
                "layers": "all",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.sjokartraster2?service=wms&request=getcapabilities",
                "layers": "all",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.sjokartraster2?service=wms&request=getcapabilities",
                "layers": "all",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.sjokartraster2?service=wms&request=getcapabilities",
                "layers": "all",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            }
        }
        },
        {
        "name": "Topografisk gråtonekart",
        "description": "En gråtone-basert kartografi med kartdata fra N50 til N2000, FKB, matrikkel, høyde- og dybdedata. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/topogrey.png",
        "thumb": "previews/topogrey_thumb.png",
        "offerings": {
            "wmts": {
            "label": "WMTS",
            "variants": [
                {
                    "type": "wmts",
                    "label": "UTM 32N (EPSG:25832)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "topograatone",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm32n",
                    "crs": "EPSG:25832",
                },
                {
                    "type": "wmts",
                    "label": "UTM 33N (EPSG:25833)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "topograatone",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm33n",
                    "crs": "EPSG:25833",
                },
                {
                    "type": "wmts",
                    "label": "UTM 35N (EPSG:25835)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "topograatone",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm35n",
                    "crs": "EPSG:25835",
                },
                {
                    "type": "wmts",
                    "label": "WebMercator (EPSG:3857)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "topograatone",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "webmercator",
                    "crs": "EPSG:3857",
                }
            ]
            },
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.topograatone?service=wms&request=getcapabilities",
                "layers": "topograatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.topograatone?service=wms&request=getcapabilities",
                "layers": "topograatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.topograatone?service=wms&request=getcapabilities",
                "layers": "topograatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.topograatone?service=wms&request=getcapabilities",
                "layers": "topograatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.topograatone?service=wms&request=getcapabilities",
                "layers": "topograatone",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            },
            "vectortile": {
            "label": "Vector tiles (kommer)",
            "disabled": True,
            "disabled_reason": "Kommer senere",
            "variants": []
            }
        }
        },
        {
        "name": "Topografisk norgeskart",
        "description": "En kartografi i farger med kartdata fra N50 til N2000, FKB, matrikkel, høyde- og dybdedata. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/topo.png",
        "thumb": "previews/topo_thumb.png",
        "offerings": {
            "wmts": {
            "label": "WMTS",
            "variants": [
                {
                "type": "wmts",
                "label": "UTM 32N (EPSG:25832)",
                "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                "layer": "topo",
                "style": "default",
                "format": "image/png",
                "tileMatrixSet": "utm32n",
                "crs": "EPSG:25832",
                },
                {
                "type": "wmts",
                "label": "UTM 33N (EPSG:25833)",
                "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                "layer": "topo",
                "style": "default",
                "format": "image/png",
                "tileMatrixSet": "utm33n",
                "crs": "EPSG:25833",
                },
                {
                "type": "wmts",
                "label": "UTM 35N (EPSG:25835)",
                "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                "layer": "topo",
                "style": "default",
                "format": "image/png",
                "tileMatrixSet": "utm35n",
                "crs": "EPSG:25835",
                },
                {
                "type": "wmts",
                "label": "WebMercator (EPSG:3857)",
                "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                "layer": "topo",
                "style": "default",
                "format": "image/png",
                "tileMatrixSet": "webmercator",
                "crs": "EPSG:3857",
                }
            ]
            },
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.topo?service=wms&request=getcapabilities",
                "layers": "topo",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.topo?service=wms&request=getcapabilities",
                "layers": "topo",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.topo?service=wms&request=getcapabilities",
                "layers": "topo",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.topo?service=wms&request=getcapabilities",
                "layers": "topo",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.topo?service=wms&request=getcapabilities",
                "layers": "topo",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            },
            "vectortile": {
            "label": "Vector tiles (under utvikling)",
            "disabled": True,
            "disabled_reason": "Kommer senere",
            "variants": []
            }
        }
        },
        {
            "name": "Topografisk rasterkart",
            "description": "Rasterkart eller \"papirkart\" med lik presentasjon (symbolikk) som kartserien Norge 1:50 000. Innhold fra N50 til N2000 og N5. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
            "preview": "previews/toporaster.png",
            "thumb": "previews/toporaster_thumb.png",
            "offerings": {
            "wmts": {
            "label": "WMTS",
            "variants": [
                {
                    "type": "wmts",
                    "label": "UTM 32N (EPSG:25832)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "toporaster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm32n",
                    "crs": "EPSG:25832",
                },
                {
                    "type": "wmts",
                    "label": "UTM 33N (EPSG:25833)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "toporaster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm33n",
                    "crs": "EPSG:25833",
                },
                {
                    "type": "wmts",
                    "label": "UTM 35N (EPSG:25835)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "toporaster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "utm35n",
                    "crs": "EPSG:25835",
                },
                {
                    "type": "wmts",
                    "label": "WebMercator (EPSG:3857)",
                    "capabilities": "https://cache.kartverket.no/v1/service?service=WMTS&request=GetCapabilities",
                    "layer": "toporaster",
                    "style": "default",
                    "format": "image/png",
                    "tileMatrixSet": "webmercator",
                    "crs": "EPSG:3857",
                }
            ]
            },
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.toporaster4?service=wms&request=getcapabilities",
                "layers": "topografiskraster",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.toporaster4?service=wms&request=getcapabilities",
                "layers": "topografiskraster",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.toporaster4?service=wms&request=getcapabilities",
                "layers": "topografiskraster",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.toporaster4?service=wms&request=getcapabilities",
                "layers": "topografiskraster",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.toporaster4?service=wms&request=getcapabilities",
                "layers": "topografiskraster",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            }
        }
        },
        {
        "name": "Økonomisk kartverk",
        "description": "Informasjon tilsvarende digitalt økonomisk kartverk (ØK). N5 er basert på utvalgte, generaliserte FKB-data. <a href=\"https://kartkatalog.geonorge.no/metadata/n5raster2-wms/79ea9761-1ac9-4780-a065-e4738835643e\">Se mer informasjon</a><br><br>&copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/economic.png",
        "thumb": "previews/economic_thumb.png",
        "offerings": {
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.n5raster2?service=wms&request=getcapabilities",
                "layers": "n5Raster_WMS",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.n5raster2?service=wms&request=getcapabilities",
                "layers": "n5Raster_WMS",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.n5raster2?service=wms&request=getcapabilities",
                "layers": "n5Raster_WMS",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.n5raster2?service=wms&request=getcapabilities",
                "layers": "n5Raster_WMS",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.n5raster2?service=wms&request=getcapabilities",
                "layers": "n5Raster_WMS",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:4326",
                }
            ]
            }
        }
        }
    ]

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.toolbar = None

    def tr(self, text):
        return QCoreApplication.translate("BakgrunnskartPlugin", text)

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon_bakgrunnskart.svg")
        self.action = QAction(QIcon(icon_path), self.tr("Bakgrunnskart"), self.iface.mainWindow())
        self.action.triggered.connect(self.run)

        self.iface.addPluginToMenu(self.tr("&Kartverket"), self.action)
        self.toolbar = self.iface.addToolBar("Kartverket")
        self.toolbar.addAction(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu(self.tr("&Kartverket"), self.action)
            try:
                if self.toolbar:
                    self.toolbar.removeAction(self.action)
            except Exception:
                pass
            self.action = None

    # -------------------------
    # Group helper
    # -------------------------
    def get_or_create_main_group(self):
        root = QgsProject.instance().layerTreeRoot()
        grp = root.findGroup(self.MAIN_GROUP_NAME)
        if grp is None:
            grp = root.addGroup(self.MAIN_GROUP_NAME)
        return grp

    # -------------------------
    # URL encode for QGIS URI (url=... parameter)
    # -------------------------
    def encode_url_for_qgis_uri(self, url: str) -> str:
        # Match QGIS "Kilde": encode '=' og '&' (og '%' først)
        return (
            url.replace("%", "%25")
            .replace("=", "%3D")
            .replace("&", "%26")
        )

    # -------------------------
    # Add XYZ layer
    # -------------------------
    def add_xyz_layer(self, variant: Dict) -> QgsRasterLayer:
        url_tmpl = variant["xyz_url"]

        url_enc = (
            url_tmpl
            .replace("%", "%25")
            .replace("&", "%26")
            .replace("{", "%7B")
            .replace("}", "%7D")
        )

        zmin = int(variant.get("zmin", 0))
        zmax = int(variant.get("zmax", 21))

        uri = f"type=xyz&url={url_enc}&zmin={zmin}&zmax={zmax}&crs=EPSG3857"
        title = variant.get("title") or variant.get("label") or "XYZ"

        rl = QgsRasterLayer(uri, title, "wms")
        if not rl.isValid():
            raise RuntimeError(f"Klarte ikke å opprette XYZ-lag.\n\nURI:\n{uri}")

        QgsProject.instance().addMapLayer(rl, False)
        return rl

    # -------------------------
    # Add WMTS layer (via GetCapabilities)
    # -------------------------
    def add_wmts_layer(self, variant: Dict) -> QgsRasterLayer:
        cap = variant["capabilities"]
        cap_enc = self.encode_url_for_qgis_uri(cap)

        crs = variant.get("crs", "EPSG:25833")
        fmt = variant.get("format", "image/png")
        layer = variant["layer"]
        style = variant.get("style", "default")
        tms = variant["tileMatrixSet"]

        uri = (
            f"crs={crs}"
            f"&format={fmt}"
            f"&layers={layer}"
            f"&styles={style}"
            f"&tileMatrixSet={tms}"
            f"&url={cap_enc}"
        )

        title = variant.get("title") or variant.get("label") or "WMTS"
        rl = QgsRasterLayer(uri, title, "wms")
        if not rl.isValid():
            raise RuntimeError(
                "Klarte ikke å opprette WMTS-lag.\n\n"
                f"Capabilities:\n{cap}\n\nURI:\n{uri}"
            )

        QgsProject.instance().addMapLayer(rl, False)
        return rl

    # -------------------------
    # Add WMS layer
    # -------------------------
    def add_wms_layer(self, variant: Dict) -> QgsRasterLayer:
        url = variant["url"]
        url_enc = self.encode_url_for_qgis_uri(url)

        crs = variant.get("crs", "EPSG:25833")
        fmt = variant.get("format", "image/png")
        layers = variant.get("layers") or variant.get("layer")
        styles = variant.get("styles", "")

        if not layers:
            raise RuntimeError("WMS-variant mangler 'layers' (eller 'layer').")

        uri = (
            f"crs={crs}"
            f"&format={fmt}"
            f"&layers={layers}"
            f"&styles={styles}"
            f"&url={url_enc}"
        )

        title = variant.get("title") or variant.get("label") or "WMS"
        rl = QgsRasterLayer(uri, title, "wms")
        if not rl.isValid():
            raise RuntimeError(
                "Klarte ikke å opprette WMS-lag.\n\n"
                f"URL:\n{url}\n\nURI:\n{uri}"
            )

        QgsProject.instance().addMapLayer(rl, False)
        return rl

    # -------------------------
    # Add Vector Tile layer (ArcGIS VectorTileServer / MVT)
    # -------------------------
    def add_vectortile_layer(self, variant: Dict):
        if QgsVectorTileLayer is None:
            raise RuntimeError("Denne QGIS-versjonen har ikke QgsVectorTileLayer tilgjengelig.")

        title = variant.get("title") or variant.get("label") or "Vector tiles"

        # Du kan enten oppgi ferdig 'uri' i variant,
        # eller bruke style_url + url/service_url for å bygge.
        uri = variant.get("uri")
        if not uri:
            service_url = variant.get("url") or variant.get("service_url")
            style_url = variant.get("style_url") or variant.get("styleUrl")
            zmin = int(variant.get("zmin", 0))
            zmax = int(variant.get("zmax", 14))
            if not service_url or not style_url:
                raise RuntimeError(
                    "Vector tile-variant mangler 'uri' eller (service_url/url + style_url/styleUrl)."
                )

            # ArcGIS VectorTileServer (slik QGIS normalt lagrer det)
            uri = (
                f"serviceType=arcgis"
                f"&styleUrl={style_url}"
                f"&type=xyz"
                f"&url={service_url}"
                f"&zmin={zmin}"
                f"&zmax={zmax}"
            )

        provider = variant.get("provider", "arcgisvectortileservice")
        lyr = QgsVectorTileLayer(uri, title, provider)
        if not lyr.isValid():
            raise RuntimeError(f"Klarte ikke å opprette Vector tile-lag.\n\nURI:\n{uri}")

        QgsProject.instance().addMapLayer(lyr, False)
        return lyr

    # -------------------------
    # Main
    # -------------------------
    def run(self):
        plugin_dir = os.path.dirname(__file__)

        dlg = ServicePickerDialog(
            self.iface.mainWindow(),
            self.SERVICES,
            plugin_dir,
            icon_size=self.PREVIEW_ICON_SIZE,
        )
        if dlg.exec() != dialog_accepted_code():
            return


        service, type_key, variant = dlg.get_selection()
        if not service or not type_key or not variant:
            return

        main_group = self.get_or_create_main_group()

        progress = QProgressDialog("Legger til lag…", "Avbryt", 0, 0, self.iface.mainWindow())
        progress.setWindowTitle("Bakgrunnskart")
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        try:
            vtype = (variant.get("type") or "").lower()

            layer_title = f"{service.get('name', 'Bakgrunnskart')} [{type_key.upper()}] ({variant.get('label', 'variant')})"
            variant = dict(variant)  # kopi
            variant["title"] = layer_title

            if vtype == "wmts":
                rl = self.add_wmts_layer(variant)
                main_group.addLayer(rl)

            elif vtype == "xyz":
                rl = self.add_xyz_layer(variant)
                main_group.addLayer(rl)

            elif vtype == "wms":
                rl = self.add_wms_layer(variant)
                main_group.addLayer(rl)

            elif vtype in ("vectortile", "vt", "mvt", "arcgis_vt"):
                lyr = self.add_vectortile_layer(variant)
                main_group.addLayer(lyr)

            else:
                raise RuntimeError(
                    "Ukjent variant-type.\n\n"
                    "Bruk 'wmts', 'wms', 'xyz' (og evt. 'vectortile' hvis du aktiverer det)."
                )

        except Exception as e:
            QMessageBox.critical(self.iface.mainWindow(), "Bakgrunnskart", str(e))
        finally:
            try:
                progress.close()
            except Exception:
                pass