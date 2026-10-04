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
4. The publisher writes a product config fragment, then composes `docs.json` from the authored Daylight template plus all available product fragments.
5. Git commits only when the generated site differs from what is already published.
6. Mintlify deploys the resulting commit.

Scheduled syncs detect new releases without cross-repository credentials. Manual syncs and publisher/workflow/template changes rebuild the current release immediately, so publishing fixes do not have to wait for another Card release.

This means unreleased documentation can live on the Card repository's normal development branch without becoming public.

## Authored vs generated files

Edit these directly:

- `docs.template.json` — Daylight-wide Mintlify configuration, global navigation, and hand-authored redirects
- `index.mdx` — Daylight landing page
- publisher/workflow/test files

Generated files should not be edited directly:

- `docs.json` — composed Mintlify configuration
- `card/`
- `.sync/card-release`
- `.sync/card-config.json`
- `images/`, `favicon.ico`, and `style.css` while the Card remains the source of the shared Daylight visual assets

Each product owns its generated config fragment. Composing from the template plus fragments avoids inferring ownership from previous `docs.json` output, preserves hand-authored Daylight redirects even when they match generated values, and allows future products to coexist without one product sync erasing another. Legacy root URLs are an explicit per-product capability: Calendar Card preserves the existing `/introduction`, `/configuration/...`, and similar URLs, while future products publish only inside their own namespace unless they actually have legacy root URLs to preserve.

Only site-level publishing metadata at the root of a product's `docs/` directory is excluded from that product's namespaced copy. Product-owned `images/`, `logo/`, and other local files remain inside the product namespace, and root-relative MDX links to copied pages/files are rewritten accordingly. The designated shared-assets product may additionally publish global assets used by the Daylight shell. Same-named nested directories such as `guides/images/` remain intact.

## Validation

The publisher is implemented in `scripts/publish_product_docs.py` and covered by standard-library unit tests. Pull requests validate both Mintlify JSON files and run the publisher tests before merge.
