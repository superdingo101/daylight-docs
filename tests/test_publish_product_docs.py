import json
import pathlib
import tempfile
import unittest

from scripts.publish_product_docs import publish


class PublishProductDocsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()

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
                "global": {
                    "anchors": [{"anchor": "Home", "href": "/"}]
                },
                "tabs": [
                    {
                        "tab": "About",
                        "groups": [
                            {"group": "About", "pages": ["about"]}
                        ],
                    }
                ],
            },
            "redirects": [
                {
                    "source": "/keep",
                    "destination": "/somewhere-else",
                    "permanent": True,
                },
                self.manual_alias,
                self.manual_collision,
            ],
        }))

        # This file is intentionally stale. Publishing must rebuild it from the
        # authored template rather than infer ownership from previous output.
        (self.root / "docs.json").write_text(json.dumps({
            "navigation": {"tabs": [{"tab": "Stale", "groups": []}]},
            "redirects": [
                {
                    "source": "/stale",
                    "destination": "/card/stale",
                    "permanent": True,
                }
            ],
        }))

        (self.source / "docs.json").write_text(json.dumps({
            "navigation": {
                "groups": [
                    {
                        "group": "Get Started",
                        "pages": ["introduction", "guides/setup"],
                    }
                ]
            },
            "redirects": [
                {
                    "source": "/",
                    "destination": "/introduction",
                    "permanent": True,
                },
                {
                    "source": "/old-guide",
                    "destination": "/guides/setup",
                    "permanent": True,
                },
                {
                    "source": "/external",
                    "destination": "https://example.com/reference",
                    "permanent": False,
                },
            ],
        }))

        (self.source / "index.mdx").write_text(
            '<Card href="/introduction">Start</Card>\n'
            '[Setup](/guides/setup?mode=fast)\n'
        )
        (self.source / "introduction.mdx").write_text(
            '[Setup](/guides/setup#next)\n'
        )

        guides = self.source / "guides"
        guides.mkdir()
        (guides / "setup.mdx").write_text("# Setup\n")
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
        (self.source / "favicon.ico").write_bytes(b"icon")
        (self.source / "style.css").write_text("body {}\n")
        (self.source / "AGENTS.md").write_text("not published\n")
        (self.source / ".atlas-analysis.json").write_text("{}\n")

    def tearDown(self):
        self.temp.cleanup()

    def publish(self):
        publish(
            source_docs=self.source,
            product_key="card",
            product_label="Calendar Card",
            product_icon="calendar-days",
            release_tag="v1.2.3",
            publish_shared_assets=True,
            repo_root=self.root,
        )

    def test_publish_rebuilds_config_from_template_and_adds_product(self):
        self.publish()

        config = json.loads((self.root / "docs.json").read_text())
        tab_names = [tab["tab"] for tab in config["navigation"]["tabs"]]

        self.assertEqual(["About", "Calendar Card"], tab_names)
        card_tab = config["navigation"]["tabs"][1]
        self.assertEqual("calendar-days", card_tab["icon"])
        self.assertEqual(["card/index"], card_tab["groups"][0]["pages"])
        self.assertEqual(
            ["card/introduction", "card/guides/setup"],
            card_tab["groups"][1]["pages"],
        )

        self.assertFalse(any(tab["tab"] == "Stale" for tab in config["navigation"]["tabs"]))
        self.assertFalse(any(r["source"] == "/stale" for r in config["redirects"]))

    def test_authored_redirects_are_preserved_and_win_source_collisions(self):
        self.publish()
        redirects = json.loads((self.root / "docs.json").read_text())["redirects"]

        self.assertIn(self.manual_alias, redirects)
        self.assertIn(self.manual_collision, redirects)
        self.assertIn(
            {
                "source": "/keep",
                "destination": "/somewhere-else",
                "permanent": True,
            },
            redirects,
        )
        self.assertEqual(
            1,
            sum(1 for redirect in redirects if redirect["source"] == "/introduction"),
        )
        self.assertNotIn(
            {
                "source": "/introduction",
                "destination": "/card/introduction",
                "permanent": True,
            },
            redirects,
        )

    def test_source_redirects_are_translated_without_replacing_site_root(self):
        self.publish()
        redirects = json.loads((self.root / "docs.json").read_text())["redirects"]

        self.assertIn(
            {
                "source": "/old-guide",
                "destination": "/card/guides/setup",
                "permanent": True,
            },
            redirects,
        )
        self.assertIn(
            {
                "source": "/card/old-guide",
                "destination": "/card/guides/setup",
                "permanent": True,
            },
            redirects,
        )
        self.assertIn(
            {
                "source": "/external",
                "destination": "https://example.com/reference",
                "permanent": False,
            },
            redirects,
        )
        self.assertIn(
            {
                "source": "/card/external",
                "destination": "https://example.com/reference",
                "permanent": False,
            },
            redirects,
        )
        self.assertFalse(any(r["source"] == "/" for r in redirects))
        self.assertFalse(any(r["source"] == "/card" for r in redirects))

    def test_links_and_root_only_exclusions_are_handled_correctly(self):
        self.publish()

        index = (self.root / "card" / "index.mdx").read_text()
        intro = (self.root / "card" / "introduction.mdx").read_text()
        self.assertIn('href="/card/introduction"', index)
        self.assertIn("](/card/guides/setup?mode=fast)", index)
        self.assertIn("](/card/guides/setup#next)", intro)

        self.assertFalse((self.root / "card" / "images").exists())
        self.assertFalse((self.root / "card" / "logo").exists())
        self.assertFalse((self.root / "card" / "AGENTS.md").exists())
        self.assertTrue((self.root / "card" / "guides" / "images" / "step.png").exists())
        self.assertTrue((self.root / "card" / "guides" / "logo" / "mark.svg").exists())

        self.assertTrue((self.root / "images" / "logo.png").exists())
        self.assertEqual(
            "v1.2.3\n",
            (self.root / ".sync" / "card-release").read_text(),
        )

    def test_existing_product_fragments_are_composed_with_current_product(self):
        sync_dir = self.root / ".sync"
        sync_dir.mkdir()
        (sync_dir / "import-config.json").write_text(json.dumps({
            "product_key": "import",
            "tab": {
                "tab": "Calendar Import",
                "icon": "sparkles",
                "groups": [
                    {"group": "Get Started", "pages": ["import/index"]}
                ],
            },
            "redirects": [
                {
                    "source": "/import-old",
                    "destination": "/import/index",
                    "permanent": True,
                }
            ],
        }))

        self.publish()
        config = json.loads((self.root / "docs.json").read_text())

        tab_names = [tab["tab"] for tab in config["navigation"]["tabs"]]
        self.assertEqual(["About", "Calendar Card", "Calendar Import"], tab_names)
        self.assertIn(
            {
                "source": "/import-old",
                "destination": "/import/index",
                "permanent": True,
            },
            config["redirects"],
        )

    def test_publish_is_deterministic_when_repeated_for_same_release(self):
        self.publish()
        first_config = (self.root / "docs.json").read_text()
        first_fragment = (self.root / ".sync" / "card-config.json").read_text()
        first_index = (self.root / "card" / "index.mdx").read_text()

        self.publish()

        self.assertEqual(first_config, (self.root / "docs.json").read_text())
        self.assertEqual(first_fragment, (self.root / ".sync" / "card-config.json").read_text())
        self.assertEqual(first_index, (self.root / "card" / "index.mdx").read_text())


if __name__ == "__main__":
    unittest.main()
