#!/usr/bin/env python3
"""Publish one released product's docs into the combined Daylight Mintlify site."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil


PRODUCT_EXCLUDES = {
    "docs.json",
    "AGENTS.md",
    ".mintignore",
    ".atlas-analysis.json",
    "style.css",
    "favicon.ico",
    "images",
    "logo",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-docs", required=True, type=pathlib.Path)
    parser.add_argument("--product-key", required=True)
    parser.add_argument("--product-label", required=True)
    parser.add_argument("--product-icon", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--publish-shared-assets", action="store_true")
    return parser.parse_args()


def prefix_navigation(value, product_key: str):
    if isinstance(value, list):
        return [prefix_navigation(item, product_key) for item in value]
    if not isinstance(value, dict):
        return value

    result = {}
    for key, child in value.items():
        if key == "pages" and isinstance(child, list):
            result[key] = [
                f"{product_key}/{item.lstrip('/')}"
                if isinstance(item, str)
                else prefix_navigation(item, product_key)
                for item in child
            ]
        else:
            result[key] = prefix_navigation(child, product_key)
    return result


def discover_routes(product_root: pathlib.Path) -> set[str]:
    return {
        str(path.relative_to(product_root).with_suffix("")).replace("\\", "/")
        for path in product_root.rglob("*.mdx")
    }


def rewrite_product_links(product_root: pathlib.Path, product_key: str, routes: set[str]) -> None:
    targets = sorted(routes, key=len, reverse=True)

    for mdx_path in product_root.rglob("*.mdx"):
        text = mdx_path.read_text()

        for target in targets:
            escaped = re.escape(target)
            text = re.sub(
                rf'href=(["\'])/{escaped}(?=(?:[#?][^"\']*)?["\'])',
                rf'href=\1/{product_key}/{target}',
                text,
            )
            text = re.sub(
                rf'\]\(/{escaped}(?=(?:[#?][^)]*)?\))',
                rf'](/{product_key}/{target}',
                text,
            )

        mdx_path.write_text(text)


def update_site_config(
    root_config_path: pathlib.Path,
    source_config_path: pathlib.Path,
    product_key: str,
    product_label: str,
    product_icon: str,
    routes: set[str],
) -> None:
    root = json.loads(root_config_path.read_text())
    source = json.loads(source_config_path.read_text())

    groups = source.get("navigation", {}).get("groups")
    if not isinstance(groups, list):
        raise ValueError("Product docs.json must contain navigation.groups")

    generated_groups = [
        {
            "group": "Overview",
            "icon": "house",
            "pages": [f"{product_key}/index"],
        },
        *prefix_navigation(groups, product_key),
    ]

    navigation = root.setdefault("navigation", {})
    tabs = navigation.setdefault("tabs", [])
    tab = next((item for item in tabs if item.get("tab") == product_label), None)
    if tab is None:
        tabs.append(
            {
                "tab": product_label,
                "icon": product_icon,
                "groups": generated_groups,
            }
        )
    else:
        tab["icon"] = product_icon
        tab["groups"] = generated_groups
        tab.pop("pages", None)

    redirects = [
        item
        for item in root.get("redirects", [])
        if not str(item.get("destination", "")).startswith(f"/{product_key}/")
    ]
    redirects.extend(
        {
            "source": f"/{route}",
            "destination": f"/{product_key}/{route}",
            "permanent": True,
        }
        for route in sorted(routes)
        if route != "index"
    )
    root["redirects"] = redirects

    root_config_path.write_text(json.dumps(root, indent=2) + "\n")


def copy_product_docs(source_docs: pathlib.Path, product_root: pathlib.Path) -> None:
    if product_root.exists():
        shutil.rmtree(product_root)

    shutil.copytree(
        source_docs,
        product_root,
        ignore=shutil.ignore_patterns(*PRODUCT_EXCLUDES),
    )


def copy_shared_assets(source_docs: pathlib.Path, repo_root: pathlib.Path) -> None:
    source_images = source_docs / "images"
    if not source_images.is_dir():
        raise ValueError("Shared asset source is missing docs/images")

    target_images = repo_root / "images"
    if target_images.exists():
        shutil.rmtree(target_images)
    shutil.copytree(source_images, target_images)

    for filename in ("favicon.ico", "style.css"):
        source = source_docs / filename
        if not source.is_file():
            raise ValueError(f"Shared asset source is missing {filename}")
        shutil.copy2(source, repo_root / filename)


def publish(
    source_docs: pathlib.Path,
    product_key: str,
    product_label: str,
    product_icon: str,
    release_tag: str,
    publish_shared_assets: bool,
    repo_root: pathlib.Path = pathlib.Path("."),
) -> None:
    source_config = source_docs / "docs.json"
    if not source_config.is_file():
        raise ValueError("Source docs directory is missing docs.json")

    root_config = repo_root / "docs.json"
    if not root_config.is_file():
        raise ValueError("Publishing repository is missing docs.json")

    product_root = repo_root / product_key
    copy_product_docs(source_docs, product_root)

    routes = discover_routes(product_root)
    if "index" not in routes:
        raise ValueError("Product docs must contain index.mdx")

    rewrite_product_links(product_root, product_key, routes)
    update_site_config(
        root_config,
        source_config,
        product_key,
        product_label,
        product_icon,
        routes,
    )

    if publish_shared_assets:
        copy_shared_assets(source_docs, repo_root)

    sync_dir = repo_root / ".sync"
    sync_dir.mkdir(exist_ok=True)
    (sync_dir / f"{product_key}-release").write_text(f"{release_tag}\n")


def main() -> None:
    args = parse_args()
    publish(
        source_docs=args.source_docs,
        product_key=args.product_key,
        product_label=args.product_label,
        product_icon=args.product_icon,
        release_tag=args.release_tag,
        publish_shared_assets=args.publish_shared_assets,
    )


if __name__ == "__main__":
    main()
