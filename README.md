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
4. The publisher writes a product config fragment, then composes `docs.json` from the authored Daylight template plus all complete product fragments.
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
- `images/`, `logo/`, `favicon.ico`, and `style.css` while the Card remains the source of the shared Daylight visual assets

Each product owns its generated config fragment and namespaced output directory. A publish refuses to replace a pre-existing repository directory unless an existing fragment records that same product as its owner, preventing product keys such as `scripts` or `images` from deleting authored/global content.

Composing from the template plus complete product fragments avoids inferring ownership from previous `docs.json` output, preserves hand-authored Daylight redirects even when they match generated values, rejects stale product fragments, and prevents one product sync from silently erasing or overriding another.

Legacy root URLs are an explicit per-product capability: Calendar Card preserves the existing `/introduction`, `/configuration/...`, and similar URLs, while future products publish only inside their own namespace unless they actually have legacy root URLs to preserve.

## Product content boundary

Released product content is treated as data, not rewritten source:

- symlinks anywhere under released `docs/` are rejected before copying;
- product `.mintignore` rules are evaluated in isolation with Git's ignore semantics (source `.gitignore` files and user/global Git excludes are not consulted), and ignored files are not copied;
- if navigation or a redirect destination points at a page excluded by `.mintignore`, publishing fails closed;
- `.md` and `.mdx` pages are both supported, and duplicate routes such as `guide.md` plus `guide.mdx` are rejected;
- product MDX/Markdown is copied **unchanged** so code examples, reference links, frontmatter, and other literal content are never mutated by the publishing layer.

Calendar Card is the legacy exception: its existing root page URLs are preserved with redirects and its released `images/`, `logo/`, favicon, and stylesheet are also copied to the global Daylight shell, so the current released Card docs continue to work unchanged.

New products should author product-local absolute links under their final namespace (for example, `/import/images/example.png` and `/import/introduction`) or use relative links. This keeps the publishing layer deterministic and avoids maintaining a custom MDX parser.

## Validation

The publisher is implemented in `scripts/publish_product_docs.py` and covered by standard-library unit tests. Pull requests validate both Mintlify JSON files and run the publisher tests before merge. GitHub Actions dependencies used by the write-capable publishing workflow are pinned to immutable commits.
