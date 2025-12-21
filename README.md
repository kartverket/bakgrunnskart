# Bakgrunnskart (QGIS-plugin)

**Bakgrunnskart** er en enkel QGIS-plugin som gir en liten “katalog” over utvalgte, åpne bakgrunnskart fra Kartverket/Geonorge (primært WMTS-cache).  
Du velger et kart, ser forhåndsvisning og beskrivelse, velger ønsket tilesett (f.eks. UTM 32/33/35 eller WebMercator), og legger kartet inn i prosjektet.

## Funksjoner

- Katalog med forhåndsdefinerte Kartverket/Geonorge-bakgrunnskart
- Stor forhåndsvisning (preview) + beskrivelse (støtter klikkbare lenker)
- Valg av tilesett/projeksjon per tjeneste (radioknapper)
- Søkefelt for å filtrere tjenestelista
- Legger inn valgt kart i en egen gruppe i lagpanelet: `Bakgrunnskart`

## Tjenester (foreløpig)

- Flybilder _(OBS! Fjernes 1. mars 2026)_
- Forenklet europakart
- Topografisk gråtonekart
- Topografisk norgeskart
- Topografisk rasterkart
- Sjøkart

## Installering (fra ZIP)

1. Sørg for at plugin-mappen heter `bakgrunnskart` (samme navn som i `metadata.txt`).
2. Zip **hele** plugin-mappen (ikke bare innholdet).
3. I QGIS: **Plugins → Manage and Install Plugins… → Install from ZIP**

## Minimumsfiler i pluginen

- `metadata.txt`
- `__init__.py`
- `bakgrunnskart_plugin.py`
- `icon_bakgrunnskart.svg`
- `previews/` _(forhåndsvisningsbilder)_

## Utvikling / feilrapportering

Kildekode og issues håndteres på GitHub (se pluginens `homepage`/`tracker` i `metadata.txt`).
