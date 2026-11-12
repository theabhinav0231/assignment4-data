#!/usr/bin/env python3
"""Benchmark filtering pipeline on a sample of WET records from Common Crawl."""

import io
import urllib.request
from warcio.archiveiterator import ArchiveIterator
from cs336_data.langid import identify_language
from cs336_data.quality import gopher_quality_filter, classify_quality
from cs336_data.toxicity import classify_nsfw, classify_toxic_speech
from cs336_data.pii import mask_emails, mask_phone_numbers, mask_ips

wet_url = "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-18/segments/1712296815919.75/wet/CC-MAIN-20240412101354-20240412131354-00000.warc.wet.gz"
req = urllib.request.Request(wet_url, headers={"Range": "bytes=0-4000000", "User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as resp:
    data = resp.read()

stats = {
    "total": 0,
    "dropped_non_english": 0,
    "dropped_gopher": 0,
    "dropped_nsfw": 0,
    "dropped_toxicity": 0,
    "dropped_low_quality_cc": 0,
    "kept": 0,
}

count = 0
for record in ArchiveIterator(io.BytesIO(data)):
    if record.rec_type == "conversion":
        text = record.content_stream().read().decode("utf-8", errors="replace")
        if not text.strip():
            continue
        stats["total"] += 1

        # 1. Language ID
        lang, lang_prob = identify_language(text)
        if lang != "en" or lang_prob < 0.70:
            stats["dropped_non_english"] += 1
            continue

        # 2. Gopher quality rules
        if not gopher_quality_filter(text):
            stats["dropped_gopher"] += 1
            continue

        # 3. Harmful content (NSFW & Toxicity)
        nsfw_label, nsfw_score = classify_nsfw(text)
        if nsfw_label == "nsfw" and nsfw_score >= 0.70:
            stats["dropped_nsfw"] += 1
            continue

        toxic_label, toxic_score = classify_toxic_speech(text)
        if toxic_label == "toxic" and toxic_score >= 0.80:
            stats["dropped_toxicity"] += 1
            continue

        # 4. FastText Quality Classifier
        qual_label, qual_score = classify_quality(text)
        if qual_label != "wiki":
            stats["dropped_low_quality_cc"] += 1
            continue

        # 5. Kept
        stats["kept"] += 1
        count += 1
        if stats["total"] >= 100:
            break

print("=== FILTERING BREAKDOWN ON WET SAMPLE ===")
total = stats["total"]
total_dropped = total - stats["kept"]
print(f"Total Documents: {total}")
print(f"Kept Documents: {stats['kept']} ({stats['kept'] / total * 100:.2f}%)")
print(f"Total Discarded: {total_dropped} ({total_dropped / total * 100:.2f}%)")
print("\nBreakdown of Discarded Documents by Filter Step:")
for k in ["dropped_non_english", "dropped_gopher", "dropped_nsfw", "dropped_toxicity", "dropped_low_quality_cc"]:
    cnt = stats[k]
    prop_of_discarded = cnt / total_dropped * 100 if total_dropped else 0
    prop_of_total = cnt / total * 100 if total else 0
    print(f"  {k:24s}: {cnt:3d} ({prop_of_discarded:5.1f}% of discards, {prop_of_total:5.1f}% of total)")
