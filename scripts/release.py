from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
PACKAGING_DIR = ROOT_DIR / "packaging"
PYINSTALLER_CONFIG_DIR = ROOT_DIR / ".pyinstaller-cache"
MIN_MACOS_VERSION = "11.0"
SUPPORTED_MACOS_ARCHES = ("arm64", "x86_64")


def run(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd or ROOT_DIR, env=env, check=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_template(template_path: Path, output_path: Path, replacements: dict[str, str]) -> None:
    text = template_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")


def project_version() -> str:
    text = (ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if match is None:
        raise RuntimeError("pyproject.toml does not define [project].version")
    return match.group(1)


def normalize_arch(raw_arch: str) -> str:
    arch = raw_arch.lower()
    arch = arch.replace("aarch64", "arm64")
    arch = arch.replace("amd64", "x86_64")
    arch = arch.replace("x64", "x86_64")
    return arch


def discover_archives(out_dir: Path, version: str, prefix: str, suffix: str) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    pattern = f"{prefix}-{version}-macos-*{suffix}"
    for path in sorted(out_dir.glob(pattern)):
        arch = path.name.removeprefix(f"{prefix}-{version}-macos-").removesuffix(suffix)
        assets[arch] = path
    return assets


def release_asset_url(release_base_url: str, archive_path: Path) -> str:
    if not release_base_url:
        return ""
    return f"{release_base_url}/{archive_path.name}"


def render_cli_source(cli_archives: dict[str, Path], release_base_url: str) -> str:
    if not cli_archives:
        raise FileNotFoundError("missing CLI archives for Homebrew formula generation")
    if len(cli_archives) == 1:
        arch, archive_path = next(iter(cli_archives.items()))
        return (
            f'  url "{release_asset_url(release_base_url, archive_path)}"\n'
            f'  sha256 "{sha256_file(archive_path)}"\n'
            f'  # Built for macOS {arch}.'
        )

    blocks: list[str] = []
    if "arm64" in cli_archives:
        archive_path = cli_archives["arm64"]
        blocks.append(
            "\n".join(
                [
                    "  on_arm do",
                    f'    url "{release_asset_url(release_base_url, archive_path)}"',
                    f'    sha256 "{sha256_file(archive_path)}"',
                    "  end",
                ]
            )
        )
    if "x86_64" in cli_archives:
        archive_path = cli_archives["x86_64"]
        blocks.append(
            "\n".join(
                [
                    "  on_intel do",
                    f'    url "{release_asset_url(release_base_url, archive_path)}"',
                    f'    sha256 "{sha256_file(archive_path)}"',
                    "  end",
                ]
            )
        )
    if not blocks:
        raise RuntimeError("Homebrew formula generation requires at least one supported macOS architecture")
    return "\n\n".join(blocks)


def render_app_source(app_archives: dict[str, Path], release_base_url: str) -> str:
    if not app_archives:
        raise FileNotFoundError("missing app archives for Homebrew cask generation")
    if len(app_archives) == 1:
        _, archive_path = next(iter(app_archives.items()))
        return "\n".join(
            [
                f'  sha256 "{sha256_file(archive_path)}"',
                "",
                f'  url "{release_asset_url(release_base_url, archive_path)}"',
            ]
        )

    arch_entries: list[str] = []
    sha_entries: list[str] = []
    if "arm64" in app_archives:
        arch_entries.append('arm: "arm64"')
        sha_entries.append(f'arm: "{sha256_file(app_archives["arm64"])}"')
    if "x86_64" in app_archives:
        arch_entries.append('intel: "x86_64"')
        sha_entries.append(f'intel: "{sha256_file(app_archives["x86_64"])}"')
    if not arch_entries or not sha_entries:
        raise RuntimeError("Homebrew cask generation requires at least one supported macOS architecture")
    return "\n".join(
        [
            f"  arch {', '.join(arch_entries)}",
            f"  sha256 {', '.join(sha_entries)}",
            "",
            f'  url "{release_base_url}/msgflow-app-#{{version}}-macos-#{{arch}}.zip"',
        ]
    )


def clean_package_metadata() -> None:
    for egg_info_dir in (ROOT_DIR / "src").glob("*.egg-info"):
        shutil.rmtree(egg_info_dir, ignore_errors=True)


def refresh_package_metadata() -> None:
    clean_package_metadata()
    run([sys.executable, "-m", "pip", "install", "--no-deps", "-e", str(ROOT_DIR)])


def build_pyinstaller(spec_name: str, version: str) -> None:
    env = dict(os.environ)
    env["PYINSTALLER_CONFIG_DIR"] = str(PYINSTALLER_CONFIG_DIR)
    env["MSGFLOW_VERSION"] = version
    env.setdefault("MACOSX_DEPLOYMENT_TARGET", MIN_MACOS_VERSION)
    run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", str(PACKAGING_DIR / "pyinstaller" / spec_name)],
        env=env,
    )


def bundle_core_binary() -> None:
    app_bundle = DIST_DIR / "msgflow.app"
    core_binary = DIST_DIR / "msgflow-core" / "msgflow-core"
    target_binary = app_bundle / "Contents" / "MacOS" / "msgflow-core"
    if not app_bundle.exists():
        raise FileNotFoundError(f"missing app bundle: {app_bundle}")
    if not core_binary.exists():
        raise FileNotFoundError(f"missing core binary: {core_binary}")
    shutil.copy2(core_binary, target_binary)
    target_binary.chmod(0o755)


def verify_app_launches(app_bundle: Path, *, config_dir: Path | None = None) -> None:
    app_binary = app_bundle / "Contents" / "MacOS" / "msgflow-app"
    if not app_binary.exists():
        raise FileNotFoundError(f"missing app executable: {app_binary}")
    env = dict(os.environ)
    if config_dir is not None:
        env["MSGFLOW_CONFIG_DIR"] = str(config_dir)
    process = subprocess.Popen(
        [str(app_binary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        stdout, stderr = process.communicate(timeout=6)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        return
    raise RuntimeError(
        f"app exited during launch smoke test with code {process.returncode}\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def verify_app_archive_launches(app_zip: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="msgflow-app-smoke-") as temp_dir:
        run(["ditto", "-x", "-k", str(app_zip), temp_dir])
        verify_app_launches(Path(temp_dir) / "msgflow.app", config_dir=Path(temp_dir) / "config")


def find_codesigning_identity() -> str | None:
    configured_identity = os.environ.get("APPLE_SIGNING_IDENTITY")
    if configured_identity:
        return configured_identity
    result = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
        check=False,
    )
    for line in result.stdout.splitlines():
        if "Developer ID Application" not in line:
            continue
        match = re.search(r'"([^"]+)"', line)
        if match is not None:
            return match.group(1)
    return None


def codesign_app(app_bundle: Path, identity: str) -> None:
    run(
        [
            "codesign",
            "--force",
            "--deep",
            "--options",
            "runtime",
            "--sign",
            identity,
            str(app_bundle),
        ]
    )


def notarize_app(app_zip: Path) -> None:
    apple_id = os.environ.get("APPLE_ID")
    password = os.environ.get("APPLE_APP_SPECIFIC_PASSWORD")
    team_id = os.environ.get("APPLE_TEAM_ID")
    if not apple_id or not password or not team_id:
        return
    run(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(app_zip),
            "--apple-id",
            apple_id,
            "--password",
            password,
            "--team-id",
            team_id,
            "--wait",
        ]
    )
    run(["xcrun", "stapler", "staple", str(DIST_DIR / "msgflow.app")])


def archive_cli(version: str, arch: str, out_dir: Path) -> Path:
    source_dir = DIST_DIR / "msgflow"
    archive_path = out_dir / f"msgflow-{version}-macos-{arch}.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(source_dir, arcname=".")
    return archive_path


def archive_app(version: str, arch: str, out_dir: Path) -> Path:
    app_bundle = DIST_DIR / "msgflow.app"
    if not app_bundle.exists():
        raise FileNotFoundError(f"missing app bundle: {app_bundle}")
    archive_path = out_dir / f"msgflow-app-{version}-macos-{arch}.zip"
    archive_path.unlink(missing_ok=True)
    run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", "msgflow.app", str(archive_path)], cwd=DIST_DIR)
    return archive_path


def render_homebrew_files(version: str, tag: str, repo: str, out_dir: Path) -> None:
    homepage = f"https://github.com/{repo}" if repo else "https://github.com/axel/msgflow"
    release_base_url = f"{homepage}/releases/download/{tag}" if repo else ""
    cli_archives = discover_archives(out_dir, version, "msgflow", ".tar.gz")
    app_archives = discover_archives(out_dir, version, "msgflow-app", ".zip")
    replacements = {
        "VERSION": version,
        "HOMEPAGE": homepage,
        "CLI_SOURCE": render_cli_source(cli_archives, release_base_url),
        "APP_SOURCE": render_app_source(app_archives, release_base_url),
    }
    render_template(
        PACKAGING_DIR / "homebrew" / "msgflow.rb.tmpl",
        out_dir / "homebrew" / "Formula" / "msgflow.rb",
        replacements,
    )
    render_template(
        PACKAGING_DIR / "homebrew" / "msgflow-app.rb.tmpl",
        out_dir / "homebrew" / "Casks" / "msgflow-app.rb",
        replacements,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build msgflow release artifacts")
    parser.add_argument(
        "--version",
        default=None,
        help="release version without the leading v, defaults to [project].version in pyproject.toml",
    )
    parser.add_argument("--tag", default=None, help="git tag name, defaults to v<version>")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/repo for release URLs")
    parser.add_argument("--out-dir", default="release", help="output directory relative to project root")
    parser.add_argument(
        "--arch",
        default=None,
        help="override the macOS architecture label used in archive names, defaults to the current machine",
    )
    parser.add_argument("--skip-build", action="store_true", help="reuse existing dist artifacts")
    parser.add_argument("--skip-homebrew", action="store_true", help="skip rendering Homebrew Formula/Cask files")
    parser.add_argument(
        "--render-homebrew-only",
        action="store_true",
        help="render Homebrew Formula/Cask files from existing archives in --out-dir without building",
    )
    parser.add_argument(
        "--smoke-homebrew",
        action="store_true",
        help="launch-test the Homebrew app zip after extracting it; intended for local verification",
    )
    args = parser.parse_args()

    version = args.version or project_version()
    tag = args.tag or f"v{version}"
    github_ref_name = os.environ.get("GITHUB_REF_NAME", "")
    if args.tag is None and github_ref_name.startswith("v") and github_ref_name != tag:
        raise RuntimeError(
            f"git tag {github_ref_name!r} does not match pyproject.toml version {version!r}; "
            "update [project].version or pass --version explicitly"
        )
    out_dir = ROOT_DIR / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    arch = normalize_arch(args.arch or platform.machine())
    if arch not in SUPPORTED_MACOS_ARCHES:
        print(f"warning: building unsupported macOS architecture label {arch!r}", file=sys.stderr)

    if args.render_homebrew_only:
        render_homebrew_files(version, tag, args.repo, out_dir)
        return

    if not args.skip_build:
        refresh_package_metadata()
        shutil.rmtree(BUILD_DIR, ignore_errors=True)
        shutil.rmtree(DIST_DIR, ignore_errors=True)
        build_pyinstaller("msgflow-cli.spec", version)
        build_pyinstaller("msgflow-core.spec", version)
        build_pyinstaller("msgflow-app.spec", version)
        bundle_core_binary()
        signing_identity = find_codesigning_identity()
        if signing_identity:
            codesign_app(DIST_DIR / "msgflow.app", signing_identity)

    cli_archive = archive_cli(version, arch, out_dir)
    app_archive = archive_app(version, arch, out_dir)
    if args.smoke_homebrew:
        verify_app_archive_launches(app_archive)
    notarize_app(app_archive)
    if os.environ.get("APPLE_ID") and os.environ.get("APPLE_APP_SPECIFIC_PASSWORD") and os.environ.get("APPLE_TEAM_ID"):
        app_archive.unlink(missing_ok=True)
        app_archive = archive_app(version, arch, out_dir)
        if args.smoke_homebrew:
            verify_app_archive_launches(app_archive)

    if not args.skip_homebrew:
        render_homebrew_files(version, tag, args.repo, out_dir)


if __name__ == "__main__":
    main()
