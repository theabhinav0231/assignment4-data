#!/usr/bin/env python3
"""
Production Data Filtering Pipeline for Language Modeling.
CS336 Assignment 4 - Problem (filter_data)

This script processes Common Crawl WET files in parallel using ProcessPoolExecutor,
applying a cascading multi-stage filter pipeline:
  1. Language Identification (fastText lid.176.bin >= 0.70)
  2. Gopher Quality Heuristics (word count, word length, symbol/bullet ratios)
  3. Harmful Content Filtering (Jigsaw NSFW < 0.70 & Toxic < 0.80)
  4. FastText Quality Classifier (wiki vs. cc classifier)
  5. PII Masking (optional downstream / inline)
  6. Exact Line Deduplication / MinHash deduplication
"""

import argparse
import concurrent.futures
import gzip
import io
import json
import logging
import os
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Global worker state for multiprocessing initialization (avoids re-loading models per doc)
_WORKER_MODELS: Dict[str, Any] = {}


def _init_worker(models_dir: str):
    """Initialize FastText models once per worker process."""
    global _WORKER_MODELS
    import fasttext

    # Silence fasttext warnings
    fasttext.FastText.eprint = lambda x: None

    lid_path = os.path.join(models_dir, "lid.176.bin")
    nsfw_path = os.path.join(models_dir, "dolma_fasttext_nsfw_jigsaw_model.bin")
    toxic_path = os.path.join(models_dir, "dolma_fasttext_hatespeech_jigsaw_model.bin")
    qual_path = os.path.join(models_dir, "quality_classifier.bin")

    if os.path.exists(lid_path):
        _WORKER_MODELS["lid"] = fasttext.load_model(lid_path)
    if os.path.exists(nsfw_path):
        _WORKER_MODELS["nsfw"] = fasttext.load_model(nsfw_path)
    if os.path.exists(toxic_path):
        _WORKER_MODELS["toxic"] = fasttext.load_model(toxic_path)
    if os.path.exists(qual_path):
        _WORKER_MODELS["quality"] = fasttext.load_model(qual_path)


def evaluate_document(
    text: str,
    min_lang_prob: float = 0.70,
    max_nsfw_score: float = 0.70,
    max_toxic_score: float = 0.80,
    require_quality_label: str = "wiki",
) -> Tuple[bool, str]:
    """
    Evaluate a single document through the filtering hierarchy.
    Returns (keep: bool, reason: str).
    """
    from cs336_data.quality import gopher_quality_filter

    clean_text = text.replace("\n", " ").strip()
    if not clean_text:
        return False, "empty_document"

    # Stage 1: Language ID
    lid_model = _WORKER_MODELS.get("lid")
    if lid_model is not None:
        labels, probs = lid_model.predict(clean_text, k=1)
        lang = labels[0].replace("__label__", "")
        prob = probs[0]
        if lang != "en" or prob < min_lang_prob:
            return False, "dropped_non_english"

    # Stage 2: Gopher Quality Heuristics
    if not gopher_quality_filter(text):
        return False, "dropped_gopher"

    # Stage 3: Harmful Content (NSFW)
    nsfw_model = _WORKER_MODELS.get("nsfw")
    if nsfw_model is not None:
        labels, probs = nsfw_model.predict(clean_text, k=1)
        label = labels[0].replace("__label__", "")
        if label == "nsfw" and probs[0] >= max_nsfw_score:
            return False, "dropped_nsfw"

    # Stage 4: Harmful Content (Toxicity)
    toxic_model = _WORKER_MODELS.get("toxic")
    if toxic_model is not None:
        labels, probs = toxic_model.predict(clean_text, k=1)
        label = labels[0].replace("__label__", "")
        if label == "toxic" and probs[0] >= max_toxic_score:
            return False, "dropped_toxicity"

    # Stage 5: Domain Quality Classifier
    qual_model = _WORKER_MODELS.get("quality")
    if qual_model is not None:
        labels, probs = qual_model.predict(clean_text, k=1)
        label = labels[0].replace("__label__", "")
        if label != require_quality_label:
            return False, "dropped_low_quality_cc"

    return True, "kept"


