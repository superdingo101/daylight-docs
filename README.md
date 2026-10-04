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
3. The sync workflow resolves that release by its explicit Git tag ref and deterministically rebuilds the Card section.
4. Git commits only when the generated site differs from what is already published.
5. Mintlify deploys the resulting commit.

Scheduled syncs detect new releases without cross-repository credentials. Manual syncs and publisher/workflow changes rebuild the current release immediately, so fixes to publishing logic do not have to wait for another Card release.

This means unreleased documentation can live on the Card repository's normal development branch without becoming public.

## Generated paths

The following are generated and should not be edited manually:

- `card/`
- `.sync/card-release`
- `.sync/card-generated-redirects.json`
- Card-derived navigation and compatibility redirects in `docs.json`
- `images/`, `favicon.ico`, and `style.css` while the Card remains the source of the shared Daylight visual assets

The publisher records the exact redirects it generated so future rebuilds can replace only those entries. Hand-authored Daylight redirects remain untouched.

The site-wide landing page and global Mintlify configuration remain intentionally authored here.

## Validation

The publisher is implemented in `scripts/publish_product_docs.py` and covered by standard-library unit tests. Pull requests validate `docs.json` and run the publisher tests before merge.
