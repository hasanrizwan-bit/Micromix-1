#!/usr/bin/env python3
"""Deterministic synthetic dataset generator for the Micromix scalability benchmarks.

Produces, for each sample count S (default 32, 100, 250, 500, 1000):

* ``legacy_wide_S{S}.tsv``      -- legacy session workflow input (POST /upload).
  Tab-separated, one row per gene, columns ``Locus Tag``, ``Name`` followed by
  S integer count columns. Mirrors the bundled ``static/*.tsv`` layout
  (e.g. ``salmonella_salcom_complete_tpm.tsv``). No missing values: the legacy
  parser (``experimental_features.adjust_numeric_dtype``) fills NaN with
  ``min - 1``, so missing values would silently become fake counts.
* ``orthology_expression_long_S{S}.tsv`` -- orthology expression import input
  (POST /orthogroup_imports/<rid>/expression_upload). Long/tidy, one row per
  (strain gene, sample) measurement, columns drawn from
  ``orthology.schema.EXPRESSION_KNOWN_COLUMNS`` and mirroring
  ``MultiStrain/outputs/expression/orthogroup_expression_long.tsv``.

and once (shared by every size):

* ``orthology_reference.tsv``   -- orthogroup reference table
  (POST /upload_orthogroups), columns from ``orthology.schema.KNOWN_COLUMNS``.

Design (all fixed by ``--seed``):

* 6,000 orthogroups; 8 strains; 85 % core orthogroups present in all strains,
  15 % accessory present in 1-7 strains (-> structurally missing matrix cells);
  3 % paralog orthogroups with 2 copies in 1-3 strains (``copies_in_strain``=2).
* Samples are assigned condition-major, then strain, then replicate (2 reps),
  i.e. conditions = ceil(S / 16). Sample ids look like ``S03 C012 R2``.
  Each sample belongs to exactly one strain (as in the Pseudomonas data).
* Counts: negative-binomial (gamma-Poisson). Per-gene means are log-normal
  (median ~150, matching the Pseudomonas reference median 138), per-gene
  dispersion 0.05-0.4, per-sample library-size factor log-normal(0, 0.25),
  8 % of genes respond to each condition (log2FC ~ N(0, 1.5)), 2 % of genes are
  zero-inflated (50 % extra zeros).
* 0.5 % of orthology measurement rows are randomly dropped (missing
  measurements), in addition to structural absences.
* Per-sample random streams come from ``SeedSequence(seed, spawn_key=(j,))``,
  so sample j is identical across all dataset sizes (nested datasets).

Usage::

    python generate_datasets.py                 # all default sizes
    python generate_datasets.py --sizes 32 100  # subset
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
GENERATOR_VERSION = "1.0.0"
DEFAULTS = dict(
    seed=20261119,
    n_orthogroups=6000,
    n_strains=8,
    n_replicates=2,
    core_fraction=0.85,
    paralog_fraction=0.03,
    condition_responsive_fraction=0.08,
    zero_inflated_fraction=0.02,
    row_dropout_fraction=0.005,
    lib_size_sdlog=0.25,
    mean_log_median=150.0,
    mean_log_sd=1.5,
)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Static (size-independent) structure
# ---------------------------------------------------------------------------

def build_reference(p):
    rng = np.random.default_rng(np.random.SeedSequence(p["seed"], spawn_key=(10_000_000,)))
    G, K = p["n_orthogroups"], p["n_strains"]
    strains = [f"Syn.S{k + 1:02d}" for k in range(K)]
    og_ids = [f"OG{g + 1:06d}" for g in range(G)]

    presence = np.ones((G, K), dtype=bool)
    accessory = rng.random(G) >= p["core_fraction"]
    for g in np.flatnonzero(accessory):
        n_present = rng.integers(1, K)  # 1..K-1
        keep = rng.choice(K, size=n_present, replace=False)
        presence[g] = False
        presence[g, keep] = True

    copies = presence.astype(int)
    paralog = rng.random(G) < p["paralog_fraction"]
    for g in np.flatnonzero(paralog):
        present = np.flatnonzero(presence[g])
        n_par = min(len(present), rng.integers(1, 4))
        for k in rng.choice(present, size=n_par, replace=False):
            copies[g, k] = 2

    # OG-level annotation and mean expression.
    og_mu = np.exp(np.log(p["mean_log_median"]) + p["mean_log_sd"] * rng.standard_normal(G))
    og_mu = np.clip(og_mu, 0.5, 2e5)
    gene_names = [f"syn{g + 1:04d}" if rng.random() < 0.4 else "" for g in range(G)]
    products = [f"Synthetic protein family {g % 997 + 1}" for g in range(G)]
    prot_len = rng.integers(60, 1200, size=G)

    rows = []
    peg_counter = [0] * K
    for g in range(G):
        species_count = int(presence[g].sum())
        gene_count = int(copies[g].sum())
        for k in range(K):
            for c in range(copies[g, k]):
                peg_counter[k] += 1
                start = peg_counter[k] * 1000 + int(rng.integers(0, 500))
                rows.append({
                    "orthogroup_id": og_ids[g], "strain": strains[k],
                    "seed_peg": f"peg.{peg_counter[k]}", "copy_index": c + 1,
                    "copies_in_strain": int(copies[g, k]), "species_count": species_count,
                    "gene_count": gene_count, "gene": gene_names[g], "product": products[g],
                    "contig": f"Syn._S{k + 1:02d}", "start": start,
                    "end": start + 3 * int(prot_len[g]), "strand": "+" if rng.random() < 0.5 else "-",
                    "protein_length": int(prot_len[g]),
                    "_g": g, "_k": k,
                })
    ref = pd.DataFrame(rows)
    # Per-gene (strain-specific) mean = OG mean x strain jitter; dispersion; ZI flag.
    n = len(ref)
    ref["_mu"] = og_mu[ref["_g"].to_numpy()] * np.exp(0.3 * rng.standard_normal(n))
    ref["_phi"] = rng.uniform(0.05, 0.4, size=n)
    ref["_zi"] = rng.random(n) < p["zero_inflated_fraction"]
    # Legacy (single organism) gene table re-uses the OG means.
    legacy = pd.DataFrame({
        "Locus Tag": [f"SYN_{g + 1:05d}" for g in range(G)],
        "Name": [gene_names[g] or f"SYN_{g + 1:05d}" for g in range(G)],
        "_mu": og_mu, "_phi": rng.uniform(0.05, 0.4, size=G),
        "_zi": rng.random(G) < p["zero_inflated_fraction"],
    })
    return strains, ref, legacy


def sample_design(S, strains, n_reps):
    K = len(strains)
    n_cond = math.ceil(S / (K * n_reps))
    design = []
    for c in range(n_cond):
        for k in range(K):
            for r in range(n_reps):
                if len(design) < S:
                    design.append({
                        "sample_id": f"S{k + 1:02d} C{c + 1:03d} R{r + 1}",
                        "strain": strains[k], "strain_idx": k,
                        "condition": f"condition {c + 1:03d}", "cond_idx": c,
                        "replicate": str(r + 1),
                    })
    return design


def condition_effects(p, n_genes, n_cond, key):
    """log2 fold change per (gene, condition); deterministic per condition."""
    eff = np.zeros((n_genes, n_cond))
    for c in range(n_cond):
        rng = np.random.default_rng(np.random.SeedSequence(p["seed"], spawn_key=(key, c)))
        responsive = rng.random(n_genes) < p["condition_responsive_fraction"]
        eff[responsive, c] = 1.5 * rng.standard_normal(int(responsive.sum()))
    return eff


def nb_counts(rng, mu, phi, zi):
    lam = rng.gamma(shape=1.0 / phi, scale=mu * phi)
    counts = rng.poisson(lam)
    zmask = zi & (rng.random(len(mu)) < 0.5)
    counts[zmask] = 0
    return counts


# ---------------------------------------------------------------------------
# Per-size writers
# ---------------------------------------------------------------------------

def write_legacy(path, S, design, legacy, p):
    G = len(legacy)
    n_cond = max(d["cond_idx"] for d in design) + 1
    eff = condition_effects(p, G, n_cond, key=1)
    mu, phi, zi = legacy["_mu"].to_numpy(), legacy["_phi"].to_numpy(), legacy["_zi"].to_numpy()
    cols = {}
    for j, d in enumerate(design):
        rng = np.random.default_rng(np.random.SeedSequence(p["seed"], spawn_key=(1, j)))
        lib = math.exp(p["lib_size_sdlog"] * rng.standard_normal())
        m = mu * lib * np.exp2(eff[:, d["cond_idx"]])
        cols[d["sample_id"]] = nb_counts(rng, m, phi, zi)
    df = pd.DataFrame(cols)
    df.insert(0, "Name", legacy["Name"].to_numpy())
    df.insert(0, "Locus Tag", legacy["Locus Tag"].to_numpy())
    df.to_csv(path, sep="\t", index=False)
    info = {"rows": G, "value_columns": S, "missing_values": 0,
            "zero_fraction": float((df.iloc[:, 2:].to_numpy() == 0).mean())}
    # TPM-like float companion (same counts, length-normalised, 2 decimals):
    # float matrices compress far worse in Parquet than small integers, which
    # matters for the 16 MB session-document question.
    vals = df.iloc[:, 2:].to_numpy(dtype=float)
    length_kb = np.random.default_rng(np.random.SeedSequence(p["seed"], spawn_key=(3,))).uniform(0.2, 4.0, size=G)
    rpk = vals / length_kb[:, None]
    tpm = np.round(rpk / rpk.sum(axis=0, keepdims=True) * 1e6, 2)
    tdf = pd.DataFrame(tpm, columns=df.columns[2:])
    tdf.insert(0, "Name", df["Name"].to_numpy())
    tdf.insert(0, "Locus Tag", df["Locus Tag"].to_numpy())
    tpath = Path(str(path).replace("legacy_wide_", "legacy_wide_tpm_"))
    tdf.to_csv(tpath, sep="\t", index=False)
    info["tpm_companion"] = {"file": tpath.name, "bytes": tpath.stat().st_size, "sha256": sha256(tpath)}
    return info


EXPR_COLUMNS = ["orthogroup_id", "strain", "seed_peg", "sample_id", "condition", "replicate",
                "count", "copy_index", "copies_in_strain", "gene", "product"]


def write_orthology(path, S, design, ref, p):
    n_cond = max(d["cond_idx"] for d in design) + 1
    G = int(ref["_g"].max()) + 1
    eff = condition_effects(p, G, n_cond, key=2)
    by_strain = {k: ref[ref["_k"] == k].reset_index(drop=True) for k in ref["_k"].unique()}
    n_rows = n_zero = n_dropped = 0
    with open(path, "w") as fh:
        fh.write("\t".join(EXPR_COLUMNS) + "\n")
        for j, d in enumerate(design):
            sub = by_strain[d["strain_idx"]]
            rng = np.random.default_rng(np.random.SeedSequence(p["seed"], spawn_key=(2, j)))
            lib = math.exp(p["lib_size_sdlog"] * rng.standard_normal())
            m = sub["_mu"].to_numpy() * lib * np.exp2(eff[sub["_g"].to_numpy(), d["cond_idx"]])
            counts = nb_counts(rng, m, sub["_phi"].to_numpy(), sub["_zi"].to_numpy())
            keep = rng.random(len(sub)) >= p["row_dropout_fraction"]
            n_dropped += int((~keep).sum())
            out = sub.loc[keep, ["orthogroup_id", "strain", "seed_peg", "copy_index",
                                 "copies_in_strain", "gene", "product"]].copy()
            out["sample_id"] = d["sample_id"]
            out["condition"] = d["condition"]
            out["replicate"] = d["replicate"]
            out["count"] = counts[keep]
            n_rows += len(out)
            n_zero += int((out["count"] == 0).sum())
            out[EXPR_COLUMNS].to_csv(fh, sep="\t", index=False, header=False)
    return {"rows": n_rows, "zero_count_rows": n_zero, "dropped_measurements": n_dropped,
            "orthogroups": G, "samples": S, "conditions": n_cond}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sizes", type=int, nargs="+", default=[32, 100, 250, 500, 1000])
    ap.add_argument("--out", type=Path, default=HERE / ".work" / "data")
    ap.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    ap.add_argument("--skip-existing", action="store_true",
                    help="keep files that already exist and match the manifest parameters")
    args = ap.parse_args(argv)

    p = dict(DEFAULTS, seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out / "manifest.json"
    manifest = {"generator_version": GENERATOR_VERSION, "parameters": p, "files": {}}
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text())
        if old.get("parameters") == p and old.get("generator_version") == GENERATOR_VERSION:
            manifest["files"] = old.get("files", {})

    t0 = time.time()
    strains, ref, legacy = build_reference(p)
    ref_path = args.out / "orthology_reference.tsv"
    public_ref = ref.drop(columns=[c for c in ref.columns if c.startswith("_")])
    public_ref.to_csv(ref_path, sep="\t", index=False)
    manifest["files"][ref_path.name] = {
        "kind": "orthology_reference", "bytes": ref_path.stat().st_size, "sha256": sha256(ref_path),
        "rows": len(public_ref), "orthogroups": int(public_ref["orthogroup_id"].nunique()),
        "strains": strains,
        "paralog_orthogroups": int(public_ref.loc[public_ref["copies_in_strain"] > 1, "orthogroup_id"].nunique()),
        "core_orthogroups": int((public_ref.groupby("orthogroup_id")["strain"].nunique() == len(strains)).sum()),
    }
    print(f"[gen] reference: {len(public_ref)} rows", flush=True)

    for S in args.sizes:
        design = sample_design(S, strains, p["n_replicates"])
        for kind, fname, writer, src in (
            ("legacy_wide", f"legacy_wide_S{S}.tsv", write_legacy, legacy),
            ("orthology_expression_long", f"orthology_expression_long_S{S}.tsv", write_orthology, ref),
        ):
            path = args.out / fname
            if args.skip_existing and path.exists() and fname in manifest["files"] \
                    and manifest["files"][fname].get("sha256") == sha256(path):
                print(f"[gen] keep {fname}", flush=True)
                continue
            t = time.time()
            info = writer(path, S, design, src, p)
            info.update(kind=kind, samples=S, bytes=path.stat().st_size, sha256=sha256(path),
                        generate_seconds=round(time.time() - t, 2))
            manifest["files"][fname] = info
            print(f"[gen] {fname}: {info['bytes'] / 1e6:.1f} MB in {info['generate_seconds']} s", flush=True)
        manifest_path.write_text(json.dumps(manifest, indent=2))

    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"[gen] done in {time.time() - t0:.1f} s -> {manifest_path}")


if __name__ == "__main__":
    sys.exit(main())
