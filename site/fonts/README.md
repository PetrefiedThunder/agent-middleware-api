# Vendored webfonts

Generated. Do not hand-edit this directory or `../fonts.css` — run
`python3 vendor_fonts.py` from `site/` and commit the result.

The test suite enforces the offline half of that contract: every `src` in
`fonts.css` must resolve to a committed file here, and no file here may be
orphaned. Verifying against upstream needs the network, so it is a manual step —
`python3 vendor_fonts.py --check`.

These files are served from this origin so the site makes no third-party request
for typography. That removes two cross-origin handshakes
(`fonts.googleapis.com` for the CSS, `fonts.gstatic.com` for the files) from the
critical path, and lets `vercel.json` keep `style-src 'self'; font-src 'self'`
with no external host in the Content-Security-Policy.

## Licensing

All three families are licensed under the **SIL Open Font License 1.1**, which
permits redistribution and web embedding. Full text:
<https://openfontlicense.org/open-font-license-official-text/>

| Family | Upstream | Copyright |
| --- | --- | --- |
| IBM Plex Mono | <https://github.com/IBM/plex> | Copyright © 2017 IBM Corp. |
| Libre Franklin | <https://github.com/impallari/Libre-Franklin> | Copyright © 2015 Impallari Type |
| Public Sans | <https://github.com/uswds/public-sans> | Copyright © 2015-2019 Impallari Type; Copyright © 2019 USWDS |

The OFL requires that the fonts not be sold on their own and that any modified
version be renamed. Neither applies here: these are unmodified subsets as served
by the Google Fonts API.

## What is in here

Only the `latin` and `latin-ext` subsets are vendored. The site is English;
`latin-ext` covers accented characters in an operator's name. Each face keeps
Google's `unicode-range`, so a browser downloads only the subsets a page needs.

`libre-franklin-*` and `public-sans-*` carry no weight in their filename because
those families are **variable fonts**: upstream serves one file per subset and
varies the `wght` axis from the `font-weight` on each `@font-face`. IBM Plex Mono
is static, so its files are per weight.
