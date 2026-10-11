# Bundled fonts

Latin subsets, self-hosted on purpose: the pages must not depend on an external font
service while a demo is running. A render-blocking `<link>` to `fonts.googleapis.com`
stalled first paint when that origin was slow — it failed the reduced-motion browser
check outright — and venue wi-fi is exactly where that would bite.

| File | Family | Licence |
|---|---|---|
| `archivo-var-latin.woff2` | Archivo (variable: weight 400–800, width 75–100%) | SIL Open Font License 1.1 |
| `plexmono-400-latin.woff2` | IBM Plex Mono 400 | SIL Open Font License 1.1 |
| `plexmono-500-latin.woff2` | IBM Plex Mono 500 | SIL Open Font License 1.1 |

Both families are OFL 1.1, which permits redistribution and self-hosting. Full licence
text: <https://openfontlicense.org>. Archivo by Omnibus-Type; IBM Plex Mono by IBM.

~110 KB total. `@font-face` rules live in `../design-system.css`, with
`font-display: swap` so text renders immediately in the fallback stack and reflows
once the faces load.

To refresh, re-request the CSS with a browser user-agent and pull the `latin` subset
URLs out of it:

```bash
curl -sS -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36" \
  "https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..100,400..800&family=IBM+Plex+Mono:wght@400;500&display=swap"
```
