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
import posixpath
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlparse
import urllib.request


SCHEMA_VERSION = 2
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
        if item.is_symlink():
            record = f"L {rel} {os.readlink(item)}\n".encode()
        elif item.is_dir():
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
    if isinstance(url, str) and not url.startswith("https://"):
        die(f"{name}.url must be an https URL")
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
    if "oci_rootfs" not in artifacts:
        die("missing required artifact: oci_rootfs")
    for name in ("kernel", "dtb", "initramfs", "headers"):
        if name in artifacts:
            validate_source(f"artifacts.{name}", artifacts[name], manifest_dir)
    if "gcpt" in artifacts:
        validate_source("artifacts.gcpt", artifacts["gcpt"], manifest_dir)

    abi = data.get("header_abi")
    if "headers" in artifacts:
        if not isinstance(abi, dict):
            die("header_abi must explicitly describe the extension build ABI")
        for field in ("python", "torch", "libc", "cxx11_abi"):
            if field not in abi or abi[field] in (None, ""):
                die(f"header_abi.{field} is required")
        if abi["cxx11_abi"] not in (0, 1, "0", "1"):
            die("header_abi.cxx11_abi must be verified as 0 or 1")

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
        filename = Path(unquote(urlparse(url).path)).name or name.replace(".", "_")
        # A filename is not a cache key: mirrors can reuse names across
        # releases.  Include the expected digest and never expose a partial
        # download as a valid cache entry.
        candidate = cache_dir / f"{filename}.{expected}"
        if candidate.exists() and digest(candidate) == expected:
            return candidate
        temporary = cache_dir / f".{filename}.{expected}.part"
        temporary.unlink(missing_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=60) as response, \
                    temporary.open("wb") as stream:
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    stream.write(block)
            actual = digest(temporary)
            if actual != expected:
                die(f"{name}: downloaded sha256 mismatch (expected {expected}, got {actual})")
            os.replace(temporary, candidate)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            if isinstance(exc, RecipeError):
                raise
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
                name = PurePosixPath(member.name)
                if name.is_absolute() or ".." in name.parts:
                    die(f"archive contains path traversal: {member.name}")
                target = (destination / Path(*name.parts)).resolve()
                if target != root and root not in target.parents:
                    die(f"archive contains path traversal: {member.name}")
                if member.issym() or member.islnk():
                    link = PurePosixPath(member.linkname)
                    link_name = member.linkname.lstrip("/") if link.is_absolute() else member.linkname
                    link_base = "" if link.is_absolute() else posixpath.dirname(member.name)
                    link_target = posixpath.normpath(posixpath.join(link_base, link_name))
                    if link_target == ".." or link_target.startswith("../"):
                        die(f"archive link escapes destination: {member.name} -> {member.linkname}")
                elif not (member.isdir() or member.isfile()):
                    die(f"archive contains unsupported special entry: {member.name}")
            tar.extractall(destination)
    except (OSError, tarfile.TarError) as exc:
        die(f"cannot extract OCI tar {archive}: {exc}")


def make_stage_writable(root: Path) -> None:
    """Allow an unprivileged recipe process to overlay RPM files.

    OCI archives carry root-owned, often read-only directory modes.  The
    staging tree is not the final image, so add only the current owner's
    write/search bits; the final cpio remains owned by root.
    """
    for item in (root, *root.rglob("*")):
        try:
            mode = item.lstat().st_mode
            if item.is_symlink():
                continue
            if item.is_dir():
                os.chmod(item, mode | 0o700)
            elif item.is_file():
                os.chmod(item, mode | 0o600)
        except OSError as exc:
            die(f"cannot make staging entry writable: {item}: {exc}")


