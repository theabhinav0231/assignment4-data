#!/usr/bin/env python3
"""Deduplication primitives for language model pre-training corpora.

Includes:
1. Exact line deduplication across multiple corpus files using hash-based counting.
2. MinHash + Locality-Sensitive Hashing (LSH) fuzzy document-level deduplication.
"""

from collections import Counter, defaultdict
import hashlib
import os
from pathlib import Path
import random
import shutil
import string
from typing import Sequence
import unicodedata

import mmh3
from xopen import xopen


def exact_line_deduplication(
    input_files: Sequence[os.PathLike | str],
    output_directory: os.PathLike | str,
) -> None:
    """Perform exact line deduplication across a collection of input files.

    Counts occurrences of each line across all input files using a hash digest
    to conserve memory. In a second pass, rewrites each file to output_directory
    retaining only lines that appear exactly once across the entire corpus.

    Args:
        input_files: List of file paths to process.
        output_directory: Directory where deduplicated files are written.
    """
    out_dir = Path(output_directory)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Pass 1: Count line frequencies using SHA-256 hashes
    line_counts = Counter()
    for file_path in input_files:
        with xopen(file_path, "rt", encoding="utf-8", errors="surrogateescape") as f:
            for line in f:
                line_hash = hashlib.sha256(
                    line.encode("utf-8", errors="surrogateescape")
                ).digest()
                line_counts[line_hash] += 1

    # Pass 2: Rewrite each document keeping only unique lines (count == 1)
    for file_path in input_files:
        out_file_path = out_dir / Path(file_path).name
        with xopen(
            file_path, "rt", encoding="utf-8", errors="surrogateescape"
        ) as f_in, xopen(
            out_file_path, "wt", encoding="utf-8", errors="surrogateescape"
        ) as f_out:
            for line in f_in:
                line_hash = hashlib.sha256(
                    line.encode("utf-8", errors="surrogateescape")
                ).digest()
                if line_counts[line_hash] == 1:
                    f_out.write(line)


def normalize_text_for_minhash(text: str) -> list[str]:
    """Normalize text prior to n-gram extraction following RefinedWeb (Penedo et al., 2023).

    Steps:
    1. Apply NFD Unicode normalization.
    2. Remove accents / combining characters.
    3. Convert to lowercase.
    4. Replace punctuation with whitespace.
    5. Split into normalized whitespace tokens.
    """
    # 1. NFD Unicode normalization
    text = unicodedata.normalize("NFD", text)
    # 2. Strip accents (combining characters in category 'Mn')
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # 3. Lowercase
    text = text.lower()
    # 4. Remove punctuation
    text = text.translate(str.maketrans(string.punctuation, " " * len(string.punctuation)))
    # 5. Normalize whitespace
    return text.split()


def extract_word_ngrams(words: list[str], n: int) -> set[bytes]:
    """Extract word n-grams as UTF-8 encoded byte sequences."""
    if len(words) < n:
        return {" ".join(words).encode("utf-8")} if words else set()
    return {" ".join(words[i : i + n]).encode("utf-8") for i in range(len(words) - n + 1)}


def compute_minhash_signature(ngrams: set[bytes], num_hashes: int) -> list[int]:
    """Compute k-element MinHash signature using MurmurHash3 with seeds 0..k-1."""
    if not ngrams:
        return [0] * num_hashes
    sig = [0xFFFFFFFF] * num_hashes
    for ng in ngrams:
        for i in range(num_hashes):
            h = mmh3.hash(ng, seed=i, signed=False)
            if h < sig[i]:
                sig[i] = h
    return sig


def minhash_deduplication(
    input_files: Sequence[os.PathLike | str],
    num_hashes: int,
    num_bands: int,
    ngrams: int,
    jaccard_threshold: float,
    output_directory: os.PathLike | str,
) -> None:
    """Perform fuzzy document deduplication using MinHash and Locality-Sensitive Hashing (LSH).

    Algorithm:
    1. Preprocess and normalize each input document (NFD, strip accents, lowercase, strip punctuation).
    2. Extract word n-grams and compute k-element MinHash signatures using MurmurHash3.
    3. Partition signatures into b bands of r rows (k = b * r) and bucket documents into hash tables.
    4. Collect candidate duplicate pairs that share at least one band bucket.
    5. Compute the exact n-gram Jaccard similarity for candidate pairs.
    6. Form connected components (clusters) of documents with Jaccard similarity >= jaccard_threshold.
    7. Retain exactly one document from each cluster (and all non-duplicate documents) and write them to output_directory.

    Args:
        input_files: List of file paths to process.
        num_hashes: Total number of hash functions k in signature.
        num_bands: Number of bands b for LSH bucketing.
        ngrams: Word n-gram length n.
        jaccard_threshold: Jaccard similarity threshold theta for marking duplicates.
        output_directory: Directory where deduplicated files are written.
    """
    out_dir = Path(output_directory)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows_per_band = num_hashes // num_bands
    doc_paths = [Path(p) for p in input_files]

    # 1. Read files and extract normalized n-grams
    doc_ngrams: list[set[bytes]] = []
    for p in doc_paths:
        with xopen(p, "rt", encoding="utf-8", errors="surrogateescape") as f:
            raw_text = f.read()
        words = normalize_text_for_minhash(raw_text)
        ng = extract_word_ngrams(words, ngrams)
        doc_ngrams.append(ng)

    # 2. Compute MinHash signatures
    signatures = [compute_minhash_signature(ng, num_hashes) for ng in doc_ngrams]

    # 3. LSH Bucketing across b bands
    buckets: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    for doc_idx, sig in enumerate(signatures):
        for b in range(num_bands):
            band_slice = tuple(sig[b * rows_per_band : (b + 1) * rows_per_band])
            buckets[(b, band_slice)].append(doc_idx)

    # 4. Identify candidate duplicates
    candidate_pairs: set[tuple[int, int]] = set()
    for doc_list in buckets.values():
        if len(doc_list) > 1:
            for i in range(len(doc_list)):
                for j in range(i + 1, len(doc_list)):
                    u, v = doc_list[i], doc_list[j]
                    candidate_pairs.add((min(u, v), max(u, v)))

    # 5. Verify true Jaccard similarity and build duplicate graph
    adj: dict[int, set[int]] = defaultdict(set)
    for u, v in candidate_pairs:
        s_u, s_v = doc_ngrams[u], doc_ngrams[v]
        if s_u or s_v:
            jaccard = len(s_u & s_v) / len(s_u | s_v)
        else:
            jaccard = 1.0
        if jaccard >= jaccard_threshold:
            adj[u].add(v)
            adj[v].add(u)

    # 6. Cluster connected components and select one to keep
    visited: set[int] = set()
    discarded_indices: set[int] = set()
    for doc_idx in range(len(doc_paths)):
        if doc_idx not in visited and doc_idx in adj:
            component: list[int] = []
            queue = [doc_idx]
            visited.add(doc_idx)
            while queue:
                curr = queue.pop(0)
                component.append(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            # Retain exactly one document from the cluster, discard the rest
            chosen = random.choice(component)
            for other in component:
                if other != chosen:
                    discarded_indices.add(other)

    # 7. Write retained files to output directory
    for doc_idx, path in enumerate(doc_paths):
        if doc_idx not in discarded_indices:
            out_path = out_dir / path.name
            shutil.copy2(path, out_path)
