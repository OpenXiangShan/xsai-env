# openRuyi/PyTorch release recipe

This directory contains the portable, input-verified part of the existing
openRuyi + PyTorch release.  It does not contain a copied OCI tree, RPMs,
kernel images, initramfs archives, model files, or board payloads.

The entrypoint is `build.sh`:

```sh
firmware/ruyi/build.sh validate --manifest path/to/release.json
firmware/ruyi/build.sh assemble --manifest path/to/release.json --out build/ruyi
```

`assemble` resolves every declared input from either its manifest-relative
`path` or its fixed `url`, verifies the required SHA-256, extracts the OCI
rootfs and RPMs into a generated staging directory, installs the tracked
overlay, and emits a compressed newc initramfs plus an input receipt.  It never
uses `local/ruyi-pytorch/root-oci`, `local/ruyi-pytorch`, or a personal
absolute path implicitly.

The manifest is intentionally strict:

* every artifact has a non-empty SHA-256 and either a path or URL;
* RPM package names, versions, architecture and hashes are recorded;
* the kernel, DTB, optional GCPT wrapper, initramfs input, and extension-header
  ABI are explicit inputs;
* an extension header directory has a deterministic tree digest;
* missing or unverifiable inputs stop the build before any output is written.

The OCI digest and kernel/initramfs URLs were not present in the preserved
release record.  `examples/openruyi-pytorch.json` therefore documents the
known RPM provenance while leaving those values as `null`; it is expected to
fail validation until a release owner fills them with verified values.
That is deliberate: the recipe does not claim a from-source closure from
unavailable provenance.

`ruyi.lazymeta` remains opt-in.  The init overlay always starts `warmd` with
`XSAI_LAZYMETA=0`, so the proven warm path is not affected by the optional
cold-import optimization.

The recipe only assembles the userspace/initramfs side.  A board-specific
GCPT/OpenSBI/kernel integration remains owned by the firmware build flow; if a
fixed GCPT wrapper is supplied, `assemble --payload` can append the generated
initramfs at the documented, aligned offset after verifying all inputs.