def process_single_wet_file(
    input_path: str,
    output_path: str,
    mask_pii_enabled: bool = False,
) -> Dict[str, Any]:
    """
    Process records in a single WET file and stream kept records to output_path.
    Returns summary statistics for attrition breakdown.
    """
    from warcio.archiveiterator import ArchiveIterator
    from cs336_data.pii import mask_emails, mask_phone_numbers, mask_ips

    stats = {
        "file": os.path.basename(input_path),
        "total_documents": 0,
        "kept_documents": 0,
        "dropped_non_english": 0,
        "dropped_gopher": 0,
        "dropped_nsfw": 0,
        "dropped_toxicity": 0,
        "dropped_low_quality_cc": 0,
        "dropped_empty": 0,
        "duration_seconds": 0.0,
    }

    t0 = time.time()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Open input stream (gzipped or plain)
    open_fn = gzip.open if input_path.endswith(".gz") else open
    with open_fn(input_path, "rb") as stream_in, gzip.open(output_path, "wt", encoding="utf-8") as stream_out:
        for record in ArchiveIterator(stream_in):
            if record.rec_type != "conversion":
                continue

            raw_text = record.content_stream().read().decode("utf-8", errors="replace")
            stats["total_documents"] += 1

            keep, reason = evaluate_document(raw_text)
            if not keep:
                if reason == "dropped_non_english":
                    stats["dropped_non_english"] += 1
                elif reason == "dropped_gopher":
                    stats["dropped_gopher"] += 1
                elif reason == "dropped_nsfw":
                    stats["dropped_nsfw"] += 1
                elif reason == "dropped_toxicity":
                    stats["dropped_toxicity"] += 1
                elif reason == "dropped_low_quality_cc":
                    stats["dropped_low_quality_cc"] += 1
                else:
                    stats["dropped_empty"] += 1
                continue

            # Kept document: optionally mask PII
            filtered_text = raw_text
            if mask_pii_enabled:
                filtered_text, _ = mask_emails(filtered_text)
                filtered_text, _ = mask_phone_numbers(filtered_text)
                filtered_text, _ = mask_ips(filtered_text)

            stats["kept_documents"] += 1

            # Write document as JSONL record with URI metadata
            uri = record.rec_headers.get_header("WARC-Target-URI") or ""
            out_obj = {"uri": uri, "text": filtered_text}
            stream_out.write(json.dumps(out_obj, ensure_ascii=False) + "\n")

    stats["duration_seconds"] = round(time.time() - t0, 3)
    return stats


def filter_wet_directory(
    input_dir: str,
    output_dir: str,
    models_dir: str,
    max_workers: Optional[int] = None,
    mask_pii: bool = False,
) -> Dict[str, Any]:
    """
    Filter all WET files in input_dir in parallel.
    """
    input_files = [
        str(p) for p in pathlib.Path(input_dir).rglob("*")
        if p.name.endswith(".warc.wet.gz") or p.name.endswith(".warc.wet")
    ]

    if not input_files:
        logging.warning("No WET files found in %s", input_dir)
        return {"total_files": 0}

    num_workers = max_workers or os.cpu_count() or 4
    logging.info("Found %d WET files. Launching pool with %d workers.", len(input_files), num_workers)

    overall_stats = {
        "total_files": len(input_files),
        "total_documents": 0,
        "kept_documents": 0,
        "dropped_non_english": 0,
        "dropped_gopher": 0,
        "dropped_nsfw": 0,
        "dropped_toxicity": 0,
        "dropped_low_quality_cc": 0,
        "dropped_empty": 0,
        "total_runtime_seconds": 0.0,
    }

    t_start = time.time()
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=num_workers,
        initializer=_init_worker,
        initargs=(models_dir,),
    ) as executor:
        future_to_file = {}
        for in_file in input_files:
            rel_name = os.path.basename(in_file).replace(".warc.wet.gz", ".jsonl.gz")
            out_file = os.path.join(output_dir, rel_name)
            fut = executor.submit(process_single_wet_file, in_file, out_file, mask_pii)
            future_to_file[fut] = in_file

        for fut in concurrent.futures.as_completed(future_to_file):
            f_stats = fut.result()
            logging.info("Processed %s: %d kept / %d total in %.2fs",
                         f_stats["file"], f_stats["kept_documents"], f_stats["total_documents"], f_stats["duration_seconds"])
            for k in ["total_documents", "kept_documents", "dropped_non_english", "dropped_gopher",
                      "dropped_nsfw", "dropped_toxicity", "dropped_low_quality_cc", "dropped_empty"]:
                overall_stats[k] += f_stats[k]

    overall_stats["total_runtime_seconds"] = round(time.time() - t_start, 2)
    return overall_stats


def main():
    parser = argparse.ArgumentParser(description="Filter Common Crawl WET files for language modeling.")
    parser.add_argument("--input-dir", type=str, default="local-shared-data/english-wet-data", help="Directory of WET files")
    parser.add_argument("--output-dir", type=str, default="data/filtered_data", help="Output directory for filtered JSONL files")
    parser.add_argument("--models-dir", type=str, default="local-shared-data/classifiers", help="Path to classifier models")
    parser.add_argument("--max-workers", type=int, default=None, help="Number of parallel processes")
    parser.add_argument("--mask-pii", action="store_true", help="Apply PII regex masking to kept documents")
    args = parser.parse_args()

    stats = filter_wet_directory(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        models_dir=args.models_dir,
        max_workers=args.max_workers,
        mask_pii=args.mask_pii,
    )
    print("\n" + "=" * 50)
    print("OVERALL FILTERING PIPELINE SUMMARY")
    print("=" * 50)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
