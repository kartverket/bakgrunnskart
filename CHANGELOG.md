## [1.0.0] - 2025-12-21

### Added

- Første publiserte versjon av **Bakgrunnskart** (QGIS-plugin).
- Katalog med forhåndsdefinerte Kartverket/Geonorge-bakgrunnskart.
- Dialog med tjenesteliste og statiske forhåndsvisninger (preview-bilder).
- Stor forhåndsvisning av valgt tjeneste i høyre panel.
- Navn på tjeneste vist tydelig over beskrivelse (uthevet).
- Beskrivelser med støtte for klikkbare lenker (HTML `<a href="...">`).
- Tilesett/projeksjon velges per tjeneste via radioknapper (forhåndsdefinerte valg).
- Søkefelt som filtrerer tjenestelista (inkl. treff i navn, beskrivelse og tileset-labels).
- Legger inn valgt bakgrunnskart i en egen laggruppe: `Bakgrunnskart`.

### Changed

- Forhåndsvisning skaleres med “cover”-logikk og topp-crop for mer konsistent visning.
- Forbedret HiDPI-rendering av previews for mindre kornete bilder på skjermer med scaling.
- Automatisk tekst-/lenkefarge i beskrivelse basert på lys/mørk modus.

### Fixed

- Stabilisert UI ved bytte av tjeneste og tileset (riktig oppdatering av preview, tittel, beskrivelse og radioknapper).
