#!/usr/bin/env python3
"""Read-only CryoSPARC v5 ancestry export (Python 3.9+)."""
import argparse
import getpass
import json
import math
import re
import sys
import warnings
from collections import defaultdict
from datetime import datetime, timezone
from graphlib import TopologicalSorter
from pathlib import Path

import os

DEFAULT_HOST = os.getenv("DEFAULT_HOST", "localhost")
DEFAULT_PORT = int(os.getenv("DEFAULT_PORT", "61000"))


def uid_arg(prefix):
    def parse(value):
        value = value.strip().upper()
        if not re.fullmatch(prefix + r"\d+", value):
            raise argparse.ArgumentTypeError(f"Expected {prefix} followed by digits")
        return value
    return parse


def port_arg(value):
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Port must be an integer from 1 to 65535")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", metavar="PROJECTID", type=uid_arg("P"))
    parser.add_argument("job", metavar="JOBID", type=uid_arg("J"))
    parser.add_argument("-u", "--username", help="CryoSPARC login email (prompt if omitted)")
    parser.add_argument("-p", "--password", help="Password (prefer hidden prompt; command-line passwords may be visible)")
    parser.add_argument("-ip", "--ip", default=DEFAULT_HOST, help=f"Host (default: {DEFAULT_HOST})")
    parser.add_argument("-port", "--port", type=port_arg, default=DEFAULT_PORT, help=f"Base port (default: {DEFAULT_PORT})")
    return parser.parse_args(argv)


def collect_ancestors(cs, project, target):
    """Follow actual input connections and recorded parents, not clone links."""
    jobs, edges = {}, set()
    pending = [target]
    extra_parents = 0
    while pending:
        uid = pending.pop()
        if uid in jobs:
            continue
        job = cs.find_job(project, uid)
        model = job.model
        recorded = set(model.parents or [])
        jobs[uid] = {
            "uid": uid, "type": job.type, "title": job.title,
            "status": job.status, "workspaces": model.workspace_uids,
            "params": job.params.model_dump(mode="json"),
            "inputs": {name: inp.model_dump(mode="json") for name, inp in job.inputs.items()},
            "outputs": {name: out.model_dump(mode="json") for name, out in job.outputs.items()},
        }
        connected = set()
        for input_name, inp in job.inputs.items():
            for connection in inp.connections:
                parent = connection.job_uid
                source_project = getattr(connection, "project_uid", None)
                if source_project and source_project != project:
                    raise RuntimeError(f"Cross-project dependency {source_project}-{parent}; this exporter supports one project")
                connected.add(parent)
                edges.add((parent, uid, connection.output, input_name))
        # Retain recorded dependencies even if individual ports are unavailable.
        for parent in recorded - connected:
            edges.add((parent, uid, "", ""))
            extra_parents += 1
        jobs[uid]["parents"] = sorted(recorded | connected)
        pending.extend(sorted((recorded | connected) - jobs.keys(), reverse=True))
    return jobs, edges, extra_parents

KEYWORDS = (
    "psize",
    "pixel",
    "voltage",
    "kv",
    "cs_mm",
    "aberration",
    "dose",
    "exposure",
    "diameter",
    "box",
    "crop",
    "binning",
    "downsample",
    "defocus",
    "astigmatism",
    "threshold",
    "class",
    "symmetry",
    "resolution",
    "resol",
    "fsc",
    "iteration",
    "mask",
    "filter",
    "particle",
    "batch",
    "motion",
    "bfactor",
    "b_factor",
    "amplitude",
    "fraction",
    "min_res",
    "max_res",
    "refine"
)


def unwrap_parameters(parameters):
    """
    Extract parameter values while preserving original names.
    """
    return {
        key: (
            value["value"]
            if isinstance(value, dict) and "value" in value
            else value
        )
        for key, value in parameters.items()
    }


def extract_critical_parameters(parameters):
    """
    Convenience subset of scientifically relevant parameters.
    All parameters are retained separately.
    """
    return {
        key: value
        for key, value in parameters.items()
        if any(keyword in key.lower() for keyword in KEYWORDS)
    }


def extract_output_metadata(output):
    """
    Preserve the native CryoSPARC output count and statistics.
    """
    return {
        "title": output.get("title"),
        "type": output.get("type"),
        "description": output.get("description"),
        "num_items": output.get("num_items"),
        "passthrough": output.get("passthrough"),
        "summary": output.get("summary", {}),
        "latest_summary_stats": output.get(
            "latest_summary_stats", {}
        )
    }


def sanitize_json(value):
    if isinstance(value, dict):
        cleaned = {}

        for key, val in value.items():
            if "signature" in str(key).lower():
                continue

            val = sanitize_json(val)

            if val is not None:
                cleaned[str(key)] = val

        return cleaned

    if isinstance(value, (list, tuple, set)):
        cleaned = [sanitize_json(val) for val in value]
        return [val for val in cleaned if val is not None]

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return value


