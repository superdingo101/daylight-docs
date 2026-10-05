#!/usr/bin/env python3
"""Publish released product docs into the combined Daylight Mintlify site."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
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
SHARED_ASSET_DIRECTORIES = ("images", "logo")
SHARED_ASSET_FILES = ("favicon.ico", "style.css")


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
    route_sources: dict[str, pathlib.Path] = {}

    for suffix in (".mdx", ".md"):
        for path in product_root.rglob(f"*{suffix}"):
            route = str(path.relative_to(product_root).with_suffix("")).replace("\\", "/")
            previous = route_sources.get(route)
            if previous is not None:
                raise ValueError(
                    f"Duplicate documentation route {route!r}: {previous} and {path}"
                )
            route_sources[route] = path

    return set(route_sources)


def normalized_local_route(value: str, product_key: str) -> str | None:
    if not value or is_external_target(value):
        return None

    parsed = urlsplit(value)
    relative = parsed.path.lstrip("/")
    if relative == product_key:
        relative = ""
    elif relative.startswith(f"{product_key}/"):
        relative = relative[len(product_key) + 1 :]

    if relative.endswith((".md", ".mdx")):
        relative = str(pathlib.PurePosixPath(relative).with_suffix(""))

    return relative or "index"


def referenced_navigation_routes(value, product_key: str, parent_key: str | None = None):
    if isinstance(value, str):
        if parent_key in NAVIGATION_PATH_FIELDS:
            route = normalized_local_route(value, product_key)
            if route is not None:
                yield route
        return

    if isinstance(value, list):
        for item in value:
            yield from referenced_navigation_routes(item, product_key, parent_key)
        return

    if not isinstance(value, dict):
        return

    for key, child in value.items():
        yield from referenced_navigation_routes(child, product_key, key)


def validate_ignored_routes_not_referenced(
    source_config: dict,
    product_key: str,
    ignored_routes: set[str],
) -> None:
    if not ignored_routes:
        return

    groups = source_config.get("navigation", {}).get("groups", [])
    for route in referenced_navigation_routes(groups, product_key):
        if route in ignored_routes:
            raise ValueError(
                f"Navigation references route excluded by .mintignore: {route!r}"
            )

    for redirect in source_config.get("redirects", []):
        if not isinstance(redirect, dict):
            continue
        destination = redirect.get("destination")
        if not isinstance(destination, str):
            continue
        route = normalized_local_route(destination, product_key)
        if route in ignored_routes:
            raise ValueError(
                f"Redirect destination is excluded by .mintignore: {route!r}"
            )


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


def validate_existing_fragment_product(
    fragments_dir: pathlib.Path,
    product_root: pathlib.Path,
    product_key: str,
) -> None:
    if not os.path.lexists(product_root):
        return
    if product_root.is_symlink() or not product_root.is_dir():
        raise ValueError(f"Product output path is not a managed directory: {product_root}")

    fragment_path = fragments_dir / f"{product_key}-config.json"
    release_marker = fragments_dir / f"{product_key}-release"
    if not fragment_path.is_file() or not release_marker.is_file():
        raise ValueError(
            f"Product key {product_key!r} collides with unmanaged or incomplete repository path: {product_root}"
        )

    fragment = json.loads(fragment_path.read_text())
    if fragment.get("product_key") != product_key:
        raise ValueError(f"Product output ownership mismatch: {product_root}")


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

        product_root = output_path.parent / fragment_product_key
        release_marker = fragments_dir / f"{fragment_product_key}-release"
        if product_root.is_symlink() or not product_root.is_dir() or not release_marker.is_file():
            raise ValueError(f"Stale or incomplete product fragment: {fragment_path}")

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


def mintignored_paths(source_docs: pathlib.Path) -> set[str]:
    ignore_file = source_docs / ".mintignore"
    if not ignore_file.is_file():
        return set()

    candidates = [
        path.relative_to(source_docs).as_posix()
        for path in source_docs.rglob("*")
    ]
    if not candidates:
        return set()

    with tempfile.TemporaryDirectory() as temp_dir:
        git_dir = pathlib.Path(temp_dir) / "git"
        subprocess.run(
            ["git", "init", "--bare", "--quiet", str(git_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        env = os.environ.copy()
        env["GIT_DIR"] = str(git_dir)
        env["GIT_WORK_TREE"] = str(source_docs.resolve())
        payload = b"\0".join(os.fsencode(path) for path in candidates) + b"\0"
        result = subprocess.run(
            [
                "git",
                "-c",
                f"core.excludesFile={ignore_file.resolve()}",
                "check-ignore",
                "--no-index",
                "-z",
                "--stdin",
            ],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

    if result.returncode not in (0, 1):
        raise RuntimeError(
            f"Failed to evaluate .mintignore: {result.stderr.decode(errors='replace')}"
        )

    return {
        os.fsdecode(item)
        for item in result.stdout.split(b"\0")
        if item
    }


def copy_ignore(source_docs: pathlib.Path, ignored_paths: set[str]):
    source_root = source_docs.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        directory_path = pathlib.Path(directory).resolve()
        relative_dir = directory_path.relative_to(source_root)
        ignored_names: set[str] = set()

        for name in names:
            relative = (relative_dir / name).as_posix()
            if relative.startswith("./"):
                relative = relative[2:]

            if relative_dir == pathlib.Path(".") and name in ROOT_ONLY_EXCLUDES:
                ignored_names.add(name)
            elif relative in ignored_paths:
                ignored_names.add(name)

        return ignored_names

    return ignore


def copy_product_docs(
    source_docs: pathlib.Path,
    product_root: pathlib.Path,
    ignored_paths: set[str],
) -> None:
    if product_root.exists():
        shutil.rmtree(product_root)

    shutil.copytree(
        source_docs,
        product_root,
        ignore=copy_ignore(source_docs, ignored_paths),
    )


def copy_shared_assets(
    source_docs: pathlib.Path,
    repo_root: pathlib.Path,
    ignored_paths: set[str],
) -> None:
    ignore_callback = copy_ignore(source_docs, ignored_paths)

    images_source = source_docs / "images"
    if (
        "images" in ignored_paths
        or not images_source.is_dir()
    ):
        raise ValueError("Shared asset source is missing published docs/images")

    for filename in SHARED_ASSET_FILES:
        source = source_docs / filename
        if filename in ignored_paths or not source.is_file():
            raise ValueError(f"Shared asset source is missing published {filename}")

    for dirname in SHARED_ASSET_DIRECTORIES:
        source = source_docs / dirname
        target = repo_root / dirname
        if target.exists():
            shutil.rmtree(target)

        if dirname in ignored_paths or not source.exists():
            continue
        if not source.is_dir():
            raise ValueError(f"Shared asset source is not a directory: {source}")

        shutil.copytree(source, target, ignore=ignore_callback)

    for filename in SHARED_ASSET_FILES:
        source = source_docs / filename
        target = repo_root / filename
        if target.exists():
            target.unlink()
        shutil.copy2(source, target)


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

    source_config = json.loads(source_config_path.read_text())
    source_routes = discover_routes(source_docs)
    ignored_paths = mintignored_paths(source_docs)

    sync_dir = repo_root / ".sync"
    sync_dir.mkdir(exist_ok=True)
    product_root = repo_root / product_key
    validate_existing_fragment_product(sync_dir, product_root, product_key)

    copy_product_docs(source_docs, product_root, ignored_paths)

    routes = discover_routes(product_root)
    if "index" not in routes:
        raise ValueError("Product docs must contain a published index.mdx or index.md")

    ignored_routes = source_routes - routes
    validate_ignored_routes_not_referenced(
        source_config,
        product_key,
        ignored_routes,
    )

    fragment = build_product_fragment(
        source_config,
        product_key,
        product_label,
        product_icon,
        routes,
        preserve_legacy_root_urls,
    )

    fragment_path = sync_dir / f"{product_key}-config.json"
    fragment_path.write_text(json.dumps(fragment, indent=2) + "\n")
    (sync_dir / f"{product_key}-release").write_text(f"{release_tag}\n")

    compose_site_config(
        template_path,
        repo_root / "docs.json",
        sync_dir,
    )

    if publish_shared_assets:
        copy_shared_assets(source_docs, repo_root, ignored_paths)


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
