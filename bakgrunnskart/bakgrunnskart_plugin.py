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
    QCheckBox,
    QSizePolicy,
)

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsApplication,
    QgsAuthMethodConfig,
    QgsSettings,
)

try:
    from qgis.core import QgsVectorTileLayer  # type: ignore
except Exception:
    QgsVectorTileLayer = None  # type: ignore

import os
from typing import Optional, List, Dict, Tuple


# -------------------------------------------------------------------------
# Qt5/Qt6 helpers
# -------------------------------------------------------------------------
def _qt_try(path: str):
    obj = Qt
    for part in path.split("."):
        if not hasattr(obj, part):
            return None
        obj = getattr(obj, part)
    return obj


def qt_pick(*paths: str, default=None):
    for p in paths:
        v = _qt_try(p)
        if v is not None:
            return v
    return default


def palette_role(name: str):
    v = getattr(QPalette, name, None)
    if v is not None:
        return v

    cr = getattr(QPalette, "ColorRole", None)
    if cr is not None and hasattr(cr, name):
        return getattr(cr, name)

    low = name[:1].lower() + name[1:]
    if hasattr(QPalette, low):
        return getattr(QPalette, low)

    raise AttributeError(f"Fant ikke QPalette role: {name}")


def dialog_accepted_code():
    v = getattr(QDialog, "Accepted", None)
    if v is not None:
        return v
    return QDialog.DialogCode.Accepted


def size_policy(name: str, default=None):
    v = getattr(QSizePolicy, name, None)
    if v is not None:
        return v

    pol = getattr(QSizePolicy, "Policy", None)
    if pol is not None and hasattr(pol, name):
        return getattr(pol, name)

    return default


def lineedit_echo_mode(name: str, default=None):
    v = getattr(QLineEdit, name, None)
    if v is not None:
        return v

    em = getattr(QLineEdit, "EchoMode", None)
    if em is not None and hasattr(em, name):
        return getattr(em, name)

    return default


QT_HORIZONTAL = qt_pick("Orientation.Horizontal", "Horizontal", default=1)
QT_VERTICAL = qt_pick("Orientation.Vertical", "Vertical", default=2)

QT_ALIGN_CENTER = qt_pick("AlignmentFlag.AlignCenter", "AlignCenter", default=0x0084)

QT_TEXT_BROWSER = qt_pick(
    "TextInteractionFlag.TextBrowserInteraction",
    "TextBrowserInteraction",
    default=0,
)

QT_KEEP_ASPECT = qt_pick(
    "AspectRatioMode.KeepAspectRatio",
    "KeepAspectRatio",
    default=1,
)

QT_SMOOTH_TRANSFORM = qt_pick(
    "TransformationMode.SmoothTransformation",
    "SmoothTransformation",
    default=1,
)

QT_RICHTEXT = qt_pick("TextFormat.RichText", "RichText", default=1)

QT_USER_ROLE = qt_pick("ItemDataRole.UserRole", "UserRole", default=0x0100)

QT_SIZEPOLICY_FIXED = size_policy("Fixed", 0)
QT_ECHO_PASSWORD = lineedit_echo_mode("Password", 2)


