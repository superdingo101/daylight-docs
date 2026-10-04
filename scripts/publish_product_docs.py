#!/usr/bin/env python3
"""Publish released product docs into the combined Daylight Mintlify site."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil


ROOT_ONLY_EXCLUDES = {
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


def namespace_destination(destination: str, product_key: str) -> str:
    if not destination.startswith("/"):
        return destination
    if destination == "/":
        return f"/{product_key}"
    return f"/{product_key}{destination}"


def translated_source_redirects(source_config: dict, product_key: str) -> list[dict]:
    """Translate product-local redirects for both legacy and namespaced URLs."""
    generated: list[dict] = []

    for redirect in source_config.get("redirects", []):
        if not isinstance(redirect, dict):
            continue

        source = redirect.get("source")
        destination = redirect.get("destination")
        if not isinstance(source, str) or not isinstance(destination, str):
            continue

        # The old product site's root redirect must not replace the Daylight
        # landing page or the generated /<product>/index page.
        if source == "/":
            continue

        destination = namespace_destination(destination, product_key)

        namespaced = dict(redirect)
        namespaced["source"] = f"/{product_key}{source}"
        namespaced["destination"] = destination
        generated.append(namespaced)

        legacy = dict(redirect)
        legacy["source"] = source
        legacy["destination"] = destination
        generated.append(legacy)

    return generated


def build_product_fragment(
    source_config: dict,
    product_key: str,
    product_label: str,
    product_icon: str,
    routes: set[str],
) -> dict:
    groups = source_config.get("navigation", {}).get("groups")
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

    redirects_by_source: dict[str, dict] = {}

    for redirect in translated_source_redirects(source_config, product_key):
        redirects_by_source[redirect["source"]] = redirect

    # Current routes take precedence over historical product redirects.
    for route in sorted(routes):
        if route == "index":
            continue
        redirects_by_source[f"/{route}"] = {
            "source": f"/{route}",
            "destination": f"/{product_key}/{route}",
            "permanent": True,
        }

    return {
        "product_key": product_key,
        "tab": {
            "tab": product_label,
            "icon": product_icon,
            "groups": generated_groups,
        },
        "redirects": list(redirects_by_source.values()),
    }


def compose_site_config(
    template_path: pathlib.Path,
    output_path: pathlib.Path,
    fragments_dir: pathlib.Path,
) -> None:
    root = json.loads(template_path.read_text())
    navigation = root.setdefault("navigation", {})
    tabs = navigation.setdefault("tabs", [])
    redirects = root.setdefault("redirects", [])

    authored_tab_names = {
        item.get("tab")
        for item in tabs
        if isinstance(item, dict) and isinstance(item.get("tab"), str)
    }
    authored_redirect_sources = {
        item.get("source")
        for item in redirects
        if isinstance(item, dict) and isinstance(item.get("source"), str)
    }

    for fragment_path in sorted(fragments_dir.glob("*-config.json")):
        fragment = json.loads(fragment_path.read_text())

        tab = fragment.get("tab")
        if not isinstance(tab, dict) or not isinstance(tab.get("tab"), str):
            raise ValueError(f"Invalid product tab fragment: {fragment_path}")
        if tab["tab"] not in authored_tab_names:
            tabs.append(tab)

        for redirect in fragment.get("redirects", []):
            if not isinstance(redirect, dict):
                raise ValueError(f"Invalid redirect in product fragment: {fragment_path}")
            source = redirect.get("source")
            if not isinstance(source, str):
                raise ValueError(f"Redirect without source in product fragment: {fragment_path}")
            if source in authored_redirect_sources:
                continue
            redirects.append(redirect)
            authored_redirect_sources.add(source)

    output_path.write_text(json.dumps(root, indent=2) + "\n")


def root_only_ignore(source_docs: pathlib.Path):
    source_root = source_docs.resolve()

    def ignore(directory: str, _names: list[str]) -> set[str]:
        if pathlib.Path(directory).resolve() == source_root:
            return ROOT_ONLY_EXCLUDES
        return set()

    return ignore


def copy_product_docs(source_docs: pathlib.Path, product_root: pathlib.Path) -> None:
    if product_root.exists():
        shutil.rmtree(product_root)

    shutil.copytree(
        source_docs,
        product_root,
        ignore=root_only_ignore(source_docs),
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
    source_config_path = source_docs / "docs.json"
    if not source_config_path.is_file():
        raise ValueError("Source docs directory is missing docs.json")

    template_path = repo_root / "docs.template.json"
    if not template_path.is_file():
        raise ValueError("Publishing repository is missing docs.template.json")

    product_root = repo_root / product_key
    copy_product_docs(source_docs, product_root)

    routes = discover_routes(product_root)
    if "index" not in routes:
        raise ValueError("Product docs must contain index.mdx")

    rewrite_product_links(product_root, product_key, routes)

    source_config = json.loads(source_config_path.read_text())
    fragment = build_product_fragment(
        source_config,
        product_key,
        product_label,
        product_icon,
        routes,
    )

    sync_dir = repo_root / ".sync"
    sync_dir.mkdir(exist_ok=True)
    fragment_path = sync_dir / f"{product_key}-config.json"
    fragment_path.write_text(json.dumps(fragment, indent=2) + "\n")

    compose_site_config(
        template_path,
        repo_root / "docs.json",
        sync_dir,
    )

    if publish_shared_assets:
        copy_shared_assets(source_docs, repo_root)

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
