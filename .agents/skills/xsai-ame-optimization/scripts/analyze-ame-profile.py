#!/usr/bin/env python3
"""Summarize XSAI [AME_PROFILE] groups with one consistent MFU definition."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


PROFILE_RE = re.compile(r"\[AME_PROFILE\]\s+(calls|cycles|derived)\s+(.*)")
MX_PROFILE_RE = re.compile(r"\[AME_PROFILE\]\s+(mxfp4(?:_k[0-9]+)?)\s+(.*)")
PAIR_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)")
READY_FIELDS = (
    "first_panel_pack_cycles",
    "serial_ready_panels",
    "serial_ready_consumer_cycles",
    "serial_ready_handoff_cycles",
    "serial_pair_overage_cycles",
    "serial_window_scope",
)
PACKED_PHASE_TIMERS = (
    "rms_stats", "rms_apply", "rms_finite_scan", "packed_qualification",
    "vector_pack", "split_reorder", "rms_AME_reorder",
)
PACKED_PHASE_COUNTS = (
    "calls", "packed_calls", "packed_blocks", "qualification_fallbacks",
    "packed_nv_fallbacks", "rms_rows", "rms_blocks",
)
PACKED_PHASE_SCOPE = {
    "scope": "production_packed_instrumented",
    "raw_cycles_no_overhead_subtraction": "yes",
    "helper_counters_exclude_unfused_RMS": "yes",
    "rejected_qualification_cycles_not_counted": "yes",
}
PHASES = (
    "prepare_cache",
    "pack_a",
    "pack_b",
    "zero_c",
    "ame_tile_call",
    "accumulator_initialization",
    "scale",
    "store",
)


def parse_value(raw: str) -> int | float | str:
    try:
        return float(raw) if any(ch in raw for ch in ".eE") else int(raw, 0)
    except ValueError:
        return raw


def serial_ready_fields(
    record: dict[str, object], case: dict[str, object], rms: dict[str, object],
) -> dict[str, object]:
    def counter(fields: dict[str, object], name: str) -> int:
        value = fields.get(name)
        if type(value) is not int or value < 0:
            raise ValueError(f"missing or invalid {name}")
        return value

    if rms.get("serial_window_scope") != "tile_call_through_scatter":
        raise ValueError("unknown serial-ready consumer scope")
    mode = case.get("mode")
    if mode not in ("serial", "pipeline", "pipeline-chunk") or case.get("exact") != "PASS":
        raise ValueError("serial-ready counters need an exact fused graph sample")
    if (counter(record, "calls") != 1 or counter(rms, "calls") != 1
            or counter(case, "fused_calls") != 1 or counter(case, "first_panels_admitted") != 1):
        raise ValueError("serial-ready counters need one fused call and one first panel")
    panels = counter(case, "panels")
    callbacks = counter(case, "callbacks")
    if (panels == 0 or panels != counter(rms, "prepared_panels")
            or callbacks != counter(rms, "overlap_callbacks")
            or counter(rms, "pipeline_calls") != int(mode == "pipeline")
            or counter(rms, "chunk_pipeline_calls") != int(mode == "pipeline-chunk")):
        raise ValueError("serial-ready work or mode counters disagree")
    preflight = counter(case, "norm_gamma_preflight")
    panel_pack = counter(case, "panel_quant_pack")
    prepare = preflight + panel_pack
    operator_cycles = counter(record, "cycles_total")
    if (counter(rms, "norm_gamma_preflight") != preflight
            or counter(record, "activation_quant_pack") != prepare
            or not 0 < prepare <= operator_cycles <= counter(case, "cycles")):
        raise ValueError("serial-ready prepare totals disagree")

    first = counter(rms, "first_panel_pack_cycles")
    panel_windows = counter(rms, "serial_ready_panels")
    consumer = counter(rms, "serial_ready_consumer_cycles")
    handoff = counter(rms, "serial_ready_handoff_cycles")
    overage = counter(rms, "serial_pair_overage_cycles")
    later = panel_pack - first
    if first == 0 or later < 0 or (later == 0) != (panels == 1):
        raise ValueError("invalid first/later panel pack split")
    fields: dict[str, object] = {name: rms[name] for name in READY_FIELDS}
    fields["post_first_panel_pack_cycles"] = later
    if mode != "serial":
        if panel_windows or consumer or handoff or overage:
            raise ValueError("nonserial sample has serial-only consumer counters")
        return fields

    if callbacks or panel_windows != panels or not 0 <= handoff < consumer or (handoff == 0) != (panels == 1):
        raise ValueError("incomplete serial-ready consumer segments or unexpected callbacks")
    if prepare + consumer > operator_cycles:
        raise ValueError("disjoint serial preparation and consumer time exceed operator cycles")
    minimum_overage = max(0, later - handoff)
    if not minimum_overage <= overage <= later:
        raise ValueError("serial overage violates the measured handoff accounting bound")
    fields.update({
        "serial_ready_tail_consumer_cycles": consumer - handoff,
        "serial_pair_min_overage_cycles": minimum_overage,
        "serial_pair_hideable_ceiling_cycles": later - overage,
        "serial_pair_bound_scope": "accounting_only_not_PE_overlap",
    })
    return fields


def packed_phase_fields(
    record: dict[str, object], case: dict[str, object], profile: dict[str, object],
) -> dict[str, object]:
    if case.get("exact") != "PASS" or any(profile.get(name) != value for name, value in PACKED_PHASE_SCOPE.items()):
        raise ValueError("packed phases need an exact graph and the known raw diagnostic scope")

    counters: dict[str, int] = {}
    for name in PACKED_PHASE_COUNTS + PACKED_PHASE_TIMERS:
        value = profile.get(name)
        if type(value) is not int or value < 0:
            raise ValueError(f"missing or invalid packed-phase {name}")
        counters[name] = value
    if counters["packed_calls"] > counters["calls"]:
        raise ValueError("packed-phase successful calls exceed calls")

    fields: dict[str, object] = {f"packed_phase_{name}": value for name, value in counters.items()}
    fields["packed_phase_scope"] = profile["scope"]
    if (case.get("fused_calls") == 1 and counters["packed_calls"] == counters["calls"] > 0
            and counters["packed_blocks"] > 0 and not counters["qualification_fallbacks"]
            and not counters["packed_nv_fallbacks"]):
        prepare = record.get("activation_quant_pack")
        if type(prepare) is not int or prepare <= 0:
            raise ValueError("packed-phase residual needs a valid preparation total")
        fields["packed_phase_prepare_minus_sum_cycles"] = prepare - sum(
            counters[name] for name in PACKED_PHASE_TIMERS
        )
    return fields


def parse_file(path: Path, peak: float, *, require_serial_ready: bool = False) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    sample = 0
    case: dict[str, object] = {}
    window: dict[str, object] | None = None
    window_case: dict[str, object] = {}
    window_record: dict[str, object] | None = None
    window_ready: dict[str, object] | None = None
    window_packed_phase: dict[str, object] | None = None
    window_rms_lines = 0
    unscoped_mx: list[dict[str, object]] = []
    has_windows = False
    measured_serial_cases = 0
    measured_serial_ready = 0

    def key(values: dict[str, object]) -> tuple[object, ...]:
        return tuple(values.get(name) for name in ("mode", "phase", "sample"))

    def measured_serial(values: dict[str, object]) -> bool:
        return values.get("mode") == "serial" and values.get("phase") == "measured"

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            pairs = PAIR_RE.findall(line)
            values = {name: parse_value(raw) for name, raw in pairs}
            if window_packed_phase is not None and stripped.startswith((
                    "AME_RMS_FUSION_CASE ", "AME_RMS_SAMPLE_PROFILE_BEGIN ")):
                raise ValueError(f"{path}:{line_number}: packed-phase sample missing matching END")
            if (window_ready is not None and stripped.startswith((
                    "AME_RMS_FUSION_CASE ", "AME_RMS_SAMPLE_PROFILE_BEGIN "))):
                raise ValueError(f"{path}:{line_number}: serial-ready sample missing matching END")
            if stripped.startswith("AME_RMS_FUSION_CASE "):
                case = values
                if require_serial_ready and measured_serial(case):
                    run_sample = case.get("sample")
                    if len(values) != len(pairs) or type(run_sample) is not int or run_sample < 1:
                        raise ValueError(f"{path}:{line_number}: invalid measured serial CASE")
                    measured_serial_cases += 1
                # A new case cannot repair a prior missing END.
                window = None
                window_record = None
            elif stripped.startswith("AME_RMS_SAMPLE_PROFILE_BEGIN "):
                has_windows = True
                if require_serial_ready and (measured_serial(case) or measured_serial(values)):
                    if key(case) != key(values) or window is not None or len(values) != len(pairs):
                        raise ValueError(f"{path}:{line_number}: invalid measured serial BEGIN")
                window = values
                window_case = case if key(case) == key(window) else {}
                window_record = None
                window_rms_lines = 0
            elif stripped.startswith("AME_RMS_SAMPLE_PROFILE_END "):
                required = require_serial_ready and (measured_serial(window_case) or measured_serial(values))
                if required and (window_ready is None or len(values) != len(pairs)):
                    raise ValueError(f"{path}:{line_number}: measured serial END lacks a valid RMS profile")
                if (window is not None and key(values) == key(window)
                        and window_case and window_record is not None):
                    seq, hidden, output = (window_case.get(name) for name in ("seq", "hidden", "output"))
                    if any(type(dim) is not int or dim <= 0 for dim in (seq, hidden, output)):
                        raise ValueError(f"{path}:{line_number}: invalid graph shape")
                    expected_ops = 2 * seq * hidden * output
                    if number(window_record, "logical_ops") != expected_ops:
                        raise ValueError(f"{path}:{line_number}: profile/shape work mismatch")
                    if window_case.get("scope") != "whole_graph_RMS_gamma_quant_pack_GEMM_output":
                        raise ValueError(f"{path}:{line_number}: unknown graph timing scope")
                    if window_ready is not None:
                        if window_rms_lines != 1 or window.get("calls_expected") != 1:
                            raise ValueError(f"{path}:{line_number}: serial-ready sample needs one RMS profile")
                        try:
                            window_record.update(serial_ready_fields(window_record, window_case, window_ready))
                        except ValueError as error:
                            raise ValueError(f"{path}:{line_number}: {error}") from error
                        if required:
                            measured_serial_ready += 1
                    if window_packed_phase is not None:
                        if (len(values) != len(pairs) or window.get("calls_expected") != 1
                                or window_record.get("calls") != 1):
                            raise ValueError(f"{path}:{line_number}: packed-phase sample needs one MX profile")
                        try:
                            window_record.update(packed_phase_fields(window_record, window_case, window_packed_phase))
                        except ValueError as error:
                            raise ValueError(f"{path}:{line_number}: {error}") from error
                    sample += 1
                    window_record.update({
                        "sample": sample, "run_sample": window_case["sample"],
                        "mode": window_case["mode"], "phase": window_case["phase"],
                        "M": window_case["output"], "N": window_case["seq"],
                        "K": window_case["hidden"], "graph_exact": window_case.get("exact"),
                        "whole_graph_cycles": window_case["cycles"],
                        "sample_window_complete": True,
                        "macro_cycle_scope": (
                            "exclusive_CPU_wrapper_excludes_nested_prepare"
                            if window_case["mode"] in ("pipeline", "pipeline-chunk")
                            else "AME_call_wrapper"
                        ),
                    })
                    records.append(finalize(window_record, peak))
                elif window_packed_phase is not None:
                    raise ValueError(f"{path}:{line_number}: packed-phase sample missing matching graph or END")
                elif window_ready is not None or required:
                    raise ValueError(f"{path}:{line_number}: serial-ready sample missing matching graph or END")
                case = {}
                window = None
                window_case = {}
                window_record = None
                window_ready = None
                window_packed_phase = None

            if stripped.startswith("AME_RMS_PACKED_PHASE "):
                if (window is None or not window_case or window_record is None or key(values) != key(window)
                        or window_packed_phase is not None or len(values) != len(pairs)):
                    raise ValueError(f"{path}:{line_number}: unmatched, duplicate or out-of-order packed phase")
                window_packed_phase = values

            if window is not None and stripped.startswith("[AME_PROFILE] rms_mxfp4 "):
                window_rms_lines += 1
                if any(name in values for name in READY_FIELDS):
                    if window_ready is not None or window_record is None:
                        raise ValueError(f"{path}:{line_number}: duplicate or out-of-order serial-ready profile")
                    if len(values) != len(pairs):
                        raise ValueError(f"{path}:{line_number}: duplicate RMS profile field")
                    window_ready = values

            mx_match = MX_PROFILE_RE.search(line)
            if mx_match:
                if current is not None:
                    records.append(finalize(current, peak))
                    current = None
                mx_record = dict(values)
                mx_record.update({
                    "source": str(path), "line": line_number, "format": mx_match.group(1),
                    "logical_ops": values.get("useful_ops", 0),
                    "total": values.get("cycles_total", 0),
                    "prepare_cache": values.get("activation_quant_pack", 0),
                })
                if window is not None:
                    if window_record is not None:
                        raise ValueError(f"{path}:{line_number}: duplicate MX profile in sample")
                    window_record = mx_record
                else:
                    mx_record["sample"] = len(unscoped_mx) + 1
                    mx_record["scope"] = "operator_only_unscoped"
                    unscoped_mx.append(finalize(mx_record, peak))
                continue
            match = PROFILE_RE.search(line)
            if not match:
                continue
            kind, payload = match.groups()
            values = {key: parse_value(value) for key, value in PAIR_RE.findall(payload)}
            if kind == "calls":
                if current is not None:
                    records.append(finalize(current, peak))
                sample += 1
                current = {"source": str(path), "sample": sample, "line": line_number}
            elif current is None:
                continue
            current.update(values)

    if window_packed_phase is not None:
        raise ValueError(f"{path}: packed-phase sample missing matching END")
    if window_ready is not None:
        raise ValueError(f"{path}: serial-ready sample missing matching END")
    if require_serial_ready and (not measured_serial_cases or measured_serial_ready != measured_serial_cases):
        raise ValueError(f"{path}: validated {measured_serial_ready}/{measured_serial_cases} measured serial cases; "
                         "require at least one and no missing serial-ready samples")
    if current is not None:
        records.append(finalize(current, peak))
    # Extra allocator/OOM profiles outside a fusion window are not samples.
    # Bare MX logs remain useful for independent operator measurements.
    if not has_windows:
        records.extend(unscoped_mx)
    return records


def number(record: dict[str, object], key: str) -> float:
    value = record.get(key, 0)
    return float(value) if isinstance(value, (int, float)) else 0.0


def finalize(record: dict[str, object], peak: float) -> dict[str, object]:
    logical_ops = number(record, "logical_ops")
    total = number(record, "total")
    tile_cycles = number(record, "ame_tile_call")
    tiles = number(record, "tiles")
    edge_tiles = number(record, "edge_tiles")
    phase_total = sum(number(record, phase) for phase in PHASES)
    if "format" in record:
        phase_total += number(record, "weight_prepare")

    record["peak_ops_per_cycle"] = peak
    record["operator_ops_per_cycle"] = logical_ops / total if total else 0.0
    record["operator_mfu_pct"] = logical_ops / total / peak * 100.0 if total and peak else 0.0
    record["macro_ops_per_cycle"] = logical_ops / tile_cycles if tile_cycles else 0.0
    record["macro_mfu_pct"] = logical_ops / tile_cycles / peak * 100.0 if tile_cycles and peak else 0.0
    graph_cycles = number(record, "whole_graph_cycles")
    if graph_cycles:
        record["whole_graph_mfu_pct"] = logical_ops / graph_cycles / peak * 100.0 if peak else 0.0
    record["edge_pct"] = edge_tiles / tiles * 100.0 if tiles else 0.0
    record["attributed_pct"] = phase_total / total * 100.0 if total else 0.0
    for phase in PHASES:
        record[f"{phase}_pct"] = number(record, phase) / total * 100.0 if total else 0.0
    if "format" in record:
        record["weight_prepare_pct"] = number(record, "weight_prepare") / total * 100.0 if total else 0.0
    return record


def markdown(records: list[dict[str, object]]) -> str:
    headers = [
        "source#sample", "ops (M)", "cycles (M)", "op/cyc", "op MFU",
        "macro op/cyc", "macro MFU", "prep", "pack A", "pack B", "tile",
        "init", "scale", "store", "edge", "attributed",
    ]
    show_graph = any("whole_graph_cycles" in record for record in records)
    show_mx = any("format" in record for record in records)
    if show_mx:
        headers.append("weight prep")
    if show_graph:
        headers.extend(["mode", "phase", "exact", "whole graph cycles (M)", "whole graph MFU"])
    rows = []
    for r in records:
        rows.append([
            f"{Path(str(r['source'])).name}#{r['sample']}",
            f"{number(r, 'logical_ops') / 1e6:.3f}",
            f"{number(r, 'total') / 1e6:.3f}",
            f"{number(r, 'operator_ops_per_cycle'):.2f}",
            f"{number(r, 'operator_mfu_pct'):.2f}%",
            f"{number(r, 'macro_ops_per_cycle'):.2f}",
            f"{number(r, 'macro_mfu_pct'):.2f}%",
            f"{number(r, 'prepare_cache_pct'):.2f}%",
            f"{number(r, 'pack_a_pct'):.2f}%",
            f"{number(r, 'pack_b_pct'):.2f}%",
            f"{number(r, 'ame_tile_call_pct'):.2f}%",
            f"{number(r, 'accumulator_initialization_pct'):.2f}%",
            f"{number(r, 'scale_pct'):.2f}%",
            f"{number(r, 'store_pct'):.2f}%",
            f"{number(r, 'edge_pct'):.2f}%",
            f"{number(r, 'attributed_pct'):.2f}%",
        ])
        if show_mx:
            rows[-1].append(f"{number(r, 'weight_prepare_pct'):.2f}%")
        if show_graph:
            rows[-1].extend([
                str(r.get("mode", "-")), str(r.get("phase", "-")),
                str(r.get("graph_exact", "-")),
                f"{number(r, 'whole_graph_cycles') / 1e6:.3f}" if "whole_graph_cycles" in r else "-",
                f"{number(r, 'whole_graph_mfu_pct'):.2f}%" if "whole_graph_cycles" in r else "-",
            ])
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    output.extend("| " + " | ".join(row) + " |" for row in rows)
    if show_mx:
        output.append(
            "\nMX macro MFU is a call-window metric, not array occupancy or an independent "
            "ready-input result; pipelined fusion excludes nested preparation from that window."
        )
    ready_records = [record for record in records if "first_panel_pack_cycles" in record]
    if ready_records:
        columns = (
            ("first panel pack", "first_panel_pack_cycles"),
            ("later panel pack", "post_first_panel_pack_cycles"),
            ("serial ready panels", "serial_ready_panels"),
            ("serial consumer", "serial_ready_consumer_cycles"),
            ("handoff envelope", "serial_ready_handoff_cycles"),
            ("tail consumer", "serial_ready_tail_consumer_cycles"),
            ("pair overage", "serial_pair_overage_cycles"),
            ("hideable ceiling", "serial_pair_hideable_ceiling_cycles"),
        )
        output.append("\nSerial-ready accounting (cycles unless a count):")
        output.append("\n| source#sample | " + " | ".join(label for label, _ in columns) + " |")
        output.append("| " + " | ".join(["---"] * (len(columns) + 1)) + " |")
        for record in ready_records:
            sample_label = f"{Path(str(record['source'])).name}#{record['sample']}"
            serial = record.get("mode") == "serial"
            values = [str(record[field]) if field in record and (serial or index < 2) else "-"
                      for index, (_, field) in enumerate(columns)]
            output.append("| " + " | ".join([sample_label, *values]) + " |")
        output.append("\nSerial consumer envelopes include synchronization, stores and scatter. "
                      "The ceiling is a serial-accounting estimate, not measured PE/RVV overlap.")
    packed_records = [record for record in records if "packed_phase_scope" in record]
    if packed_records:
        columns = (*PACKED_PHASE_TIMERS, "prepare_minus_sum_cycles")
        output.append("\nPacked preparation diagnostics (raw cycles):")
        output.append("\n| source#sample | " + " | ".join(columns) + " |")
        output.append("| " + " | ".join(["---"] * (len(columns) + 1)) + " |")
        for record in packed_records:
            sample_label = f"{Path(str(record['source'])).name}#{record['sample']}"
            values = [str(record.get(f"packed_phase_{field}", "-")) for field in columns]
            output.append("| " + " | ".join([sample_label, *values]) + " |")
        output.append("\nThe signed remainder is shown only for fused samples with all calls packed and no fallbacks. "
                      "Timers include diagnostic overhead, omit unfused RMS, and do not measure overlap.")
    return "\n".join(output)


def csv_output(records: list[dict[str, object]]) -> None:
    keys = sorted({key for record in records for key in record})
    writer = csv.DictWriter(sys.stdout, fieldnames=keys)
    writer.writeheader()
    writer.writerows(records)


def collect_prefill(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=f"{Path(sys.argv[0]).name} collect-prefill",
                                     description="Import an accepted MXMODEL_AB terminal receipt.")
    parser.add_argument("raw", type=Path)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--tag", choices=("MXModelActivation", "MXModelWeight"), required=True)
    parser.add_argument("--select", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--result-receipt", type=Path, required=True)
    parser.add_argument("--collector-receipt", type=Path, help="verify the recorded runner SHA-256 against these bytes")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args(argv)

    def require(condition, message):
        if not condition:
            raise ValueError(message)

    def unique_pairs(pairs):
        values = dict(pairs)
        require(len(values) == len(pairs), "duplicate field")
        return values

    def fields(tokens):
        matches = [PAIR_RE.fullmatch(token) for token in tokens]
        require(all(matches), f"malformed key=value fields: {' '.join(tokens)}")
        return unique_pairs([match.groups() for match in matches])

    def one(matches, label):
        require(len(matches) == 1, f"expected one {label}, found {len(matches)}")
        return matches[0]

    def actual_domains(marker):
        parsed = fields(marker[1:])
        domain_sets = {}
        for piece in parsed.get("domains", "").split("+"):
            match = re.fullmatch(r"([0-7])(?:\.([0-7])(?:-\1\.([0-7]))?)?", piece)
            require(match, "malformed actual placement")
            board, start, end = match.groups()
            lanes = set(range(int(start or 0), int(end or start or 7) + 1))
            previous = domain_sets.setdefault(board, set())
            require(lanes and not previous & lanes, "overlapping or reversed placement")
            previous.update(lanes)
        require(parsed.get("prefix") and sorted(map(len, domain_sets.values())) == [7, 8], "expected 15 actual domains")
        return parsed["domains"]

    try:
        require((args.ledger is None) == (args.manifest is None), "need both --manifest and --ledger")
        selector = fields(args.select)
        activation = args.tag == "MXModelActivation"
        shape_fields = ("N", "K", "tile_k", "tile_mn") + (() if activation else ("M", "stride"))
        require(selector.keys() <= set(shape_fields), "--select only accepts fixture shape fields")
        result = json.loads(args.sidecar.read_bytes(), object_pairs_hook=unique_pairs)
        require(isinstance(result, dict) and result.get("version") == 2 and result.get("kind") == "result",
                "expected a v2 result sidecar")
        require(all(key in result for key in ("model", "manifest_sha256", "mechanism", "id", "scope", "input",
                    "state", "comparison_only", "phase_off", "candidate_sha256", "entry_state", "path_hit")),
                "incomplete result sidecar")
        require(result["scope"] == "leaf", "these fixture timers do not measure the complete operator")
        require(activation or result["comparison_only"] is True, "weight-file fixture is only a comparison screen")
        raw_path = args.raw.resolve()
        raw = raw_path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        lines = [line.strip() for line in raw.decode().splitlines() if line.strip()]
        job = one([line for line in lines if line.startswith("job-")], "raw job ID")
        require(re.fullmatch(r"job-[A-Za-z0-9_-]+", job) and result.get("job_id") == job, "sidecar job mismatch")
        receipt = [line.split() for line in args.result_receipt.read_text(encoding="utf-8").splitlines()]
        terminal = fields(one([row for row in receipt if any(token.startswith("job=") for token in row)],
                              "job terminal receipt"))
        require((terminal.get("job"), terminal.get("state"), terminal.get("exit_code")) == (job, "completed", "0"),
                "job terminal not completed with exit 0")
        pinned = fields(one([row for row in receipt if any(token.startswith("raw=") for token in row)], "raw pin"))
        require(pinned.get("sha256") == digest and re.fullmatch(re.escape(args.raw.name) + r"(?::[1-9]\d*(?:,[1-9]\d*)*)?",
                                                               pinned["raw"]), "raw receipt filename or SHA-256 mismatch")
        status = fields(one([row for row in receipt if row and row[0].startswith("placement=")], "release receipt"))
        require(all(status.get(key) == value for key, value in (("release_domains", "15,15"), ("guest_exit", "0,0"),
                    ("runtime_exit", "0,0"), ("local_follow_exit", "0"))), "release or exit receipt failed")
        payload_rows = [row for row in receipt if any(token.startswith(("a_bin_sha256=", "b_bin_sha256=")) for token in row)]
        payloads = fields(one(payload_rows, "payload pins")) if payload_rows else {}
        header = fields(lines[0].split())
        logger_model = header.get("model")
        validated_models = ("stories", "stories-k288-copy", "qwen", "qwen-qcur-batch8", "qwen-qcur-guard-pack")
        require(logger_model in (validated_models if activation else ("qwen-weight-file",)),
                "tag not validated by this MXMODEL_AB collector branch")
        require(header.get("action") == "run" and
                re.fullmatch(r"[0-9a-f]{64}", header.get("runner_sha256", "")), "missing run/collector identity")
        if args.collector_receipt:
            require(hashlib.sha256(args.collector_receipt.read_bytes()).hexdigest() == header["runner_sha256"],
                    "collector SHA-256 mismatch")

        arm_tags = ("MXMODEL_AB_START", "R75_PREFILL_ACTUAL_PLACEMENT", "MXMODEL_AB_ARM_PASS")
        finish_tag = "MXMODEL_AB_FINISHED"
        markers = [(index, line.split()) for index, line in enumerate(lines)
                   if line.split(maxsplit=1)[0] in (*arm_tags, finish_tag)]
        require(tuple(row[0] for _, row in markers) == arm_tags * 2 + (finish_tag,)
                and lines.index(job) < markers[0][0], "invalid or duplicate A/B markers")
        samples = [(line_number, line) for line_number, line in enumerate(lines) if line.split(maxsplit=1)[0] == args.tag]
        require(all(any(markers[offset][0] < line_number < markers[offset + 1][0] for offset in (0, 3))
                    for line_number, _ in samples), "fixture row outside A/B window")
        finish = fields(markers[-1][1][1:])
        placement, work = [], []
        for index, name in enumerate(("baseline", "candidate")):
            (start, start_row), (placed, actual_row), (_, pass_row) = markers[index * 3:index * 3 + 3]
            start_fields, passed = fields(start_row[1:]), fields(pass_row[1:])
            require(all((values.get("model"), values.get("arm")) == (logger_model, str(index))
                        for values in (start_fields, passed)) and passed.get("release_domains") == "15",
                    f"{name}: invalid arm identity or release")
            domain = actual_domains(actual_row)
            placement.append(domain)
            arm_lines = lines[start + 1:placed]
            summary = f"{args.tag} PASS errors=0"
            done = one([line_number for line_number, line in samples if start < line_number < placed and line == summary],
                       f"{name} fixture PASS")
            exits = [line for line in arm_lines if line.startswith("Exit with code =")]
            require(exits == ["Exit with code = 0"] and start + 1 + arm_lines.index(exits[0]) > done
                    and not any("BAD TRAP" in line.upper() for line in arm_lines), f"{name}: invalid guest exit")
            selected = []
            for line_number, line in samples:
                if not start < line_number < placed or line == summary:
                    continue
                row = line.split()
                require(row[-1] == "PASS" and line_number < done, f"{name}: invalid fixture row")
                values = fields(row[1:-1])
                require(values.get("phase") in ("warmup", "measure", "fallback", "smoke")
                        and all(re.fullmatch(r"[1-9][0-9]*", values.get(key, "")) for key in shape_fields)
                        and re.fullmatch(r"0|[1-9][0-9]*", values.get("sample", ""))
                        and re.fullmatch(r"[1-9][0-9]{0,19}", values.get("cycles", ""))
                        and int(values["cycles"]) < 2 ** 64, f"{name}: malformed fixture sample")
                if values["phase"] in ("warmup", "measure") and all(values.get(key) == value for key, value in selector.items()):
                    selected.append(values)
            warmups = sum(row["phase"] == "warmup" for row in selected)
            shapes = {tuple(row.get(key) for key in shape_fields) for row in selected}
            require(len(shapes) == 1 and len(selected) - warmups >= 3 and all(row["sample"] == str(sample_index)
                    and row["phase"] == ("warmup" if sample_index < warmups else "measure")
                    for sample_index, row in enumerate(selected)),
                    f"{name}: ambiguous or incomplete timing samples; select one fixture shape")
            cycles = [int(row.pop("cycles")) for row in selected][warmups:]
            work.append(selected)
            arm = result.get(name)
            require(isinstance(arm, dict), f"{name}: missing sidecar arm identity")
            if payload_rows:
                require(payloads.get(f"{'ab'[index]}_bin_sha256", "") == arm.get("payload_sha256"),
                        f"{name}: payload identity differs from terminal receipt")
            arm.update(cycles=cycles, warmups=warmups, placement=domain,
                       receipt=str(raw_path), receipt_sha256=digest)

        matched = placement[0] == placement[1]
        match_status = "matched" if matched else "not_matched"
        require(work[0] == work[1] and finish.get("model") == logger_model and finish.get("phase") == "screen"
                and finish.get("raw_cycles") == ("available" if matched else "diagnostic")
                and finish.get("placement") == status.get("placement") == match_status
                and (not matched or status.get("actual_domains") == placement[0]), "A/B work or terminal placement mismatch")
        result.update(metric="dut_cycles", work_equal=True, correctness=True, terminal=True, released=True)
        output = json.dumps(result, sort_keys=True, allow_nan=False)
        if args.ledger is not None:
            guard = Path(__file__).resolve().parents[4] / "scripts" / "agent-workflow-guard.py"
            return subprocess.run([sys.executable, guard, "record", "-", "--manifest", args.manifest,
                                   "--ledger", args.ledger], input=output + "\n", text=True).returncode
        print(output)
        return 0
    except (OSError, ValueError) as error:
        parser.error(str(error))


def main() -> int:
    if sys.argv[1:2] == ["collect-prefill"]:
        return collect_prefill(sys.argv[2:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--peak-ops-per-cycle", type=float, required=True)
    parser.add_argument("--format", choices=("markdown", "json", "csv"), default="markdown")
    parser.add_argument("--require-serial-ready", action="store_true",
                        help="require a serial-ready window for every measured serial CASE in each input (at least one)")
    args = parser.parse_args()

    records = []
    for path in args.logs:
        try:
            parsed = parse_file(path, args.peak_ops_per_cycle, require_serial_ready=args.require_serial_ready)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        records.extend(parsed)
    complete = [record for record in records if number(record, "total") and number(record, "logical_ops")]
    if not complete:
        print("no complete [AME_PROFILE] groups found", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(complete, indent=2, sort_keys=True))
    elif args.format == "csv":
        csv_output(complete)
    else:
        print(markdown(complete))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