def flatten_dict(data, prefix=""):
    for key, value in data.items():

        path = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            yield from flatten_dict(value, path)
        else:
            yield path, value


def clean(data):
    """
    Recursively remove null values, empty containers,
    non-finite numbers and signatures.
    """

    if isinstance(data, dict):

        result = {}

        for key, value in data.items():

            if "signature" in str(key).lower():
                continue

            value = clean(value)

            if value is not None:
                result[key] = value

        return result or None

    if isinstance(data, (list, tuple)):

        result = [clean(value) for value in data]
        result = [value for value in result if value is not None]

        return result or None

    if isinstance(data, float) and not math.isfinite(data):
        return None

    return data


def get_counts(outputs, dtype):
    """
    Preserve individual output counts.
    Never sum potentially overlapping datasets.
    """

    return {
        name: output["num_items"]
        for name, output in outputs.items()
        if output.get("type") == dtype
        and output.get("num_items") is not None
    }


def get_symmetry(parameters):
    """
    Extract explicitly recorded point-group symmetry.
    """

    preferred_keys = (
        "refine_symmetry",
        "symmetry",
        "sym_expand_symmetry",
        "symmetry_expand_symmetry",
        "abinit_symmetry"
    )

    for key in preferred_keys:

        value = parameters.get(key)

        if isinstance(value, dict):
            value = value.get("value")

        if isinstance(value, str) and re.fullmatch(
            r"(?:[CD]\d+|[TOI](?:[1-4])?)",
            value.upper()
        ):
            return value.upper()

    return None


def get_resolution(outputs):
    """
    Extract reported resolution statistics from volume outputs.

    Do not use resolution-related processing parameters,
    such as initial lowpass or alignment resolution.
    """

    resolutions = {}

    accepted_keys = {
        "resolution",
        "resolution_a",
        "resolution_angstrom",
        "resolution_angstroms",
        "fsc_resolution",
        "fsc_res",
        "gsfsc_resolution",
        "gsfsc_res",
        "fsc_resolution_0143",
        "resolution_0143",
        "res_0143",
        "fsc_0143",
        "radwn_final_a"
    }

    for name, output in outputs.items():

        if output.get("type") not in ("volume", "volume_multi"):
            continue

        for section in ("summary", "latest_summary_stats"):

            stats = output.get(section) or {}

            for path, value in flatten_dict(stats):

                key = path.split(".")[-1].lower()

                if key not in accepted_keys:
                    continue

                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(value)
                    and value > 0
                ):
                    resolutions[f"{name}.{path}"] = round(value, 3)

    return resolutions or None


def build_complete(project, target, jobs, edges):
    parents, children = defaultdict(set), defaultdict(set)
    incoming, outgoing = defaultdict(list), defaultdict(list)
    for source, dest, output, input_name in sorted(edges):
        parents[dest].add(source)
        children[source].add(dest)
        incoming[dest].append({"job": source, "output": output, "input": input_name})
        outgoing[source].append({"job": dest, "output": output, "input": input_name})
    graph = {uid: sorted(parents[uid]) for uid in sorted(jobs, key=lambda x: int(x[1:]))}
    job_order = list(TopologicalSorter(graph).static_order())
    provenance = {
        "schema_version": "1.0", "source": "CryoSPARC",
        "project": project, "target_job": target,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "number_of_jobs": len(jobs), "number_of_connections": len(edges),
        "root_jobs": [uid for uid in job_order if not parents[uid]],
        "movie_import_jobs": [uid for uid in job_order if jobs[uid]["type"] == "import_movies"],
        "micrograph_import_jobs": [uid for uid in job_order if jobs[uid]["type"] == "import_micrographs"],
        "job_order": job_order, "jobs": {},
    }
    for step, uid in enumerate(job_order):
        job = jobs[uid]
        parameters = unwrap_parameters(job["params"])
        input_metadata = defaultdict(list)
        for conn in incoming[uid]:
            source, output_name = conn["job"], conn["output"]
            source_output = jobs[source]["outputs"].get(output_name, {})
            input_metadata[conn["input"]].append({
                "source_job": source, "source_output": output_name,
                "type": source_output.get("type"),
                "source_output_num_items": source_output.get("num_items"),
                "summary": source_output.get("summary", {}),
            })
        output_metadata = {}
        counts = defaultdict(dict)
        for name, output in job["outputs"].items():
            metadata = extract_output_metadata(output)
            consumers = [conn for conn in outgoing[uid] if conn["output"] == name]
            metadata["used_downstream"] = bool(consumers)
            metadata["downstream_connections"] = consumers
            output_metadata[name] = metadata
            counts[metadata["type"] or "unknown"][name] = metadata["num_items"]
        provenance["jobs"][uid] = {
            "step": step, "job_uid": uid, "job_type": job["type"],
            "title": job["title"], "status": job["status"], "workspaces": job["workspaces"],
            "parents": sorted(parents[uid]), "children": sorted(children[uid]),
            "metadata": {"critical_parameters": extract_critical_parameters(parameters), "all_parameters": parameters},
            "inputs": dict(input_metadata),
            "results": {"counts": dict(counts), "outputs": output_metadata},
            "connections": {"incoming": incoming[uid], "outgoing": outgoing[uid]},
            "raw_metadata": {"parameters": job["params"], "inputs": job["inputs"], "outputs": job["outputs"]},
        }
    provenance["edges"] = [
        {"source": source, "target": dest, "source_output": output, "target_input": input_name}
        for source, dest, output, input_name in sorted(edges)
    ]
    return sanitize_json(provenance)


