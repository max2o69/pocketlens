"""Build a release from an explicit file list, never from the working directory wholesale."""

import argparse
import hashlib
from pathlib import Path
import re
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    "README.md",
    "LICENSE",
    "VERSION",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "PocketLens Runtime.ps1",
    ".gitignore",
    ".gitattributes",
    "camera.py",
    "server.py",
    "rtc_receiver.py",
    "Start PocketLens.ps1",
    "Start PocketLens.cmd",
    "Remove PocketLens.ps1",
    "Remove PocketLens.cmd",
    "Allow PocketLens Network.ps1",
    "Remove PocketLens Network Rules.cmd",
    "Install PocketLens System Camera.ps1",
    "Install PocketLens System Camera.cmd",
    "Remove PocketLens System Camera.cmd",
    "Build PocketLens Native.ps1",
    "Test PocketLens Browser.ps1",
    "Diagnose PocketLens.ps1",
    "Diagnose PocketLens.cmd",
    "native/register-system.cpp",
    "native/SOFTCAM-LICENSE.txt",
    "native/MICROSOFT-LICENSE.txt",
)
TREES = {
    "web": {".html", ".js", ".css", ".svg"},
    "native/src": {".h", ".cpp", ".def"},
    "scripts": {".py", ".js"},
    "tests": {".py", ".js"},
    ".github": {".yml", ".yaml"},
}
SOURCE_ONLY = {
    "requirements-dev.txt",
    "pyproject.toml",
    ".gitignore",
    ".gitattributes",
    "Build PocketLens Native.ps1",
    "Test PocketLens Browser.ps1",
    "native/register-system.cpp",
}
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")


def release_files(root, kind, native_bin=None):
    root = root.resolve()
    files = [
        (root / name, name) for name in ROOT_FILES if kind == "source" or name not in SOURCE_ONLY
    ]
    trees = TREES if kind == "source" else {"web": TREES["web"]}
    for tree, suffixes in trees.items():
        files.extend(
            (path, path.relative_to(root).as_posix())
            for path in sorted((root / tree).rglob("*"))
            if path.is_file() and path.suffix in suffixes and "__pycache__" not in path.parts
        )
    if kind == "windows":
        files.append((root / "scripts/unregister.py", "scripts/unregister.py"))
        native_bin = (native_bin or root / "native/bin").resolve()
        for arch in ("x64", "x86"):
            for name in ("pocketlens.dll", "register-system.exe"):
                files.append((native_bin / arch / name, f"native/bin/{arch}/{name}"))
    for path, name in files:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing release file or symbolic link: {name}")
        # Resolve every source path to guard against junctions into private state.
        allowed_root = native_bin if name.startswith("native/bin/") else root
        if not path.resolve().is_relative_to(allowed_root):
            raise ValueError(f"Release file resolves outside its source tree: {name}")
        if PRIVATE_KEY.search(path.read_bytes()):
            raise ValueError(f"Private key detected in release file: {name}")
    return files


def package(root, output, kind, native_bin=None):
    version = (root / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?", version):
        raise ValueError("VERSION must contain a semantic version")
    files = release_files(root, kind, native_bin)
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"pocketlens-{version}-{kind}.zip"
    prefix = f"pocketlens-{version}"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path, name in files:
            bundle.write(path, f"{prefix}/{name}")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n")
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("source", "windows"), default="windows")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--native-bin", type=Path)
    args = parser.parse_args()
    print(package(ROOT, args.output, args.kind, args.native_bin))