# -------------------------------------------------------------------------
# Dialog
# -------------------------------------------------------------------------
class ServicePickerDialog(QDialog):
    TYPE_ORDER = ["wmts", "wms", "vectortile"]

    SETTINGS_GROUP = "bakgrunnskart"
    SETTINGS_AUTHCFG = f"{SETTINGS_GROUP}/authcfg"

    PREVIEW_W = 687
    PREVIEW_H = 275

    def __init__(self, parent, services: List[Dict], plugin_dir: str, icon_size: int = 50):
        super().__init__(parent)
        self.setWindowTitle("Bakgrunnskart")

        self.services = services
        self.plugin_dir = plugin_dir
        self.icon_size = icon_size

        self._selected_service: Optional[Dict] = None
        self._selected_type_key: Optional[str] = None
        self._selected_variant: Optional[Dict] = None
        self._authcfg_id: str = ""

        self._preview_src_pm = QPixmap()

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

        # Fast preview-størrelse
        self.preview_big = QLabel()
        self.preview_big.setAlignment(QT_ALIGN_CENTER)
        self.preview_big.setFixedSize(self.PREVIEW_W, self.PREVIEW_H)
        self.preview_big.setSizePolicy(QT_SIZEPOLICY_FIXED, QT_SIZEPOLICY_FIXED)
        self.preview_big.setStyleSheet("QLabel { border: 1px solid rgba(255,255,255,0.15); }")
        right_layout.addWidget(self.preview_big, 0, QT_ALIGN_CENTER)

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

        # ---------------- AUTH UI ----------------
        self.auth_box = QGroupBox("Autentifisering for lukket tjeneste")
        auth_layout = QVBoxLayout(self.auth_box)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Brukernavn:"))
        self.auth_user = QLineEdit()
        self.auth_user.setPlaceholderText("f.eks. norge_digitalt_bruker")
        row2.addWidget(self.auth_user, 1)

        row2.addWidget(QLabel("Passord:"))
        self.auth_pass = QLineEdit()
        self.auth_pass.setPlaceholderText("passord")
        try:
            self.auth_pass.setEchoMode(QT_ECHO_PASSWORD)
        except Exception:
            pass
        row2.addWidget(self.auth_pass, 1)
        auth_layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.chk_remember = QCheckBox("Lagre sikkert i QGIS Authentication Manager (anbefalt)")
        self.chk_remember.setChecked(True)
        row3.addWidget(self.chk_remember, 1)

        self.btn_clear_auth = QPushButton("Fjern lagret auth")
        self.btn_clear_auth.setToolTip("Fjerner referanse til lagret autentifisering i plugin-innstillinger.")
        row3.addWidget(self.btn_clear_auth)
        auth_layout.addLayout(row3)

        self.auth_info = QLabel("")
        self.auth_info.setWordWrap(True)
        auth_layout.addWidget(self.auth_info)

        right_layout.addWidget(self.auth_box)
        self.auth_box.setVisible(False)

        right_layout.addStretch(1)

        splitter.setSizes([280, 760])

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

        self._populate_services()
        self.lw.currentItemChanged.connect(self._on_service_changed)
        self.search.textChanged.connect(self._apply_filter)

        self.btn_clear_auth.clicked.connect(self._clear_saved_auth)
        self._load_auth_settings()

        if self.lw.count() > 0:
            self.lw.setCurrentRow(0)
            self._on_service_changed(self.lw.currentItem(), None)

        self.resize(1120, 760)
        self.setFixedSize(self.size())
        try:
            self.setSizeGripEnabled(False)
        except Exception:
            pass

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
    # Offerings
    # -------------------------
    def _normalize_offerings(self, svc: Dict) -> Dict:
        offerings = svc.get("offerings")
        if isinstance(offerings, dict) and offerings:
            return offerings

        variants = svc.get("variants") or []
        out: Dict[str, Dict] = {}

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
                wmts_like.append(v)

        if wmts_like:
            out["wmts"] = {"label": "WMTS / XYZ", "variants": wmts_like}
        if wms_like:
            out["wms"] = {"label": "WMS", "variants": wms_like}
        if vt_like:
            out["vectortile"] = {"label": "Vector tiles", "variants": vt_like}

        if not out:
            out["wmts"] = {"label": "WMTS / XYZ", "variants": [{"label": "Standard", "key": "default"}]}

        return out

    def _current_offering(self) -> Dict:
        if not self._selected_service or not self._selected_type_key:
            return {}
        offerings = self._normalize_offerings(self._selected_service)
        off = offerings.get(self._selected_type_key) or {}
        return off if isinstance(off, dict) else {}

    def _current_selection_requires_auth(self) -> bool:
        return bool(self._current_offering().get("requires_auth"))

    def _update_auth_visibility(self):
        needs_auth = self._current_selection_requires_auth()
        self.auth_box.setVisible(needs_auth)

        if not needs_auth:
            return

        if self._authcfg_id:
            self.auth_info.setText(
                "Denne tjenesten er lukket og krever autentifisering.\n\n"
                "Det finnes allerede lagret autentisering i QGIS Authentication Manager. "
                "Du kan bruke den direkte, eller skrive inn nytt brukernavn og passord for å oppdatere."
            )
        else:
            self.auth_info.setText(
                "Denne tjenesten er lukket og krever autentifisering.\n\n"
                "Oppgi brukernavn og passord. Dette lagres via QGIS Authentication Manager (kryptert). "
                "Du kan bli bedt om å sette eller oppgi QGIS master password første gang."
            )

    # -------------------------
    # Preview helper
    # -------------------------
    def _scaled_fit_pixmap(self, pm: QPixmap, target_w: int, target_h: int) -> QPixmap:
        if pm.isNull():
            return pm

        dpr = self.devicePixelRatioF() or 1.0
        tw = max(1, int(target_w * dpr))
        th = max(1, int(target_h * dpr))

        scaled = pm.scaled(tw, th, QT_KEEP_ASPECT, QT_SMOOTH_TRANSFORM)
        scaled.setDevicePixelRatio(dpr)
        return scaled

    def _refresh_preview(self):
        if self._preview_src_pm is None or self._preview_src_pm.isNull():
            self.preview_big.clear()
            return

        banner = self._scaled_fit_pixmap(self._preview_src_pm, self.PREVIEW_W, self.PREVIEW_H)
        self.preview_big.setPixmap(banner)

    # -------------------------
    # Populate + search filter
    # -------------------------
    def _populate_services(self):
        self.lw.clear()

        for svc in self.services:
            name = svc.get("name", "(uten navn)")
            item = QListWidgetItem(name)

            offerings = self._normalize_offerings(svc)

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

            thumb_rel = svc.get("thumb") or svc.get("preview")
            if thumb_rel:
                p = os.path.join(self.plugin_dir, thumb_rel)
                if os.path.exists(p):
                    pm = QPixmap(p)
                    if not pm.isNull():
                        dpr = self.devicePixelRatioF() or 1.0
                        s = max(1, int(self.icon_size * dpr))
                        icon_pm = pm.scaled(s, s, QT_KEEP_ASPECT, QT_SMOOTH_TRANSFORM)
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
                self._preview_src_pm = QPixmap()
                self.preview_big.clear()
                self.title_label.setText("")
                self.desc.setText("")
                self._clear_types()
                self._clear_variants()
                self.auth_box.setVisible(False)

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

        preview_rel = svc.get("preview")
        self._preview_src_pm = QPixmap()
        if preview_rel:
            p = os.path.join(self.plugin_dir, preview_rel)
            if os.path.exists(p):
                pm = QPixmap(p)
                if not pm.isNull():
                    self._preview_src_pm = pm
        self._refresh_preview()

        name = svc.get("name", "")
        self.title_label.setText(f"<b>{name}</b>")
        self.desc.setText(svc.get("description", ""))

        self._populate_types(svc)
        self._populate_variants_for_type(svc, self._selected_type_key)
        self._update_auth_visibility()

    def _on_type_clicked(self, btn: QRadioButton):
        k = btn.property("type_key")
        if isinstance(k, str):
            self._selected_type_key = k
            if self._selected_service:
                self._populate_variants_for_type(self._selected_service, k)
            self._update_auth_visibility()

    def _on_variant_clicked(self, btn: QRadioButton):
        v = btn.property("variant_dict")
        if isinstance(v, dict):
            self._selected_variant = v

    # -------------------------
    # Auth helpers
    # -------------------------
    def _load_auth_settings(self):
        s = QgsSettings()
        self._authcfg_id = s.value(self.SETTINGS_AUTHCFG, "", type=str) or ""
        self._update_auth_visibility()

    def _clear_saved_auth(self):
        s = QgsSettings()
        s.setValue(self.SETTINGS_AUTHCFG, "")
        self._authcfg_id = ""
        self.auth_user.clear()
        self.auth_pass.clear()
        self._update_auth_visibility()
        QMessageBox.information(
            self,
            "Bakgrunnskart",
            "Lagret autentifisering (referanse) er fjernet fra plugin-innstillinger.\n\n"
            "Merk: Selve auth-konfigurasjonen kan fortsatt ligge i QGIS Authentication Manager.",
        )

    def _ensure_auth_manager_ready(self) -> bool:
        authm = QgsApplication.authManager()
        if authm is None or authm.isDisabled():
            QMessageBox.warning(self, "Bakgrunnskart", "QGIS Authentication Manager er deaktivert.")
            return False

        try:
            if not authm.masterPasswordIsSet():
                ok = authm.setMasterPassword(True)
                if not ok:
                    return False
        except Exception:
            pass

        return True

    def _upsert_basic_authcfg(self, username: str, password: str) -> str:
        if not self._ensure_auth_manager_ready():
            return ""

        authm = QgsApplication.authManager()

        existing_id = (QgsSettings().value(self.SETTINGS_AUTHCFG, "", type=str) or "").strip()
        if existing_id:
            try:
                cfg = QgsAuthMethodConfig()
                ok = authm.loadAuthenticationConfig(existing_id, cfg, True)
                if ok:
                    cfg.setMethod("Basic")
                    cfg.setName("Bakgrunnskart (plugin)")
                    cfg.setConfig("username", username)
                    cfg.setConfig("password", password)
                    authm.updateAuthenticationConfig(cfg)
                    self._authcfg_id = existing_id
                    QgsSettings().setValue(self.SETTINGS_AUTHCFG, existing_id)
                    return existing_id
            except Exception:
                pass

        cfg = QgsAuthMethodConfig()
        try:
            cfg.setMethod("Basic")
        except Exception:
            pass
        cfg.setName("Bakgrunnskart (plugin)")
        cfg.setConfig("username", username)
        cfg.setConfig("password", password)

        authm.storeAuthenticationConfig(cfg)
        new_id = cfg.id() or ""
        self._authcfg_id = new_id
        QgsSettings().setValue(self.SETTINGS_AUTHCFG, new_id)
        return new_id

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

        self._authcfg_id = (QgsSettings().value(self.SETTINGS_AUTHCFG, "", type=str) or "").strip()

        if self._current_selection_requires_auth():
            user = (self.auth_user.text() or "").strip()
            pwd = (self.auth_pass.text() or "").strip()

            # Har vi lagret auth fra før og brukeren ikke skriver inn nytt -> bruk lagret
            if (not user or not pwd) and self._authcfg_id:
                self.accept()
                return

            if not user or not pwd:
                QMessageBox.warning(
                    self,
                    "Bakgrunnskart",
                    "Denne tjenesten er lukket og krever autentifisering.\n\n"
                    "Fyll inn brukernavn og passord, eller bruk lagret autentifisering hvis du allerede har det.",
                )
                return

            if not self.chk_remember.isChecked():
                QMessageBox.information(
                    self,
                    "Bakgrunnskart",
                    "Denne pluginen støtter per nå kun lagring via QGIS Authentication Manager.\n"
                    "La «Lagre sikkert …» stå på.",
                )
                return

            authcfg = self._upsert_basic_authcfg(user, pwd)
            if not authcfg:
                QMessageBox.warning(
                    self,
                    "Bakgrunnskart",
                    "Klarte ikke å lagre autentifisering i QGIS Authentication Manager.",
                )
                return
            self._authcfg_id = authcfg

        self.accept()

    def get_selection(self) -> Tuple[Optional[Dict], Optional[str], Optional[Dict], str]:
        if self.result() != dialog_accepted_code():
            return None, None, None, ""
        return self._selected_service, self._selected_type_key, self._selected_variant, (self._authcfg_id or "")


