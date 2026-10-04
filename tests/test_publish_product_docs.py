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

        (self.root / "docs.json").write_text(json.dumps({
            "navigation": {
                "tabs": [
                    {"tab": "Calendar Card", "icon": "old", "groups": []}
                ]
            },
            "redirects": [
                {
                    "source": "/keep",
                    "destination": "/somewhere-else",
                    "permanent": True,
                },
                {
                    "source": "/stale",
                    "destination": "/card/stale",
                    "permanent": True,
                },
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
            }
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

        images = self.source / "images"
        images.mkdir()
        (images / "logo.png").write_bytes(b"image")
        (self.source / "favicon.ico").write_bytes(b"icon")
        (self.source / "style.css").write_text("body {}\n")
        (self.source / "AGENTS.md").write_text("not published\n")
        (self.source / ".atlas-analysis.json").write_text("{}\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_publish_generates_prefixed_navigation_redirects_and_links(self):
        publish(
            source_docs=self.source,
            product_key="card",
            product_label="Calendar Card",
            product_icon="calendar-days",
            release_tag="v1.2.3",
            publish_shared_assets=True,
            repo_root=self.root,
        )

        config = json.loads((self.root / "docs.json").read_text())
        tab = config["navigation"]["tabs"][0]

        self.assertEqual("calendar-days", tab["icon"])
        self.assertEqual(["card/index"], tab["groups"][0]["pages"])
        self.assertEqual(
            ["card/introduction", "card/guides/setup"],
            tab["groups"][1]["pages"],
        )

        self.assertIn(
            {
                "source": "/introduction",
                "destination": "/card/introduction",
                "permanent": True,
            },
            config["redirects"],
        )
        self.assertIn(
            {
                "source": "/guides/setup",
                "destination": "/card/guides/setup",
                "permanent": True,
            },
            config["redirects"],
        )
        self.assertNotIn(
            {
                "source": "/index",
                "destination": "/card/index",
                "permanent": True,
            },
            config["redirects"],
        )
        self.assertIn(
            {
                "source": "/keep",
                "destination": "/somewhere-else",
                "permanent": True,
            },
            config["redirects"],
        )
        self.assertFalse(any(r["source"] == "/stale" for r in config["redirects"]))

        index = (self.root / "card" / "index.mdx").read_text()
        intro = (self.root / "card" / "introduction.mdx").read_text()
        self.assertIn('href="/card/introduction"', index)
        self.assertIn("](/card/guides/setup?mode=fast)", index)
        self.assertIn("](/card/guides/setup#next)", intro)

        self.assertFalse((self.root / "card" / "images").exists())
        self.assertFalse((self.root / "card" / "AGENTS.md").exists())
        self.assertTrue((self.root / "images" / "logo.png").exists())
        self.assertEqual("v1.2.3\n", (self.root / ".sync" / "card-release").read_text())

    def test_publish_is_deterministic_when_repeated_for_same_release(self):
        kwargs = dict(
            source_docs=self.source,
            product_key="card",
            product_label="Calendar Card",
            product_icon="calendar-days",
            release_tag="v1.2.3",
            publish_shared_assets=True,
            repo_root=self.root,
        )

        publish(**kwargs)
        first_config = (self.root / "docs.json").read_text()
        first_index = (self.root / "card" / "index.mdx").read_text()

        publish(**kwargs)

        self.assertEqual(first_config, (self.root / "docs.json").read_text())
        self.assertEqual(first_index, (self.root / "card" / "index.mdx").read_text())


if __name__ == "__main__":
    unittest.main()
