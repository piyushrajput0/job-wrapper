#!/usr/bin/env python3
"""Build "Job Wrapper.app" - a double-clickable macOS application.

    uv run python scripts/build_app.py

Produces dist/Job Wrapper.app. The Playwright browser is deliberately NOT bundled (it is ~150MB
and updates independently); the app checks for it and tells the user how to install it.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "jobwrapper"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
APP_NAME = "Job Wrapper"


def make_icns() -> Path | None:
    """Render the icon at every size macOS wants and pack it into an .icns."""
    if platform.system() != "Darwin" or not shutil.which("iconutil"):
        return None
    iconset = BUILD / f"{APP_NAME}.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    sizes = [16, 32, 64, 128, 256, 512, 1024]
    page_html = BUILD / "icon.html"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for size in sizes:
            radius, font = round(size * 0.22), round(size * 0.40)
            page_html.write_text(
                f"""<html><body style="margin:0"><div style="width:{size}px;height:{size}px;
                background:linear-gradient(135deg,#5b8cff,#9d6bff);border-radius:{radius}px;
                display:flex;align-items:center;justify-content:center;font-family:Helvetica;
                color:#fff;font-weight:800;font-size:{font}px;letter-spacing:-{max(1, size // 40)}px"
                >JW</div></body></html>""")
            page = browser.new_page(viewport={"width": size, "height": size})
            page.goto(page_html.as_uri())
            page.screenshot(path=str(iconset / f"icon_{size}x{size}.png"))
            if size <= 512:                       # retina variants
                page.close()
                page = browser.new_page(viewport={"width": size, "height": size},
                                        device_scale_factor=2)
                page.goto(page_html.as_uri())
                page.screenshot(path=str(iconset / f"icon_{size}x{size}@2x.png"))
            page.close()
        browser.close()

    icns = BUILD / f"{APP_NAME}.icns"
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)
    print(f"  icon: {icns.relative_to(ROOT)}")
    return icns


def build() -> int:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is missing. Run: uv sync --extra desktop")
        return 1

    icns = make_icns()
    separator = ";" if platform.system() == "Windows" else ":"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--windowed",                       # no terminal window
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        # the knowledge base, templates and web UI are data, not code - they must come along
        "--add-data", f"{PKG / 'data'}{separator}jobwrapper/data",
        "--add-data", f"{PKG / 'templates'}{separator}jobwrapper/templates",
        "--add-data", f"{PKG / 'server' / 'web'}{separator}jobwrapper/server/web",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.protocols.http.h11_impl",
        "--hidden-import", "uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import", "uvicorn.lifespan.on",
        "--collect-submodules", "jobwrapper",
        "--osx-bundle-identifier", "com.jobwrapper.app",
    ]
    if icns:
        args += ["--icon", str(icns)]
    args.append(str(ROOT / "scripts" / "app_entry.py"))

    print(f"building {APP_NAME}.app ...")
    result = subprocess.run(args, cwd=ROOT)
    if result.returncode != 0:
        return result.returncode

    bundle = DIST / f"{APP_NAME}.app"
    print(f"\n  {bundle}")
    if bundle.exists():
        size = sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file())
        print(f"  {size / 1_000_000:.0f} MB")
        print(f"\nInstall it:  mv '{bundle}' /Applications/")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