def extract_rpm(package: Path, destination: Path) -> None:
    rpm2cpio = shutil.which("rpm2cpio")
    cpio = shutil.which("cpio")
    if not cpio:
        die("RPM extraction requires cpio on the host")
    destination.mkdir(parents=True, exist_ok=True)
    if rpm2cpio:
        first = subprocess.Popen([rpm2cpio, str(package)], stdout=subprocess.PIPE)
    else:
        # Keep the recipe usable on minimal build hosts.  The RPM payload is a
        # compressed cpio stream; only the lead/header framing is parsed here,
        # while cpio remains the extractor and the archive path is still
        # checked with --no-absolute-filenames.
        def rpm_header(stream):
            magic = stream.read(3)
            if magic != b"\x8e\xad\xe8":
                die(f"invalid RPM header in {package}")
            stream.read(5)
            count = int.from_bytes(stream.read(4), "big")
            size = int.from_bytes(stream.read(4), "big")
            index = [(
                int.from_bytes(stream.read(4), "big"),
                int.from_bytes(stream.read(4), "big"),
                int.from_bytes(stream.read(4), "big"),
                int.from_bytes(stream.read(4), "big"),
            ) for _ in range(count)]
            data = stream.read(size)
            return index, data

        source = package.open("rb")
        if source.read(96)[:4] != b"\xed\xab\xee\xdb":
            source.close()
            die(f"invalid RPM lead in {package}")
        rpm_header(source)
        source.seek((source.tell() + 7) & ~7)
        index, data = rpm_header(source)
        payload_offset = source.tell()
        payload = source.read(6)
        if payload[:4] == b"\x28\xb5\x2f\xfd":
            decoder = ["zstd", "-dc"]
        elif payload[:6] == b"\xfd7zXZ\x00":
            decoder = ["xz", "-dc"]
        elif payload[:2] == b"\x1f\x8b":
            decoder = ["gzip", "-dc"]
        elif payload[:3] == b"BZh":
            decoder = ["bzip2", "-dc"]
        else:
            source.close()
            die(f"unsupported RPM payload compressor in {package}")
        source.close()
        compressed = subprocess.Popen(
            ["tail", "-c", f"+{payload_offset + 1}", str(package)],
            stdout=subprocess.PIPE,
        )
        first = subprocess.Popen(
            decoder, stdin=compressed.stdout, stdout=subprocess.PIPE
        )
        assert compressed.stdout is not None
        compressed.stdout.close()
    try:
        second = subprocess.run(
            [cpio, "--extract", "--make-directories", "--no-absolute-filenames"],
            cwd=destination, stdin=first.stdout, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, text=True)
    finally:
        assert first.stdout is not None
        first.stdout.close()
        first.wait()
        if not rpm2cpio:
            compressed.wait()
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
            if target.is_symlink():
                target.unlink()
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
        "header_abi": data.get("header_abi"),
        "resolved_inputs": resolved,
        "recipe": data.get("recipe", {}),
    }
    (output / "inputs.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def validate_command(manifest: Path) -> int:
    data, directory = load_manifest(manifest.resolve())
    validate_manifest(data, directory)
    print(f"manifest valid: {manifest}")
    return 0


def assemble_command(manifest: Path, output: Path, payload: bool,
                     cache_dir: Path | None) -> int:
    data, directory = load_manifest(manifest.resolve())
    validate_manifest(data, directory)
    if payload:
        # Do not download/extract a large image before reporting that payload
        # assembly is intentionally owned by the firmware flow.
        die("--payload requires a fixed GCPT wrapper and is reserved for the firmware integration step")
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        die(f"refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    # Keep downloaded OCI/RPM inputs outside the generated output directory.
    # This prevents a failed/repeated build from leaving a bulky cache beside
    # the small receipt and initramfs deliverables.
    cache = (cache_dir or
             Path(os.environ.get("XSAI_RUYI_CACHE",
                                 str(Path.home() / ".cache" / "xsai-ruyi")))).resolve()
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
        make_stage_writable(root)
        for index, package in enumerate(data["rpms"]):
            extract_rpm(Path(resolved[f"rpms[{index}]"]), root)
        copy_overlay(root)
        write_cpio(root, output / "rootfs.cpio.zst")
        for name in ("kernel", "dtb", "initramfs", "headers", "gcpt"):
            key = f"artifacts.{name}"
            if key in resolved:
                source = Path(resolved[key])
                target = output / source.name
                if source.is_file():
                    shutil.copy2(source, target)
                elif source.is_dir():
                    shutil.copytree(source, target)
        receipt(data, resolved, output)
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
            item.add_argument(
                "--cache-dir", type=Path,
                help="external cache for fixed downloads (default: $XSAI_RUYI_CACHE or ~/.cache/xsai-ruyi)",
            )
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return validate_command(args.manifest)
        return assemble_command(args.manifest, args.out, args.payload, args.cache_dir)
    except RecipeError as exc:
        print(f"ruyi recipe: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
