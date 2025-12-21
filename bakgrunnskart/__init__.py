# -*- coding: utf-8 -*-

def classFactory(iface):
    """
    QGIS kaller denne funksjonen for å instansiere plugin-klassen.
    """
    from .bakgrunnskart_plugin import BakgrunnskartPlugin
    return BakgrunnskartPlugin(iface)
