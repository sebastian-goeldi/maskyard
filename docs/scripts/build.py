"""Build and validate the two documentation locales."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryFile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SOURCE = DOCS / "source"
STAGED = DOCS / "source-built"
SITE = DOCS / "site"
VERSION_SITE = DOCS / "_build" / "versioned-site"
VERSION_BRANCH = "gh-pages"


class LocaleLinks(HTMLParser):
    """Collect generated links between the two locale builds."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and "data-locale-link" in attributes:
            href = attributes.get("href")
            if not href:
                raise ValueError("Missing locale link URL")
            self.links.append(href)


def locale_root(locale: str, version: str | None) -> Path:
    if version is None:
        return SITE / locale
    return VERSION_SITE / locale / version


def build(version: str | None = None) -> None:
    guides = {
        locale: {
            path.relative_to(SOURCE / locale)
            for path in (SOURCE / locale).rglob("*.md")
            if path.relative_to(SOURCE / locale).parts[0] != "reference"
        }
        for locale in ("en", "zh")
    }
    if guides["en"] != guides["zh"]:
        message = f"Unpaired documentation pages: {sorted(guides['en'] ^ guides['zh'])}"
        raise SystemExit(message)

    for locale, other in (("en", "zh"), ("zh", "en")):
        current_root = locale_root(locale, version)
        other_root = locale_root(other, version)
        staged = STAGED / locale
        if staged.exists():
            shutil.rmtree(staged)
        shutil.copytree(SOURCE / locale, staged)
        shutil.copytree(DOCS / "assets", staged / "assets")
        shutil.copy2(ROOT / "logo.png", staged / "assets" / "logo.png")

        for path in staged.rglob("*.md"):
            page = path.relative_to(staged)
            directory = page.parent if page.name == "index.md" else page.with_suffix("")
            counterpart = (
                Path("reference") if page.parts[0] == "reference" else directory
            )
            # Header links are emitted by the template, relative to the HTML page.
            alternate_href = os.path.relpath(
                other_root / counterpart, current_root / directory
            ).replace(os.sep, "/")
            content = path.read_text(encoding="utf-8")
            content = content.replace(
                'src="../../../logo.png"', 'src="assets/logo.png"'
            )
            content = content.replace("](../../../assets/", "](../assets/")
            if locale == "zh" and page == Path("reference/index.md"):
                content += f"\n[查看英文 API 参考]({alternate_href}/)\n"
            alternate_meta = f"alternate_href: {json.dumps(alternate_href + '/')}\n"
            if content.startswith("---\n"):
                content = f"---\n{alternate_meta}{content[4:]}"
            else:
                content = f"---\n{alternate_meta}---\n\n{content}"
            path.write_text(content, encoding="utf-8")

        config = str(DOCS / f"zensical.{locale}.toml")
        if version:
            deploy_locale(config, locale, version)
        else:
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "zensical", "build", "--clean", "-f", config],
                cwd=ROOT,
                check=True,
            )

    if version:
        if VERSION_SITE.exists():
            shutil.rmtree(VERSION_SITE)
        with TemporaryFile() as archive:
            subprocess.run(  # noqa: S603
                ["git", "archive", "--format=zip", VERSION_BRANCH],  # noqa: S607
                cwd=ROOT,
                stdout=archive,
                check=True,
            )
            with ZipFile(archive) as site_archive:
                site_archive.extractall(VERSION_SITE)

    else:
        shutil.copy2(DOCS / "index.html", SITE / "index.html")

    for locale in ("en", "zh"):
        current_root = locale_root(locale, version)
        for page in (SOURCE / locale).rglob("*.md"):
            relative = page.relative_to(SOURCE / locale)
            output = current_root / relative
            if output.name != "index.md":
                output = output.with_suffix("") / "index.md"
            output = output.with_suffix(".html")
            parser = LocaleLinks()
            parser.feed(output.read_text(encoding="utf-8"))
            if not parser.links or any(
                not (output.parent / href / "index.html").is_file()
                for href in parser.links
            ):
                raise SystemExit(f"Broken or missing language switch in {output}")


def deploy_locale(config: str, locale: str, version: str) -> None:
    mike = Path(sys.executable).with_name("mike")
    if os.name == "nt":
        mike = mike.with_suffix(".exe")
    common_options = [
        "-F",
        config,
        "--branch",
        VERSION_BRANCH,
        "--ignore-remote-status",
    ]
    options = [*common_options, "--deploy-prefix", locale]
    subprocess.run(  # noqa: S603
        [mike, "deploy", *options, "--alias-type", "copy", version],
        cwd=ROOT,
        check=True,
    )
    catalog = subprocess.check_output(  # noqa: S603
        [mike, "list", *options, "--json"], cwd=ROOT
    )
    releases = [
        entry
        for entry in json.loads(catalog)
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", entry["version"])
    ]
    default = "dev"
    if releases:
        latest = max(
            releases, key=lambda entry: tuple(map(int, entry["version"].split(".")))
        )
        if "latest" not in latest["aliases"]:
            subprocess.run(  # noqa: S603
                [
                    mike,
                    "alias",
                    *options,
                    "--update-aliases",
                    "--alias-type",
                    "copy",
                    latest["version"],
                    "latest",
                ],
                cwd=ROOT,
                check=True,
            )
        default = "latest"
    subprocess.run([mike, "set-default", *options, default], cwd=ROOT, check=True)  # noqa: S603
    if locale == "en":
        subprocess.run(  # noqa: S603
            [
                mike,
                "set-default",
                *common_options,
                "--allow-undefined",
                f"{locale}/{default}",
            ],
            cwd=ROOT,
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Store dev or a release (X.Y.Z) with Mike")
    args = parser.parse_args()
    if args.version and not re.fullmatch(
        r"dev|(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}", args.version
    ):
        parser.error("--version must be dev or X.Y.Z")
    build(args.version)
