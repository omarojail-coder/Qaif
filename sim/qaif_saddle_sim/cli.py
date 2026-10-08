"""Command-line runner: python -m qaif_saddle_sim.cli simulate ..."""

from __future__ import annotations

import argparse
import json

from .io import simulate_to_directory
from .experiment import make_pair
from .timeline import make_timeline_pair
from .reference_episode import prepare_reference_episode
from .reference_sources import fetch_reference_sources
from .audit_reference import audit_reference
from .pressure_profile import PRESSURE_MODES


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Qaif saddle simulation channels")
    subcommands = parser.add_subparsers(dest="command", required=True)
    simulate = subcommands.add_parser("simulate")
    simulate.add_argument("--config", required=True)
    simulate.add_argument("--forcing", required=True)
    simulate.add_argument("--out", required=True)
    simulate.add_argument("--seed", type=int, default=42)
    simulate.add_argument("--extensions", help="optional gas/crack research configuration")
    simulate.add_argument("--extension-forcing", help="timestamp-aligned gas/crack forcing CSV")
    pair = subcommands.add_parser("pair", help="matched baseline and intervention")
    pair.add_argument("--config", required=True)
    pair.add_argument("--forcing", required=True)
    pair.add_argument("--intervention", required=True)
    pair.add_argument("--out", required=True)
    pair.add_argument("--seed", type=int, default=42)
    timeline = subcommands.add_parser("timeline", help="multi-phase matched baseline and intervention")
    timeline.add_argument("--config", required=True)
    timeline.add_argument("--forcing", required=True)
    timeline.add_argument("--timeline", required=True)
    timeline.add_argument("--out", required=True)
    timeline.add_argument("--seed", type=int, default=42)
    fetch = subcommands.add_parser("fetch-reference", help="archive pinned public inputs")
    fetch.add_argument("--out", required=True)
    fetch.add_argument("--insecure-gaslib", action="store_true",
                       help="only when local CA store cannot verify gaslib.zib.de; recorded in manifest")
    fetch.add_argument("--append", action="store_true", help="verify existing files and fetch missing episodes")
    prepare = subcommands.add_parser("prepare-reference", help="build sourced baseline forcing")
    prepare.add_argument("--sources", required=True)
    prepare.add_argument("--episode", required=True)
    prepare.add_argument("--template", required=True)
    prepare.add_argument("--gas-assumptions", required=True)
    prepare.add_argument("--window-start-utc", help="YYYYMMDDHH within archived annual episode")
    prepare.add_argument("--window-hours", type=int)
    prepare.add_argument("--pressure-mode", choices=PRESSURE_MODES,
                         default="periodic_benchmark_surrogate")
    prepare.add_argument("--ntsb-pressure-dir", help="verified channel directory containing pressure.csv and manifest.json")
    prepare.add_argument("--ntsb-start-local", help="source-local YYYY-MM-DD HH:00; no UTC conversion")
    prepare.add_argument("--out", required=True)
    audit = subcommands.add_parser("audit-reference", help="audit one sourced simulation")
    audit.add_argument("--prepared", required=True)
    audit.add_argument("--simulated", required=True)
    args = parser.parse_args()
    if args.command == "simulate":
        if bool(args.extensions) != bool(args.extension_forcing):
            parser.error("--extensions and --extension-forcing must be supplied together")
        if args.extensions:
            from .extensions.integration import simulate_extended_to_directory
            manifest = simulate_extended_to_directory(args.config, args.forcing,
                args.extensions, args.extension_forcing, args.out, args.seed)
        else:
            manifest = simulate_to_directory(args.config, args.forcing, args.out, args.seed)
        print(json.dumps({
            "output_dir": args.out,
            "sample_count": manifest["sample_count"],
            "training_ready": manifest["training_ready"],
        }))
    elif args.command == "pair":
        manifest = make_pair(args.config, args.forcing, args.intervention, args.out, args.seed)
        print(json.dumps({
            "output_dir": args.out,
            "event_type": manifest["event_type"],
            "split_group": manifest["split_group"],
            "training_ready": manifest["training_ready"],
        }))
    elif args.command == "timeline":
        manifest = make_timeline_pair(args.config, args.forcing, args.timeline, args.out, args.seed)
        print(json.dumps({
            "output_dir": args.out,
            "mechanism_id": manifest["mechanism_id"],
            "phase_sample_counts": manifest["phase_sample_counts"],
            "split_group": manifest["split_group"],
            "training_ready": manifest["training_ready"],
        }))
    elif args.command == "fetch-reference":
        manifest = fetch_reference_sources(args.out, insecure_gaslib=args.insecure_gaslib,
                                           append=args.append)
        print(json.dumps({"output_dir": args.out,
                          "source_count": len(manifest["entries"])}))
    elif args.command == "prepare-reference":
        manifest = prepare_reference_episode(args.sources, args.episode,
                                             args.template, args.out,
                                             args.gas_assumptions,
                                             window_start_utc=args.window_start_utc,
                                             window_hours=args.window_hours,
                                             pressure_mode=args.pressure_mode,
                                             ntsb_pressure_dir=args.ntsb_pressure_dir,
                                             ntsb_start_local=args.ntsb_start_local)
        print(json.dumps({"output_dir": args.out,
                          "sample_count": manifest["sample_count"],
                          "training_ready": manifest["training_ready"]}))
    elif args.command == "audit-reference":
        print(json.dumps(audit_reference(args.prepared, args.simulated),
                         indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
