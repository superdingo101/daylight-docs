#!/usr/bin/env python3
"""Publish released product docs into the combined Daylight Mintlify site."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
from urllib.parse import urlsplit


ROOT_ONLY_EXCLUDES = {
    "docs.json",
    "AGENTS.md",
    ".mintignore",
    ".atlas-analysis.json",
    "style.css",
    "favicon.ico",
}

NAVIGATION_PATH_FIELDS = {"pages", "root", "href"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-docs", required=True, type=pathlib.Path)
    parser.add_argument("--product-key", required=True)
    parser.add_argument("--product-label", required=True)
    parser.add_argument("--product-icon", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--publish-shared-assets", action="store_true")
    parser.add_argument("--preserve-legacy-root-urls", action="store_true")
    return parser.parse_args()


def validate_product_key(product_key: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", product_key):
        raise ValueError(f"Invalid product key: {product_key!r}")


def is_external_target(value: str) -> bool:
    if value.startswith(("#", "//")):
        return True
    parsed = urlsplit(value)
    return bool(parsed.scheme or parsed.netloc)


def namespace_navigation_path(value: str, product_key: str) -> str:
    if not value or is_external_target(value):
        return value

    match = re.match(r"(?P<path>[^?#]*)(?P<suffix>[?#].*)?$", value)
    if not match:
        return value

    path_part = match.group("path")
    suffix = match.group("suffix") or ""
    leading_slash = path_part.startswith("/")
    relative = path_part.lstrip("/")

    if not relative:
        namespaced = product_key
    elif relative == product_key or relative.startswith(f"{product_key}/"):
        return value
    else:
        namespaced = f"{product_key}/{relative}"

    if leading_slash:
        namespaced = f"/{namespaced}"
    return f"{namespaced}{suffix}"


def prefix_navigation(value, product_key: str, parent_key: str | None = None):
    if isinstance(value, str):
        if parent_key in NAVIGATION_PATH_FIELDS:
            return namespace_navigation_path(value, product_key)
        return value

    if isinstance(value, list):
        return [prefix_navigation(item, product_key, parent_key) for item in value]

    if not isinstance(value, dict):
        return value

    return {
        key: prefix_navigation(child, product_key, key)
        for key, child in value.items()
    }


def discover_routes(product_root: pathlib.Path) -> set[str]:
    return {
        str(path.relative_to(product_root).with_suffix("")).replace("\\", "/")
        for path in product_root.rglob("*.mdx")
    }


def namespace_destination(destination: str, product_key: str) -> str:
    if not destination.startswith("/") or destination.startswith("//"):
        return destination
    if destination == "/":
        return f"/{product_key}"
    return f"/{product_key}{destination}"


def translated_source_redirects(
    source_config: dict,
    product_key: str,
    preserve_legacy_root_urls: bool,
) -> list[dict]:
    """Translate product-local redirects into the combined site namespace."""
    generated: list[dict] = []

    for redirect in source_config.get("redirects", []):
        if not isinstance(redirect, dict):
            continue

        source = redirect.get("source")
        destination = redirect.get("destination")
        if not isinstance(source, str) or not isinstance(destination, str):
            continue
        if not source.startswith("/") or source.startswith("//"):
            raise ValueError(f"Invalid product redirect source: {source!r}")

        # The old product site's root redirect must not replace the Daylight
        # landing page or the generated /<product>/index page.
        if source == "/":
            continue

        destination = namespace_destination(destination, product_key)

        namespaced = dict(redirect)
        namespaced["source"] = f"/{product_key}{source}"
        namespaced["destination"] = destination
        generated.append(namespaced)

        if preserve_legacy_root_urls:
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
    preserve_legacy_root_urls: bool,
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

    for redirect in translated_source_redirects(
        source_config,
        product_key,
        preserve_legacy_root_urls,
    ):
        redirects_by_source[redirect["source"]] = redirect

    # Current pages must never be shadowed by historical redirects.
    for route in sorted(routes):
        if route == "index":
            continue

        redirects_by_source.pop(f"/{product_key}/{route}", None)

        if preserve_legacy_root_urls:
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
    generated_tab_owners: dict[str, str] = {}
    generated_redirect_owners: dict[str, str] = {}

    for fragment_path in sorted(fragments_dir.glob("*-config.json")):
        fragment = json.loads(fragment_path.read_text())
        fragment_product_key = fragment.get("product_key")

        if not isinstance(fragment_product_key, str):
            raise ValueError(f"Invalid product fragment identity: {fragment_path}")
        validate_product_key(fragment_product_key)

        if fragment_path.name != f"{fragment_product_key}-config.json":
            raise ValueError(f"Invalid product fragment identity: {fragment_path}")

        tab = fragment.get("tab")
        if not isinstance(tab, dict) or not isinstance(tab.get("tab"), str):
            raise ValueError(f"Invalid product tab fragment: {fragment_path}")

        tab_name = tab["tab"]
        if tab_name in authored_tab_names:
            raise ValueError(
                f"Product tab {tab_name!r} conflicts with authored navigation"
            )
        if tab_name in generated_tab_owners:
            raise ValueError(
                f"Product tab {tab_name!r} conflicts between "
                f"{generated_tab_owners[tab_name]!r} and {fragment_product_key!r}"
            )

        tabs.append(tab)
        generated_tab_owners[tab_name] = fragment_product_key

        for redirect in fragment.get("redirects", []):
            if not isinstance(redirect, dict):
                raise ValueError(f"Invalid redirect in product fragment: {fragment_path}")

            source = redirect.get("source")
            if not isinstance(source, str):
                raise ValueError(f"Redirect without source in product fragment: {fragment_path}")

            # Authored Daylight redirects intentionally override product output.
            if source in authored_redirect_sources:
                continue

            if source in generated_redirect_owners:
                raise ValueError(
                    f"Redirect source {source!r} conflicts between "
                    f"{generated_redirect_owners[source]!r} and {fragment_product_key!r}"
                )

            redirects.append(redirect)
            generated_redirect_owners[source] = fragment_product_key

    output_path.write_text(json.dumps(root, indent=2) + "\n")


def reject_symlinks(source_docs: pathlib.Path) -> None:
    if source_docs.is_symlink():
        raise ValueError(f"Source docs path must not be a symlink: {source_docs}")

    for directory, dirnames, filenames in os.walk(source_docs, followlinks=False):
        for name in [*dirnames, *filenames]:
            path = pathlib.Path(directory) / name
            if path.is_symlink():
                raise ValueError(f"Source docs must not contain symlinks: {path}")


def root_only_ignore(source_docs: pathlib.Path):
    source_root = source_docs.resolve()

    def ignore(directory: str, _names: list[str]) -> set[str]:
        if pathlib.Path(directory).resolve() == source_root:
            return ROOT_ONLY_EXCLUDES
        return set()

    return ignore


def copy_product_docs(source_docs: pathlib.Path, product_root: pathlib.Path) -> None:
    reject_symlinks(source_docs)

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
    preserve_legacy_root_urls: bool,
    repo_root: pathlib.Path = pathlib.Path("."),
) -> None:
    validate_product_key(product_key)
    reject_symlinks(source_docs)

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

    source_config = json.loads(source_config_path.read_text())
    fragment = build_product_fragment(
        source_config,
        product_key,
        product_label,
        product_icon,
        routes,
        preserve_legacy_root_urls,
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
        preserve_legacy_root_urls=args.preserve_legacy_root_urls,
    )


if __name__ == "__main__":
    main()
