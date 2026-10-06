import json
import pathlib
import tempfile
import unittest

from scripts.publish_product_docs import publish


class PublishProductDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / ".tmp" / "card-source" / "docs"
        self.source.mkdir(parents=True)

        self.manual_alias = {
            "source": "/calendar",
            "destination": "/card/introduction",
            "permanent": True,
        }
        self.manual_collision = {
            "source": "/introduction",
            "destination": "/custom-introduction",
            "permanent": True,
        }

        (self.root / "docs.template.json").write_text(json.dumps({
            "name": "Daylight",
            "navigation": {
                "global": {"anchors": [{"anchor": "Home", "href": "/"}]},
                "tabs": [{
                    "tab": "About",
                    "groups": [{"group": "About", "pages": ["about"]}],
                }],
            },
            "redirects": [
                {"source": "/keep", "destination": "/somewhere-else", "permanent": True},
                self.manual_alias,
                self.manual_collision,
            ],
        }))
        (self.root / "docs.json").write_text(json.dumps({
            "navigation": {"tabs": [{"tab": "Stale", "groups": []}]},
            "redirects": [{"source": "/stale", "destination": "/card/stale", "permanent": True}],
        }))

        (self.source / "docs.json").write_text(json.dumps({
            "navigation": {
                "groups": [{
                    "group": "Get Started",
                    "root": "introduction",
                    "pages": ["introduction", "guides/setup", "guides/plain"],
                }]
            },
            "redirects": [
                {"source": "/", "destination": "/introduction", "permanent": True},
                {"source": "/old-guide", "destination": "/guides/setup", "permanent": True},
                {"source": "/introduction", "destination": "/old-guide", "permanent": True},
                {"source": "/external", "destination": "https://example.com/reference", "permanent": False},
            ],
        }))
        (self.source / ".mintignore").write_text(
            "# Draft content\n"
            "drafts/\n"
            "*.draft.mdx\n"
        )

        (self.source / "index.mdx").write_text(
            '<Card href="/introduction">Start</Card>\n'
            '<img src="/images/logo.png" />\n'
            '[Setup](/guides/setup?mode=fast "Setup guide")\n'
            '![Logo](/logo/light.svg)\n'
            '[logo-ref]: /images/logo.png "Logo"\n'
            '[Reference][logo-ref]\n'
            '[Escape](/../docs.template.json)\n'
            '`<img src="/images/logo.png" />`\n'
            '```html\n<img src="/images/logo.png" />\n```\n'
        )
        (self.source / "introduction.mdx").write_text('[Setup](/guides/setup#next)\n')

        guides = self.source / "guides"
        guides.mkdir()
        (guides / "setup.mdx").write_text("# Setup\n")
        (guides / "plain.md").write_text("# Plain Markdown\n")
        nested_images = guides / "images"
        nested_images.mkdir()
        (nested_images / "step.png").write_bytes(b"nested image")
        nested_logo = guides / "logo"
        nested_logo.mkdir()
        (nested_logo / "mark.svg").write_text("<svg/>")

        images = self.source / "images"
        images.mkdir()
        (images / "logo.png").write_bytes(b"shared image")
        root_logo = self.source / "logo"
        root_logo.mkdir()
        (root_logo / "light.svg").write_text("<svg/>")

        drafts = self.source / "drafts"
        drafts.mkdir()
        (drafts / "internal.mdx").write_text("# Internal\n")
        (self.source / "scratch.draft.mdx").write_text("# Scratch\n")

        (self.source / "favicon.ico").write_bytes(b"icon")
        (self.source / "style.css").write_text("body {}\n")
        (self.source / "AGENTS.md").write_text("not published\n")
        (self.source / ".atlas-analysis.json").write_text("{}\n")

    def tearDown(self):
        self.temp.cleanup()

    def publish_card(self):
        publish(
            source_docs=self.source,
            product_key="card",
            product_label="Calendar Card",
            product_icon="calendar-days",
            release_tag="v1.2.3",
            publish_shared_assets=True,
            preserve_legacy_root_urls=True,
            repo_root=self.root,
        )

    def publish_import(self):
        publish(
            source_docs=self.source,
            product_key="import",
            product_label="Calendar Import",
            product_icon="sparkles",
            release_tag="v0.5.0",
            publish_shared_assets=False,
            preserve_legacy_root_urls=False,
            repo_root=self.root,
        )

    def read_config(self):
        return json.loads((self.root / "docs.json").read_text())

    def test_publish_rebuilds_config_from_template_and_adds_product(self):
        self.publish_card()
        config = self.read_config()
        tab_names = [tab["tab"] for tab in config["navigation"]["tabs"]]
        self.assertEqual(["About", "Calendar Card"], tab_names)
        card_tab = config["navigation"]["tabs"][1]
        self.assertEqual(["card/index"], card_tab["groups"][0]["pages"])
        self.assertEqual(
            ["card/introduction", "card/guides/setup", "card/guides/plain"],
            card_tab["groups"][1]["pages"],
        )
        self.assertEqual("card/introduction", card_tab["groups"][1]["root"])
        self.assertFalse(any(tab["tab"] == "Stale" for tab in config["navigation"]["tabs"]))

    def test_local_api_spec_references_are_namespaced(self):
        config = json.loads((self.source / "docs.json").read_text())
        config["navigation"]["groups"].extend([
            {
                "group": "API",
                "openapi": "openapi.json",
                "asyncapi": {"source": "asyncapi.yaml"},
            },
            {
                "group": "Remote API",
                "openapi": "https://example.com/openapi.json",
            },
        ])
        (self.source / "docs.json").write_text(json.dumps(config))
        (self.source / "openapi.json").write_text("{}\n")
        (self.source / "asyncapi.yaml").write_text("asyncapi: 3.0.0\n")

        self.publish_card()

        groups = self.read_config()["navigation"]["tabs"][1]["groups"]
        api_group = next(group for group in groups if group["group"] == "API")
        remote_group = next(group for group in groups if group["group"] == "Remote API")
        self.assertEqual("card/openapi.json", api_group["openapi"])
        self.assertEqual("card/asyncapi.yaml", api_group["asyncapi"]["source"])
        self.assertEqual(
            "https://example.com/openapi.json",
            remote_group["openapi"],
        )

    def test_authored_redirects_are_preserved_and_win_source_collisions(self):
        self.publish_card()
        redirects = self.read_config()["redirects"]
        self.assertIn(self.manual_alias, redirects)
        self.assertIn(self.manual_collision, redirects)
        self.assertEqual(1, sum(1 for r in redirects if r["source"] == "/introduction"))

    def test_current_namespaced_route_beats_historical_redirect(self):
        self.publish_card()
        fragment = json.loads((self.root / ".sync" / "card-config.json").read_text())
        redirects = fragment["redirects"]
        self.assertNotIn(
            {"source": "/card/introduction", "destination": "/card/old-guide", "permanent": True},
            redirects,
        )
        self.assertIn(
            {"source": "/introduction", "destination": "/card/introduction", "permanent": True},
            redirects,
        )

    def test_current_route_removes_covering_wildcard_redirects(self):
        config = json.loads((self.source / "docs.json").read_text())
        config["redirects"].append({
            "source": "/guides/:slug*",
            "destination": "/introduction",
            "permanent": True,
        })
        (self.source / "docs.json").write_text(json.dumps(config))

        self.publish_card()

        fragment = json.loads((self.root / ".sync" / "card-config.json").read_text())
        sources = {redirect["source"] for redirect in fragment["redirects"]}
        self.assertNotIn("/card/guides/:slug*", sources)
        self.assertNotIn("/guides/:slug*", sources)
        self.assertIn("/guides/setup", sources)

    def test_product_content_is_copied_unchanged(self):
        source_index = (self.source / "index.mdx").read_text()
        self.publish_card()
        self.assertEqual(source_index, (self.root / "card" / "index.mdx").read_text())

    def test_mintignore_excludes_drafts_using_gitignore_semantics(self):
        self.publish_card()
        self.assertFalse((self.root / "card" / "drafts").exists())
        self.assertFalse((self.root / "card" / "scratch.draft.mdx").exists())
        self.assertFalse((self.root / "card" / ".mintignore").exists())

    def test_mintignore_does_not_consult_source_gitignore(self):
        (self.source / ".gitignore").write_text("gitignored-only.mdx\n")
        (self.source / "gitignored-only.mdx").write_text("# Still published\n")

        self.publish_card()

        self.assertTrue((self.root / "card" / "gitignored-only.mdx").exists())

    def test_mintignored_navigation_target_fails_closed(self):
        config = json.loads((self.source / "docs.json").read_text())
        config["navigation"]["groups"][0]["pages"].append("drafts/internal")
        (self.source / "docs.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "excluded by .mintignore"):
            self.publish_card()

    def test_mintignored_redirect_destination_fails_closed(self):
        config = json.loads((self.source / "docs.json").read_text())
        config["redirects"].append({
            "source": "/draft",
            "destination": "/drafts/internal",
            "permanent": True,
        })
        (self.source / "docs.json").write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, "excluded by .mintignore"):
            self.publish_card()

    def test_shared_assets_include_logo_and_respect_product_copy(self):
        self.publish_card()
        self.assertTrue((self.root / "card" / "images" / "logo.png").exists())
        self.assertTrue((self.root / "card" / "logo" / "light.svg").exists())
        self.assertTrue((self.root / "images" / "logo.png").exists())
        self.assertTrue((self.root / "logo" / "light.svg").exists())
        self.assertTrue((self.root / "favicon.ico").exists())
        self.assertTrue((self.root / "style.css").exists())

    def test_authored_root_route_wins_over_legacy_alias(self):
        authored = self.root / "guides" / "setup.mdx"
        authored.parent.mkdir()
        authored.write_text("# Daylight-owned setup\n")

        self.publish_card()

        redirects = self.read_config()["redirects"]
        self.assertFalse(any(
            redirect.get("source") == "/guides/setup"
            and redirect.get("destination") == "/card/guides/setup"
            for redirect in redirects
        ))

    def test_non_shared_product_does_not_replace_global_assets(self):
        self.publish_card()
        global_image = (self.root / "images" / "logo.png").read_bytes()
        (self.source / "images" / "logo.png").write_bytes(b"import image")
        self.publish_import()
        self.assertEqual(b"import image", (self.root / "import" / "images" / "logo.png").read_bytes())
        self.assertEqual(global_image, (self.root / "images" / "logo.png").read_bytes())

    def test_only_legacy_product_claims_root_compatibility_urls(self):
        self.publish_card()
        self.publish_import()
        import_fragment = json.loads((self.root / ".sync" / "import-config.json").read_text())
        import_sources = {r["source"] for r in import_fragment["redirects"]}
        self.assertIn("/import/old-guide", import_sources)
        self.assertNotIn("/old-guide", import_sources)
        self.assertNotIn("/introduction", import_sources)

    def test_existing_product_fragments_are_composed_with_current_product(self):
        sync_dir = self.root / ".sync"
        sync_dir.mkdir()
        (self.root / "import").mkdir()
        (sync_dir / "import-release").write_text("v0.4.0\n")
        (sync_dir / "import-config.json").write_text(json.dumps({
            "product_key": "import",
            "tab": {"tab": "Calendar Import", "icon": "sparkles", "groups": [{"group": "Get Started", "pages": ["import/index"]}]},
            "redirects": [{"source": "/import-old", "destination": "/import/index", "permanent": True}],
        }))
        self.publish_card()
        config = self.read_config()
        self.assertEqual(["About", "Calendar Card", "Calendar Import"], [t["tab"] for t in config["navigation"]["tabs"]])

    def test_stale_fragment_fails_closed(self):
        sync_dir = self.root / ".sync"
        sync_dir.mkdir()
        (sync_dir / "import-config.json").write_text(json.dumps({
            "product_key": "import",
            "tab": {"tab": "Calendar Import", "groups": []},
            "redirects": [],
        }))
        with self.assertRaisesRegex(ValueError, "Stale or incomplete"):
            self.publish_card()

    def test_release_marker_without_fragment_fails_closed(self):
        sync_dir = self.root / ".sync"
        sync_dir.mkdir()
        (self.root / "import").mkdir()
        (sync_dir / "import-release").write_text("v0.4.0\n")

        with self.assertRaisesRegex(ValueError, "Stale or incomplete product ownership"):
            self.publish_card()

    def test_rejects_symlinks_in_released_docs(self):
        target = self.root / "outside-secret"
        target.write_text("secret")
        (self.source / "leak.txt").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.publish_card()

    def test_rejects_unsafe_or_colliding_product_keys(self):
        with self.assertRaisesRegex(ValueError, "Invalid product key"):
            publish(
                source_docs=self.source,
                product_key="../escape",
                product_label="Escape",
                product_icon="triangle-alert",
                release_tag="v1",
                publish_shared_assets=False,
                preserve_legacy_root_urls=False,
                repo_root=self.root,
            )
        with self.assertRaisesRegex(ValueError, "Invalid product key"):
            publish(
                source_docs=self.source,
                product_key="api",
                product_label="API",
                product_icon="code",
                release_tag="v1",
                publish_shared_assets=False,
                preserve_legacy_root_urls=False,
                repo_root=self.root,
            )

        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "keep.py").write_text("# keep\n")
        with self.assertRaisesRegex(ValueError, "collides with unmanaged or incomplete repository path"):
            publish(
                source_docs=self.source,
                product_key="scripts",
                product_label="Scripts",
                product_icon="code",
                release_tag="v1",
                publish_shared_assets=False,
                preserve_legacy_root_urls=False,
                repo_root=self.root,
            )
        self.assertTrue((scripts / "keep.py").exists())

    def test_existing_product_root_requires_complete_ownership_markers(self):
        card = self.root / "card"
        card.mkdir()
        sync_dir = self.root / ".sync"
        sync_dir.mkdir()
        (sync_dir / "card-config.json").write_text(json.dumps({
            "product_key": "card",
            "tab": {"tab": "Calendar Card", "groups": []},
            "redirects": [],
        }))

        with self.assertRaisesRegex(
            ValueError,
            "unmanaged or incomplete repository path",
        ):
            self.publish_card()

    def test_generated_product_conflicts_fail_instead_of_silently_winning(self):
        sync_dir = self.root / ".sync"
        sync_dir.mkdir()
        (self.root / "other").mkdir()
        (sync_dir / "other-release").write_text("v1\n")
        (sync_dir / "other-config.json").write_text(json.dumps({
            "product_key": "other",
            "tab": {"tab": "Calendar Card", "icon": "calendar", "groups": [{"group": "Other", "pages": ["other/index"]}]},
            "redirects": [],
        }))
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.publish_card()

    def test_duplicate_md_and_mdx_routes_fail(self):
        (self.source / "guides" / "setup.md").write_text("# Duplicate\n")
        with self.assertRaisesRegex(ValueError, "Duplicate documentation route"):
            self.publish_card()

    def test_ignored_duplicate_route_does_not_block_publish(self):
        (self.source / "guides" / "setup.md").write_text("# Ignored duplicate\n")
        with (self.source / ".mintignore").open("a") as ignore_file:
            ignore_file.write("guides/setup.md\n")

        self.publish_card()

        self.assertTrue((self.root / "card" / "guides" / "setup.mdx").exists())
        self.assertFalse((self.root / "card" / "guides" / "setup.md").exists())

    def test_publish_is_deterministic_when_repeated_for_same_release(self):
        self.publish_card()
        first_config = (self.root / "docs.json").read_text()
        first_fragment = (self.root / ".sync" / "card-config.json").read_text()
        first_index = (self.root / "card" / "index.mdx").read_text()
        self.publish_card()
        self.assertEqual(first_config, (self.root / "docs.json").read_text())
        self.assertEqual(first_fragment, (self.root / ".sync" / "card-config.json").read_text())
        self.assertEqual(first_index, (self.root / "card" / "index.mdx").read_text())


if __name__ == "__main__":
    unittest.main()