def build_compact(provenance):
    compact = {key: provenance[key] for key in ("project", "target_job", "number_of_jobs")}
    compact["jobs"] = {}
    missing_resolution, missing_symmetry = [], []
    for uid in provenance["job_order"]:
        job = provenance["jobs"][uid]
        job_type = job["job_type"]
        parameters = job["metadata"]["all_parameters"]
        outputs = job["results"]["outputs"]
        record = {"job_type": job_type, "workspaces": job.get("workspaces", []), "parents": job["parents"]}
        stats = {}
        if job_type == "import_movies":
            stats["movies"] = get_counts(outputs, "exposure")
        elif (job_type == "import_micrographs" or "patch_motion" in job_type
              or "patch_ctf" in job_type or "exposure" in job_type):
            stats["micrographs"] = get_counts(outputs, "exposure")
        elif "picker" in job_type or "inspect_picks" in job_type:
            pass
        elif ("refine" in job_type and not job_type.startswith("ctf_")) or "abinit" in job_type:
            stats["particles"] = get_counts(outputs, "particle")
            stats["resolution_A"] = get_resolution(outputs)
            stats["symmetry"] = get_symmetry(parameters)
            if stats["resolution_A"] is None:
                missing_resolution.append(uid)
            if stats["symmetry"] is None:
                missing_symmetry.append(uid)
        elif job_type == "sym_expand":
            stats["particles"] = get_counts(outputs, "particle")
            stats["symmetry"] = get_symmetry(parameters)
        else:
            stats["particles"] = get_counts(outputs, "particle")
        if clean(stats):
            record["statistics"] = clean(stats)
        compact["jobs"][uid] = record
    return compact, missing_resolution, missing_symmetry


def write_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, allow_nan=False, default=str)
        f.write("\n")


def main(argv=None):
    args = parse_args(argv)
    try:
        from cryosparc.tools import CryoSPARC
    except ImportError:
        print("Error: create and activate the Conda environment (conda env create -f environment.yml; conda activate get_cs_tree)", file=sys.stderr)
        return 1
    try:
        username = args.username if args.username is not None else input("CryoSPARC email: ").strip()
        # Fail rather than fall back to visible password entry on noninteractive stdin.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = args.password if args.password is not None else getpass.getpass("CryoSPARC password: ")
        if not username or not password:
            raise ValueError("Email and password must not be empty")
        cs = CryoSPARC(host=args.ip, base_port=args.port, email=username, password=password)
        if not cs.test_connection():
            raise RuntimeError("CryoSPARC connection failed")
        print(f"Retrieving ancestry of {args.project}-{args.job} ...", flush=True)
        jobs, edges, extra_parents = collect_ancestors(cs, args.project, args.job)
        complete = build_complete(args.project, args.job, jobs, edges)
        compact, missing_res, missing_sym = build_compact(complete)
        prefix = f"{args.project}_{args.job}"
        out = Path(f"{prefix}_provenance")
        out.mkdir(exist_ok=True)
        for variant, data in (("complete", complete), ("compact", compact)):
            write_json(out / f"{prefix}_{variant}_provenance.json", data)
        print(f"Exported {len(jobs)} jobs, {len(edges)} connections to {out}/")
        if extra_parents:
            print(f"Note: {extra_parents} recorded dependencies have no explicit port connection.", file=sys.stderr)
        if missing_res or missing_sym:
            print(f"Note: resolution unavailable for {len(missing_res)} refinement jobs; symmetry unavailable for {len(missing_sym)}.", file=sys.stderr)
        return 0
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        # Avoid printing raw authentication exceptions, which may contain secrets.
        print(f"Error: {type(exc).__name__}: {str(exc).replace(password, '[redacted]') if 'password' in locals() and password else str(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
