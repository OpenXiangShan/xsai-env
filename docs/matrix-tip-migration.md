# Matrix component refresh — October 2026

This is an intentional compatibility transition, not a claim that the old
software, checkpoint, RTL and board artifacts are interchangeable.

## Selected components

| Component | Previous pin | Selected pin / branch |
|---|---|---|
| XSAI | `04909692` | `ee268923b`, master |
| nexus-am | `11e0547e` | `cbb6b402`, feat-matrix |
| NEMU | `c9df0dd0`, feat-matrix | `2ec110b6`, master |

The XSAI successor `ee268923b` changes only the two READMEs and an architecture
image relative to built `dc8c277e`; RTL and nested submodule pins are identical.
The new AME tests use proposal-14 contracts, including stride-less
whole-register operations. NEMU master includes the corresponding matrix
configuration and event interfaces; the old feature branch is not the new
reference contract.

QEMU remains on its configured `9.0.0_matrix-v0.6` branch at `710c609a`.
Its checkpoint/software artifact path is retained, not certified as a
proposal-14 reference by this change. Firmware, rootfs and software pins are
unchanged. Do not transplant dirty local ISA or board patches to bridge
contracts implicitly.

## Build and execution

Initialize XSAI's nested dependencies with its own target:

```bash
source env.sh
make -C XSAI init-force
make xsai
make test-matrix
```

`test-matrix` now builds `nexus-am/tests/ame-mmacc` for `riscv64-xs` with the
custom LLVM. `tests/ame0.6` is no longer the runnable default. The custom
compiler must accept `-march=rv64gc_zames_zmasync`.

The parent's initialization guard checks the current `XSAICache`/`OpenNCB`
layout, not the removed top-level `openLLC`, `huancun` and `coupledL2`
directories. A real missing dependency still invokes XSAI's own `init-force`.

Keep DiffTest's `XSAI/build/emu` symlink as the default backend selector.
For an existing binary use an explicit path:

```bash
make run-emu EMU_BIN=/absolute/path/to/emu DIFF=0 \
  PAYLOAD=nexus-am/tests/ame-mmacc/build/ame-mmacc-riscv64-xs.bin
```

Runtime `DIFF=0` differs from build-time `NO_DIFF=1`. The latter removes trap
and instruction monitors, so waiting for `GOOD TRAP` or relying on `-I` will
not terminate such an emulator. For basic smoke on that binary require the
complete expected PASS messages, no failures, and guest `Exit with code = 0`,
then stop that specific worker. Preserve the host exit status separately.
This is UART-gated acceptance, not difftest. Use a cycle limit and bounded
wall-clock timeout.

## Evidence boundaries

The selected gate is basic bare-metal AME execution on the existing
`DefaultMatrixConfig` Verilator emu (one core, eight host threads, no
DRAMsim3/wave/ChiselDB, build-time `NO_DIFF=1`). It does not certify full
Linux execution, every instruction, a new bitstream, or differential state.

The forced emu gate completed on 2026-10-16. The binary was built on
`node028`, copied to monitored `node023`, and run on physical cores `48-55`
as one worker. Its SHA-256 is
`1346a48f8f8eb301bc62884a0955174bc65dd31c9c948f1af9cfd5b99b99225e`.
Every case printed its complete expected PASS set, no failure marker, and
guest `Exit with code = 0`:

| Case | Expected / observed checks | Payload SHA-256 |
|---|---:|---|
| `ame-zero-word` | 2 / 2 | `f2e43f4f3bccc8c5c2948f7a412147c1ef65e1badc78e7188e0a2369b380d412` |
| `ame-ls-ab` | 4 / 4 | `905097c47cb34ca09301380965a8ff65f5e9e78753ece809adc84a68518b597f` |
| `ame-gemm` | 1 / 1 | `4a5881af320ef2ced1fd91a83ef04fba85efd9f739c2e330e2963baf428ed05e` |
| `ame-ls-word` | 4 / 4 | `b2cb8787a5f0f34f6a0ca667253189117d9b5792192dcdeba24f1d15e5d503c1` |
| `ame-mmacc` | 5 / 5 | `2609e0e9b9eef0b14d64045b1cfa3d8864936fe565f9afa7025ff1bf89448bbc` |

Because this emu was built with `NO_DIFF=1`, the harness intentionally
stopped each worker after the guest completion marker; this is the
UART-gated boundary described above, not a natural host exit or GOOD TRAP.

The unchanged released software/firmware path has a separate cloud-FPGA
acceptance: job **279983**, embedded-DTB NEMU payload SHA-256
`9e38c96bdbe5529cd71568970417c7fec881c720b600b7adb831fb2eccc80976`.
Its full UART includes OpenSBI/Linux boot, Q8_0 4/4, BF16 correctness passes
and guest status 0. Job279984 adds Q8/BF16 smoke and CI success but its saved
trace does not show full guest completion. The board was reused (`keep`);
there is no saved bitstream digest and this is not a test of the refreshed
RTL on FPGA.

ROB-pointer, HNX256, FlashAttention, CUTE/physical-design and PLDM research
remain outside this refresh.
