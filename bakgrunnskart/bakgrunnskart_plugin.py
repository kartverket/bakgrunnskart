from qgis.PyQt.QtCore import QCoreApplication, Qt, QSize, QUrl
from qgis.PyQt.QtGui import QIcon, QPixmap, QPalette, QDesktopServices
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

import os
from typing import Optional, List, Dict, Tuple

class ServicePickerDialog(QDialog):
    """
    Dialog:
      - Venstre: søk + liste over tjenester (lite preview-ikon)
      - Høyre: stor preview (skarpt) + navn (bold) + beskrivelse + radioknapper for variants
    Returnerer (service_dict, variant_dict) eller (None, None)
    """

    PREVIEW_W = 520
    PREVIEW_H = 240

    def __init__(self, parent, services: List[Dict], plugin_dir: str, icon_size: int = 50):
        super().__init__(parent)
        self.setWindowTitle("Bakgrunnskart")
        self.setMinimumWidth(860)
        self.setMinimumHeight(520)

        self.services = services
        self.plugin_dir = plugin_dir
        self.icon_size = icon_size

        self._selected_service: Optional[Dict] = None
        self._selected_variant: Optional[Dict] = None

        root = QVBoxLayout(self)

        header = QLabel("Velg et bakgrunnskart:")
        header.setWordWrap(True)
        root.addWidget(header)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # ---------------- LEFT ----------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Søkefelt
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
        self.preview_big.setAlignment(Qt.AlignCenter)
        self.preview_big.setMinimumHeight(self.PREVIEW_H)
        self.preview_big.setStyleSheet("QLabel { border: 1px solid rgba(255,255,255,0.15); }")
        right_layout.addWidget(self.preview_big)

        # Tittel (bold)
        self.title_label = QLabel("")
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.RichText)  # for <b>...</b>
        right_layout.addWidget(self.title_label)

        # Beskrivelse (HTML + lenker)
        self.desc = QLabel("")
        self.desc.setWordWrap(True)
        self.desc.setTextFormat(Qt.RichText)
        self.desc.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.desc.setOpenExternalLinks(True)
        right_layout.addWidget(self.desc)

        # Auto: lys/mørk modus (tekst + lenkefarge)
        self._apply_desc_colors()

        self.variants_box = QGroupBox("Velg tileset")
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
        bg = pal.color(QPalette.Window)
        is_dark = bg.lightness() < 128

        text_color = "#ffffff" if is_dark else "#222222"
        link_color = "#4ea3ff" if is_dark else "#0b57d0"

        # Gjelder både title + description (og lenker)
        self.title_label.setStyleSheet(f"QLabel {{ color: {text_color}; font-size: 13px; }}")
        self.desc.setStyleSheet(
            f"QLabel {{ color: {text_color}; }}"
            f"QLabel a {{ color: {link_color}; text-decoration: underline; }}"
        )

    # -------------------------
    # HiDPI + crop helper
    # -------------------------
    def _scaled_crop_top_pixmap(self, pm: QPixmap, target_w: int, target_h: int) -> QPixmap:
        """
        Lager en skarp "banner" preview:
        - skalerer til å dekke (cover)
        - cropper fra TOPP (ikke senter), så viktig info i toppen bevares
        - HiDPI: skalerer i fysiske pixler og setter devicePixelRatio
        """
        if pm.isNull():
            return pm

        dpr = self.devicePixelRatioF() or 1.0
        tw = max(1, int(target_w * dpr))
        th = max(1, int(target_h * dpr))

        # Cover-scale til å dekke hele banneret
        scaled = pm.scaled(
            tw,
            th,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )

        # Crop fra toppen
        if scaled.width() > tw:
            x = int((scaled.width() - tw) / 2)
        else:
            x = 0
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

            # Lag en søkestreng som inkluderer navn + beskrivelse + variant-labels
            search_blob = " ".join(
                [
                    (svc.get("name") or ""),
                    (svc.get("description") or ""),
                    " ".join([(v.get("label") or "") for v in (svc.get("variants") or [])]),
                ]
            ).lower()
            item.setData(Qt.UserRole, svc)
            item.setData(Qt.UserRole + 1, search_blob)

            # Lite ikon (hiDPI)
            preview_rel = svc.get("preview")
            if preview_rel:
                p = os.path.join(self.plugin_dir, preview_rel)
                if os.path.exists(p):
                    pm = QPixmap(p)
                    if not pm.isNull():
                        # HiDPI skarp icon
                        dpr = self.devicePixelRatioF() or 1.0
                        s = max(1, int(self.icon_size * dpr))
                        icon_pm = pm.scaled(s, s, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                        icon_pm.setDevicePixelRatio(dpr)
                        item.setIcon(QIcon(icon_pm))

            self.lw.addItem(item)

    def _apply_filter(self, text: str):
        q = (text or "").strip().lower()

        # Vis/skjul items
        any_visible = False
        for i in range(self.lw.count()):
            it = self.lw.item(i)
            blob = (it.data(Qt.UserRole + 1) or "")
            show = (q in blob) if q else True
            it.setHidden(not show)
            if show:
                any_visible = True

        # Hvis valgt item ble skjult – velg første synlige
        cur = self.lw.currentItem()
        if cur is None or cur.isHidden():
            if any_visible:
                for i in range(self.lw.count()):
                    it = self.lw.item(i)
                    if not it.isHidden():
                        self.lw.setCurrentItem(it)
                        break
            else:
                # Ingen treff: clear høyre side
                self.preview_big.clear()
                self.title_label.setText("")
                self.desc.setText("")
                self._clear_variants()

    # -------------------------
    # Variants
    # -------------------------
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

    def _on_service_changed(self, current: QListWidgetItem, _prev: QListWidgetItem):
        if current is None or current.isHidden():
            return

        svc = current.data(Qt.UserRole)
        self._selected_service = svc

        # Stor preview (skarpt + crop topp)
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

        # Tittel + beskrivelse
        name = svc.get("name", "")
        self.title_label.setText(f"<b>{name}</b>")
        self.desc.setText(svc.get("description", ""))

        # Variants
        self._clear_variants()
        variants = svc.get("variants") or []
        if not variants:
            variants = [{"label": "Standard", "key": "default"}]

        for i, v in enumerate(variants):
            label = v.get("label", f"Variant {i+1}")
            rb = QRadioButton(label)
            rb.setProperty("variant_dict", v)
            self.variant_group.addButton(rb)
            self.variants_layout.addWidget(rb)

            if i == 0:
                rb.setChecked(True)
                self._selected_variant = v

        self.variants_layout.addStretch(1)

    def _on_variant_clicked(self, btn: QRadioButton):
        v = btn.property("variant_dict")
        if isinstance(v, dict):
            self._selected_variant = v

    def _accept(self):
        if not self._selected_service:
            QMessageBox.information(self, "Bakgrunnskart", "Velg en tjeneste først.")
            return
        if not self._selected_variant:
            QMessageBox.information(self, "Bakgrunnskart", "Velg et tileset først.")
            return
        self.accept()

    def get_selection(self) -> Tuple[Optional[Dict], Optional[Dict]]:
        if self.result() != QDialog.Accepted:
            return None, None
        return self._selected_service, self._selected_variant


class BakgrunnskartPlugin:
    """
    QGIS plugin:
    - Velg tjeneste + tilesett (variant) i samme dialog
    - Alle lag samles i én gruppe: "Bakgrunnskart"
    """

    MAIN_GROUP_NAME = "Bakgrunnskart"
    PREVIEW_ICON_SIZE = 50  # px

    # -----------------------------------------
    # SERVICES: Nå med valgfri "description" og "variants"
    #
    # Variant-dict kan inneholde:
    #  - For WMTS via GetCapabilities:
    #      {"type":"wmts", "label":"UTM33 (EPSG:25833)", "capabilities": "...GetCapabilities", "layer":"...", "style":"default", "format":"image/png", "tileMatrixSet":"utm33n", "crs":"EPSG:25833"}
    #  - For XYZ:
    #      {"type":"xyz", "label":"WebMercator (EPSG:3857)", "xyz_url":"https://...tileMatrix={z}&tileRow={y}&tileCol={x}", "zmin":0, "zmax":21}
    #
    # Du kan også la én tjeneste ha kun én variant (da blir det bare én radioknapp).
    # -----------------------------------------
    SERVICES = [
        {
            "name": "Flybilder (OBS! Fjernes 1. mars 2026)",
            "description": "Ortofoto (NIB) i WebMercator. Passer best i prosjekter med EPSG:3857. <a href=\"https://kartkatalog.geonorge.no/metadata/norge-i-bilder-wmts-mercator/1b690a65-4fed-4e5e-ad77-1218e2bf315f\">Se mer informasjon</a>. OBS! Tjenesten stenges fra 1. mars 2026. <a href=\"https://register.geonorge.no/varsler/norge-i-bilder-wmts-mercator/f0dd601a-54d9-40f1-bfeb-3a8f672ccd6c\">Se mer informasjon</a>.",
            "preview": "previews/aerial.png",
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
            ],
        },
        {
            "name": "Forenklet europakart",
            "description": "Forenklet bakgrunnskart for Nord-Europa. Egner seg godt som bakgrunnskart under ett av de andre bakgrunnskartene om du skal lage kart som strekker seg utover Norges landegrenser. <a href=\"https://kartkatalog.geonorge.no/metadata/europakart-forenklet-wms/4e904a49-e2dc-4099-b271-9463bdab7846\">Se mer informasjon</a>",
            "preview": "previews/europe.png",
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
                },
            ],
        },
        {
            "name": "Topografisk gråtonekart",
            "description": "En gråtone-basert kartografi med kartdata fra N50 til N2000, FKB, matrikkel, høyde- og dybdedata. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>",
            "preview": "previews/grey.png",
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
                },
            ],
        },
        {
            "name": "Topografisk norgeskart",
            "description": "En kartografi i farger med kartdata fra N50 til N2000, FKB, matrikkel, høyde- og dybdedata. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>",
            "preview": "previews/land.png",
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
                },
            ],
        },
        {
            "name": "Topografisk rasterkart",
            "description": "Rasterkart eller \"papirkart\" med lik presentasjon (symbolikk) som kartserien Norge 1:50 000. Innhold fra N50 til N2000 og N5. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>",
            "preview": "previews/raster.png",
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
                },
            ],
        },
        {
            "name": "Sjøkart",
            "description": "Sjøkart i rasterformat med sjødata fra overseilingskart, hovedkart, kystkart, havnekart samt Svalbardkart. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>",
            "preview": "previews/ocean.png",
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
                },
            ],
        },
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
    # URL encode for QGIS WMTS URI (url=... parameter)
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

        # encode for qgis uri: keep ? and =, encode &, {}, %
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
        if dlg.exec() != QDialog.Accepted:
            return

        service, variant = dlg.get_selection()
        if not service or not variant:
            return

        main_group = self.get_or_create_main_group()

        # Vis litt “jobber…” ved behov
        progress = QProgressDialog("Legger til lag…", "Avbryt", 0, 0, self.iface.mainWindow())
        progress.setWindowTitle("Bakgrunnskart")
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()

        try:
            vtype = (variant.get("type") or "").lower()

            # Layer title: bruk tjenestenavn, og vis valgt variant i parentes
            layer_title = f"{service.get('name', 'Bakgrunnskart')} ({variant.get('label', 'variant')})"
            variant = dict(variant)  # kopi
            variant["title"] = layer_title

            if vtype == "wmts":
                rl = self.add_wmts_layer(variant)
                main_group.addLayer(rl)
            elif vtype == "xyz":
                rl = self.add_xyz_layer(variant)
                main_group.addLayer(rl)
            else:
                raise RuntimeError("Ukjent variant-type. Bruk 'wmts' eller 'xyz'.")

        except Exception as e:
            QMessageBox.critical(self.iface.mainWindow(), "Bakgrunnskart", str(e))
        finally:
            try:
                progress.close()
            except Exception:
                pass