# -------------------------------------------------------------------------
# Plugin
# -------------------------------------------------------------------------
class BakgrunnskartPlugin:
    MAIN_GROUP_NAME = "Bakgrunnskart"
    PREVIEW_ICON_SIZE = 50

    # ---------------------------------------------------------------------
    # SERVICES
    # ---------------------------------------------------------------------
    SERVICES = [
        {
        "name": "Fjellskygge",
        "description": "Denne tjenesten inneholder fjellskygger. Den er ment for å kombineres med andre tjenester. <a href=\"https://kartkatalog.geonorge.no/metadata/fjellskygge-wms/57bcf66a-1333-498f-a1f1-13f27a9cee1f\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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
        "name": "Norges grunnkart",
        "description": "Tjenesten inneholder topografiske kart i målestokken 1:500 til 1:10M. <a href=\"https://kartkatalog.geonorge.no/metadata/norges-grunnkart-wms/8ecaa2d5-8b0a-46cf-a2a7-2584f78b12e2\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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
        "description": "Tjenesten inneholder topografiske kart i målestokken 1:500 til 1:10M i gråskala. <a href=\"https://kartkatalog.geonorge.no/metadata/norges-grunnkart-graatone-wms/d24a0bf9-1398-4bc4-a4ba-63896b0a599c\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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
        "name": "Satellittbilder - Sentinel-2",
        "description": "Årlig skyfri satellittdatamosaikk sammensatt av Sentinel-2-bilder. <a href=\"https://kartkatalog.geonorge.no/metadata/satellittdata-sentinel-2-skyfri-mosaikk-wms/38a52b73-2ffb-47cc-9ecd-147ee18f62be\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
        "preview": "previews/satellite.png",
        "thumb": "previews/satellite_thumb.png",
        "offerings": {
            "wms": {
            "label": "WMS",
            "variants": [
                {
                "type": "wms",
                "label": "UTM 32N (EPSG:25832)",
                "url": "https://wms.geonorge.no/skwms1/wms.sentinel2?request=GetCapabilities&service=WMS",
                "layers": "sentinel2",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25832",
                },
                {
                "type": "wms",
                "label": "UTM 33N (EPSG:25833)",
                "url": "https://wms.geonorge.no/skwms1/wms.sentinel2?request=GetCapabilities&service=WMS",
                "layers": "sentinel2",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25833",
                },
                {
                "type": "wms",
                "label": "UTM 35N (EPSG:25835)",
                "url": "https://wms.geonorge.no/skwms1/wms.sentinel2?request=GetCapabilities&service=WMS",
                "layers": "sentinel2",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:25835",
                },
                {
                "type": "wms",
                "label": "WebMercator (EPSG:3857)",
                "url": "https://wms.geonorge.no/skwms1/wms.sentinel2?request=GetCapabilities&service=WMS",
                "layers": "sentinel2",
                "styles": "",
                "format": "image/png",
                "crs": "EPSG:3857",
                },
                {
                "type": "wms",
                "label": "WGS84 (EPSG:4326)",
                "url": "https://wms.geonorge.no/skwms1/wms.sentinel2?request=GetCapabilities&service=WMS",
                "layers": "sentinel2",
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
        "description": "Sjøkart i rasterformat med sjødata fra overseilingskart, hovedkart, kystkart, havnekart samt Svalbardkart. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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
        "description": "En gråtone-basert kartografi med kartdata fra N50 til N2000, FKB, matrikkel, høyde- og dybdedata. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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
        "description": "En kartografi i farger med kartdata fra N50 til N2000, FKB, matrikkel, høyde- og dybdedata. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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
            "description": "Rasterkart eller \"papirkart\" med lik presentasjon (symbolikk) som kartserien Norge 1:50 000. Innhold fra N50 til N2000 og N5. <a href=\"https://kartkatalog.geonorge.no/metadata/topografisk-norgeskart-wmts--cache/8f381180-1a47-4453-bee7-9a3d64843efa\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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
        "description": "Informasjon tilsvarende digitalt økonomisk kartverk (ØK). N5 er basert på utvalgte, generaliserte FKB-data. <a href=\"https://kartkatalog.geonorge.no/metadata/n5raster2-wms/79ea9761-1ac9-4780-a065-e4738835643e\">Se mer informasjon</a>. &copy; <a href=\"https://www.kartverket.no\">Kartverket</a>.",
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

    def get_or_create_main_group(self):
        root = QgsProject.instance().layerTreeRoot()
        grp = root.findGroup(self.MAIN_GROUP_NAME)
        if grp is None:
            grp = root.addGroup(self.MAIN_GROUP_NAME)
        return grp

    def encode_url_for_qgis_uri(self, url: str) -> str:
        return (
            url.replace("%", "%25")
            .replace("=", "%3D")
            .replace("&", "%26")
        )

    def add_xyz_layer(self, variant: Dict, authcfg: str = "") -> QgsRasterLayer:
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
        if authcfg:
            uri += f"&authcfg={authcfg}"

        title = variant.get("title") or variant.get("label") or "XYZ"

        rl = QgsRasterLayer(uri, title, "wms")
        if not rl.isValid():
            raise RuntimeError(f"Klarte ikke å opprette XYZ-lag.\n\nURI:\n{uri}")

        QgsProject.instance().addMapLayer(rl, False)
        return rl

    def add_wmts_layer(self, variant: Dict, authcfg: str = "") -> QgsRasterLayer:
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
        if authcfg:
            uri += f"&authcfg={authcfg}"

        title = variant.get("title") or variant.get("label") or "WMTS"
        rl = QgsRasterLayer(uri, title, "wms")
        if not rl.isValid():
            raise RuntimeError(
                "Klarte ikke å opprette WMTS-lag.\n\n"
                f"Capabilities:\n{cap}\n\nURI:\n{uri}"
            )

        QgsProject.instance().addMapLayer(rl, False)
        return rl

    def add_wms_layer(self, variant: Dict, authcfg: str = "") -> QgsRasterLayer:
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
        if authcfg:
            uri += f"&authcfg={authcfg}"

        title = variant.get("title") or variant.get("label") or "WMS"
        rl = QgsRasterLayer(uri, title, "wms")
        if not rl.isValid():
            raise RuntimeError(
                "Klarte ikke å opprette WMS-lag.\n\n"
                f"URL:\n{url}\n\nURI:\n{uri}"
            )

        QgsProject.instance().addMapLayer(rl, False)
        return rl

    def add_vectortile_layer(self, variant: Dict):
        if QgsVectorTileLayer is None:
            raise RuntimeError("Denne QGIS-versjonen har ikke QgsVectorTileLayer tilgjengelig.")

        title = variant.get("title") or variant.get("label") or "Vector tiles"

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

        service, type_key, variant, authcfg = dlg.get_selection()
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
            variant = dict(variant)
            variant["title"] = layer_title

            if vtype == "wmts":
                rl = self.add_wmts_layer(variant, authcfg=authcfg)
                main_group.addLayer(rl)

            elif vtype == "xyz":
                rl = self.add_xyz_layer(variant, authcfg=authcfg)
                main_group.addLayer(rl)

            elif vtype == "wms":
                rl = self.add_wms_layer(variant, authcfg=authcfg)
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