# FC Barcelona · Primer equip (dashboard no oficial)

Web estàtica (un sol `index.html`) amb resultats, classificació, plantilla, estadístiques, vídeos i notícies del primer equip.

- **Dades en directe:** el navegador les demana a l'API pública d'ESPN.
- **Notícies, vídeos i baixes:** una tasca de GitHub Actions (`.github/workflows/dades.yml`) les recull cada 15 min i les desa a la branca `data` (`feeds.json`).
- **Fotos:** `fotos/<dorsal>.webp`, retallades de les oficials amb `scripts/retalla_fotos.py`.

Projecte no oficial, sense afiliació amb el FC Barcelona. L'escut, les fotos i els vídeos pertanyen al club i als seus titulars.
