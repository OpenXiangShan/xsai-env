#!/usr/bin/env python3
"""Portable openRuyi/PyTorch input verification and initramfs assembly.

The recipe deliberately has no knowledge of a checkout location.  Inputs are
resolved relative to the manifest or fetched from a fixed URL, then checked
before staging.  Generated files are written only below --out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse
import urllib.request


SCHEMA_VERSION = 1
HEX64 = set("0123456789abcdef")


class RecipeError(RuntimeError):
    pass


def die(message: str) -> None:
    raise RecipeError(message)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha256_tree(path: Path) -> str:
    """Digest a directory without depending on inode, uid, mtime or ordering."""
    h = hashlib.sha256()
    for item in sorted(path.rglob("*")):
        rel = item.relative_to(path).as_posix()
        if item.is_dir():
            record = f"D {rel}\n".encode()
        elif item.is_file():
            record = f"F {rel} ".encode() + sha256_file(item).encode() + b"\n"
        else:
            die(f"unsupported input tree entry (not file/dir): {item}")
        h.update(record)
    return h.hexdigest()


def digest(path: Path) -> str:
    if path.is_file():
        return sha256_file(path)
    if path.is_dir():
        return sha256_tree(path)
    die(f"input does not exist: {path}")


def require_hash(name: str, value: object) -> str:
    if not isinstance(value, str) or len(value) != 64:
        die(f"{name}: sha256 must be a 64-hex-character string")
    result = value.lower()
    if any(char not in HEX64 for char in result):
        die(f"{name}: sha256 is not hexadecimal")
    return result


def load_manifest(path: Path) -> tuple[dict, Path]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        die(f"cannot read manifest {path}: {exc}")
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        die(f"manifest must be an object with schema_version={SCHEMA_VERSION}")
    if not isinstance(data.get("artifacts"), dict):
        die("manifest.artifacts must be an object")
    if not isinstance(data.get("rpms"), list) or not data["rpms"]:
        die("manifest.rpms must be a non-empty list")
    return data, path.parent.resolve()


def validate_source(name: str, source: dict, manifest_dir: Path) -> None:
    if not isinstance(source, dict):
        die(f"{name}: artifact must be an object")
    expected = require_hash(f"{name}.sha256", source.get("sha256"))
    path = source.get("path")
    url = source.get("url")
    if not isinstance(path, str) and not isinstance(url, str):
        die(f"{name}: provide path or fixed url")
    if isinstance(path, str) and os.path.isabs(path):
        # Absolute paths are allowed only when explicitly supplied by the user;
        # the recipe never creates them or derives them from the checkout.
        pass
    if isinstance(url, str) and not (url.startswith("https://") or url.startswith("http://")):
        die(f"{name}.url must be http(s)")
    if isinstance(path, str):
        candidate = Path(path) if os.path.isabs(path) else manifest_dir / path
        if candidate.exists():
            actual = digest(candidate)
            if actual != expected:
                die(f"{name}: sha256 mismatch (expected {expected}, got {actual})")
        elif not isinstance(url, str):
            die(f"{name}: local path does not exist: {candidate}")


def validate_manifest(data: dict, manifest_dir: Path) -> None:
    artifacts = data["artifacts"]
    required = ("oci_rootfs", "kernel", "dtb", "initramfs", "headers")
    for name in required:
        if name not in artifacts:
            die(f"missing required artifact: {name}")
        validate_source(f"artifacts.{name}", artifacts[name], manifest_dir)
    if "gcpt" in artifacts:
        validate_source("artifacts.gcpt", artifacts["gcpt"], manifest_dir)

    abi = data.get("header_abi")
    if not isinstance(abi, dict):
        die("header_abi must explicitly describe the extension build ABI")
    for field in ("python", "torch", "libc", "cxx11_abi"):
        if field not in abi or abi[field] in (None, ""):
            die(f"header_abi.{field} is required")

    for index, package in enumerate(data["rpms"]):
        name = f"rpms[{index}]"
        if not isinstance(package, dict):
            die(f"{name}: package must be an object")
        for field in ("name", "version", "arch"):
            if not isinstance(package.get(field), str) or not package[field]:
                die(f"{name}.{field} is required")
        validate_source(name, package, manifest_dir)


def resolve_source(name: str, source: dict, manifest_dir: Path,
                   cache_dir: Path) -> Path:
    expected = require_hash(f"{name}.sha256", source.get("sha256"))
    path_value = source.get("path")
    candidate = (manifest_dir / path_value).resolve() if isinstance(path_value, str) and not os.path.isabs(path_value) else (Path(path_value).resolve() if isinstance(path_value, str) else None)

    if candidate is None or not candidate.exists():
        url = source.get("url")
        if not isinstance(url, str):
            die(f"{name}: path is missing and no fixed url is available")
        cache_dir.mkdir(parents=True, exist_ok=True)
        filename = Path(urlparse(url).path).name or name.replace(".", "_")
        candidate = cache_dir / filename
        if not candidate.exists():
            try:
                urllib.request.urlretrieve(url, candidate)
            except Exception as exc:
                die(f"{name}: download failed from fixed url: {exc}")
    actual = digest(candidate)
    if actual != expected:
        die(f"{name}: sha256 mismatch (expected {expected}, got {actual})")
    return candidate


def safe_extract_tar(archive: Path, destination: Path) -> None:
    import tarfile
    try:
        with tarfile.open(archive) as tar:
            root = destination.resolve()
            for member in tar.getmembers():
                target = (destination / member.name).resolve()
                if target != root and root not in target.parents:
                    die(f"archive contains path traversal: {member.name}")
            tar.extractall(destination)
    except (OSError, tarfile.TarError) as exc:
        die(f"cannot extract OCI tar {archive}: {exc}")


def extract_rpm(package: Path, destination: Path) -> None:
    rpm2cpio = shutil.which("rpm2cpio")
    cpio = shutil.which("cpio")
    if not rpm2cpio or not cpio:
        die("RPM extraction requires rpm2cpio and cpio on the host")
    destination.mkdir(parents=True, exist_ok=True)
    first = subprocess.Popen([rpm2cpio, str(package)], stdout=subprocess.PIPE)
    try:
        second = subprocess.run(
            [cpio, "--extract", "--make-directories", "--no-absolute-filenames"],
            cwd=destination, stdin=first.stdout, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, text=True)
    finally:
        assert first.stdout is not None
        first.stdout.close()
        first.wait()
    if first.returncode != 0 or second.returncode != 0:
        detail = (second.stderr or "").strip()
        die(f"RPM extraction failed for {package.name}: {detail}")


def copy_overlay(destination: Path) -> None:
    overlay = Path(__file__).with_name("overlay")
    if not overlay.is_dir():
        die(f"tracked overlay is missing: {overlay}")
    for source in overlay.rglob("*"):
        relative = source.relative_to(overlay)
        target = destination / relative
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        else:
            die(f"unsupported overlay entry: {source}")


def write_cpio(root: Path, output: Path) -> None:
    cpio = shutil.which("cpio")
    zstd = shutil.which("zstd")
    if not cpio or not zstd:
        die("initramfs assembly requires cpio and zstd on the host")
    output.parent.mkdir(parents=True, exist_ok=True)
    find = subprocess.Popen(
        ["find", ".", "-print0"], cwd=root, stdout=subprocess.PIPE)
    pack = subprocess.Popen(
        [cpio, "--null", "--create", "--format=newc", "--owner=0:0"],
        cwd=root, stdin=find.stdout, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    assert find.stdout is not None and pack.stdout is not None
    find.stdout.close()
    compressor = subprocess.run(
        [zstd, "-1", "-T0", "-q", "-o", str(output)],
        stdin=pack.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pack.stdout.close()
    find_rc = find.wait()
    pack_rc = pack.wait()
    if find_rc or pack_rc or compressor.returncode:
        detail = (compressor.stderr or b"").decode(errors="replace").strip()
        die(f"initramfs assembly failed: {detail}")


def receipt(data: dict, resolved: dict[str, str], output: Path) -> None:
    record = {
        "schema_version": SCHEMA_VERSION,
        "profile": data.get("profile", "openruyi-pytorch"),
        "header_abi": data["header_abi"],
        "resolved_inputs": resolved,
        "recipe": data.get("recipe", {}),
    }
    (output / "inputs.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def validate_command(manifest: Path) -> int:
    data, directory = load_manifest(manifest.resolve())
    validate_manifest(data, directory)
    print(f"manifest valid: {manifest}")
    return 0


def assemble_command(manifest: Path, output: Path, payload: bool) -> int:
    data, directory = load_manifest(manifest.resolve())
    validate_manifest(data, directory)
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        die(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    cache = output / ".cache"
    resolved: dict[str, str] = {}
    try:
        artifacts = data["artifacts"]
        for name, source in artifacts.items():
            resolved[f"artifacts.{name}"] = str(resolve_source(f"artifacts.{name}", source, directory, cache))
        for index, package in enumerate(data["rpms"]):
            resolved[f"rpms[{index}]"] = str(resolve_source(f"rpms[{index}]", package, directory, cache))

        stage = Path(tempfile.mkdtemp(prefix=".stage-", dir=output))
        root = stage / "root"
        root.mkdir()
        safe_extract_tar(Path(resolved["artifacts.oci_rootfs"]), root)
        for index, package in enumerate(data["rpms"]):
            extract_rpm(Path(resolved[f"rpms[{index}]"]), root)
        copy_overlay(root)
        write_cpio(root, output / "rootfs.cpio.zst")
        for name in ("kernel", "dtb", "initramfs", "headers", "gcpt"):
            key = f"artifacts.{name}"
            if key in resolved:
                shutil.copy2(resolved[key], output / Path(resolved[key]).name) if Path(resolved[key]).is_file() else None
        receipt(data, resolved, output)
        if payload:
            die("--payload requires a fixed GCPT wrapper and is reserved for the firmware integration step")
        shutil.rmtree(stage)
    except Exception:
        # Keep no partial stage tree; the output directory itself is retained so
        # callers can inspect only the error and retry safely after correction.
        for child in output.glob(".stage-*"):
            shutil.rmtree(child, ignore_errors=True)
        raise
    print(f"assembled initramfs: {output / 'rootfs.cpio.zst'}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "assemble"):
        item = sub.add_parser(command)
        item.add_argument("--manifest", type=Path, required=True)
        if command == "assemble":
            item.add_argument("--out", type=Path, required=True)
            item.add_argument("--payload", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return validate_command(args.manifest)
        return assemble_command(args.manifest, args.out, args.payload)
    except RecipeError as exc:
        print(f"ruyi recipe: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
