import io
import urllib.request
import json
from warcio.archiveiterator import ArchiveIterator
from cs336_data.langid import identify_language
from cs336_data.quality import gopher_quality_filter, classify_quality
from cs336_data.toxicity import classify_nsfw, classify_toxic_speech

wet_url = "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-18/segments/1712296815919.75/wet/CC-MAIN-20240412101354-20240412131354-00000.warc.wet.gz"
req = urllib.request.Request(wet_url, headers={"Range": "bytes=0-8000000", "User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as resp:
    data = resp.read()

diverse_discards = []
kept_docs = []

for record in ArchiveIterator(io.BytesIO(data)):
    if record.rec_type != "conversion":
        continue
    text = record.content_stream().read().decode("utf-8", errors="replace")
    uri = record.rec_headers.get_header("WARC-Target-URI") or ""
    if not text.strip():
        continue
    
    # 1. Lang ID
    lang, lprob = identify_language(text)
    if lang != "en" or lprob < 0.70:
        if len(diverse_discards) < 2:
            diverse_discards.append({
                "uri": uri,
                "filter": f"Language ID ({lang}, {lprob:.3f})",
                "text": text[:500]
            })
        continue

    # 2. Gopher
    if not gopher_quality_filter(text):
        diverse_discards.append({
            "uri": uri,
            "filter": "Gopher Quality Filter",
            "text": text[:500]
        })
        continue

    # 3. Harmful
    n_label, n_prob = classify_nsfw(text)
    if n_label == "nsfw" and n_prob >= 0.70:
        diverse_discards.append({
            "uri": uri,
            "filter": f"NSFW Classifier ({n_prob:.3f})",
            "text": text[:500]
        })
        continue

    t_label, t_prob = classify_toxic_speech(text)
    if t_label == "toxic" and t_prob >= 0.80:
        diverse_discards.append({
            "uri": uri,
            "filter": f"Toxicity Classifier ({t_prob:.3f})",
            "text": text[:500]
        })
        continue

    # 4. Quality Classifier
    q_label, q_prob = classify_quality(text)
    if q_label != "wiki":
        diverse_discards.append({
            "uri": uri,
            "filter": f"FastText Quality Classifier (cc, {q_prob:.3f})",
            "text": text[:500]
        })
        continue

    # 5. Kept
    kept_docs.append({
        "uri": uri,
        "q_prob": q_prob,
        "text": text[:500]
    })

print(f"Kept: {len(kept_docs)}, Discards: {len(diverse_discards)}")
with open("scripts/inspection_results.json", "w", encoding="utf-8") as f:
    json.dump({"kept": kept_docs[:10], "discards": diverse_discards[:10]}, f, indent=2)
