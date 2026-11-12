#!/usr/bin/env python3
"""Evaluate Gopher quality filters on 20 WARC records from Common Crawl."""

import io
import urllib.request
from warcio.archiveiterator import ArchiveIterator
from cs336_data.extract import extract_text_from_html_bytes
from cs336_data.quality import gopher_quality_filter

warc_url = "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-18/segments/1712296815919.75/warc/CC-MAIN-20240412101354-20240412131354-00000.warc.gz"
req = urllib.request.Request(warc_url, headers={"Range": "bytes=0-10000000", "User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as resp:
    content = resp.read()

count = 0
results = []
for record in ArchiveIterator(io.BytesIO(content)):
    if record.rec_type == "response":
        http_headers = record.http_headers
        if http_headers and "html" in http_headers.get_header("Content-Type", "").lower():
            target_uri = record.rec_headers.get_header("WARC-Target-URI")
            html_bytes = record.raw_stream.read()
            text = extract_text_from_html_bytes(html_bytes)
            words = text.split()
            lines = [l for l in text.splitlines() if l.strip()]
            passed = gopher_quality_filter(text)

            reasons = []
            if len(words) < 50:
                reasons.append(f"Too short ({len(words)} < 50)")
            elif len(words) > 100000:
                reasons.append(f"Too long ({len(words)} > 100k)")

            if words:
                mean_l = sum(len(w) for w in words) / len(words)
                if mean_l < 3.0 or mean_l > 10.0:
                    reasons.append(f"Mean len {mean_l:.1f} not in [3,10]")
                alpha_ratio = sum(1 for w in words if any(c.isalpha() for c in w)) / len(words)
                if alpha_ratio < 0.8:
                    reasons.append(f"Alpha {alpha_ratio:.1%} < 80%")
            else:
                reasons.append("No words")

            if lines:
                ell_ratio = sum(1 for l in lines if l.rstrip().endswith(("...", "…"))) / len(lines)
                if ell_ratio > 0.3:
                    reasons.append(f"Ellipsis {ell_ratio:.1%} > 30%")

            count += 1
            verdict = "PASS" if passed else "FAIL"
            print(f"#{count:02d} | Words: {len(words):4d} | Gopher: {verdict:4s} | URI: {target_uri[:55]}")
            if not passed:
                print(f"     Failed: {', '.join(reasons)}")
            snippet = " ".join(text[:120].split())
            print(f"     Snippet: {snippet}")
            if count >= 20:
                break
