# openRuyi/PyTorch release recipe

This directory contains the portable, input-verified part of the existing
openRuyi + PyTorch release.  It does not contain a copied OCI tree, RPMs,
kernel images, initramfs archives, model files, or board payloads.

The entrypoint is `build.sh`:

The checked-in current runtime example is directly verifiable against public,
digest-pinned sources (the RPM repository snapshot is recorded in the
manifest):

```sh
firmware/ruyi/build.sh validate \
  --manifest firmware/ruyi/examples/openruyi-pytorch-current.json
firmware/ruyi/build.sh assemble \
  --manifest firmware/ruyi/examples/openruyi-pytorch-current.json \
  --out build/ruyi
```

`assemble` resolves every declared input from either its manifest-relative
`path` or its fixed `url`, verifies the required SHA-256, extracts the OCI
rootfs and RPMs into a generated staging directory, installs the tracked
overlay, and emits a compressed newc initramfs plus an input receipt.  It never
uses `local/ruyi-pytorch/root-oci`, `local/ruyi-pytorch`, or a personal
absolute path implicitly. Downloaded inputs live in an external cache
(`$XSAI_RUYI_CACHE`, `--cache-dir`, or `~/.cache/xsai-ruyi`), never under the
generated output tree.

The manifest is intentionally strict:

* the userspace OCI artifact and every RPM have a non-empty SHA-256 and either
  a path or URL;
* RPM package names, versions, architecture and hashes are recorded;
* optional board inputs (kernel, DTB, initramfs, GCPT and extension headers)
  are explicit inputs when supplied;
* an extension header directory has a deterministic tree digest and its ABI
  must state a verified `cxx11_abi` of `0` or `1`;
* missing or unverifiable inputs stop the build before any output is written.

`examples/openruyi-pytorch-runtime.json` records the package set used by the
September 13, 2026 board evidence, but its old RPM URLs are intentionally
not presented as a current download closure.  `examples/openruyi-pytorch.json`
is retained as a template for a board-specific release.  The current runtime
example intentionally stops at the
userspace/initramfs boundary: firmware generates the DTB and owns the
kernel/GCPT/external-initramfs physical layout.  This prevents a local DTB or
private payload from being mistaken for a portable download.

`ruyi.lazymeta` remains opt-in.  The init overlay always starts `warmd` with
`XSAI_LAZYMETA=0`, so the proven warm path is not affected by the optional
cold-import optimization.

The recipe only assembles the userspace/initramfs side.  A board-specific
GCPT/OpenSBI/kernel integration remains owned by the firmware build flow.
`assemble --payload` therefore fails closed before downloading or staging; use
the firmware `build-external` target after the generated DTB and owner-side
DTSGen contract are available.
