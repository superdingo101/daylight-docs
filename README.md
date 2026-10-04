# Daylight documentation publisher

This repository is the **published Mintlify site** for the Daylight project family.

Product documentation is authored beside the code that it documents:

- Daylight Calendar Card: `superdingo101/daylight-calendar-card/docs/`
- Daylight Calendar Import: `superdingo101/daylight-calendar-import/docs/` (to be added later)

Do not hand-edit generated product documentation in this repository.

## Publishing model

`daylight-docs` imports documentation from **published GitHub releases**, not from development branches.

For Daylight Calendar Card:

1. Code, tests, and docs are changed together in the Card repository.
2. A GitHub release is published from the Card repository.
3. The sync workflow in this repository detects the new release tag.
4. It copies that release's `docs/` content into `card/`, rewrites internal links for the combined site, and updates navigation.
5. Mintlify deploys the resulting commit.

This means unreleased documentation can live on the Card repository's normal development branch without becoming public.

## Generated paths

The following are generated and should not be edited manually:

- `card/`
- `.sources/card.docs.json`
- `.sync/card-release`
- Card-derived navigation and redirects in `docs.json`
- `images/`, `favicon.ico`, and `style.css` while the Card remains the source of the shared Daylight visual assets

The site-wide landing page and global Mintlify configuration remain intentionally authored here.
