#!/usr/bin/env python3
"""Quality filtering heuristics and classifiers for Common Crawl text.

Implements:
1. Rule-based filtering heuristics from Rae et al. (Gopher, 2021).
2. Supervised FastText quality classifier (Wikipedia vs Common Crawl).
"""

from functools import lru_cache
from pathlib import Path
from typing import Sequence

import fasttext
from cs336_data.common import get_shared_assets_path


@lru_cache(maxsize=1)
def get_quality_model():
    """Load and cache the FastText quality classifier model."""
    model_path = get_shared_assets_path() / "classifiers" / "quality_classifier.bin"
    if not model_path.exists():
        # Fallback to local training if model not pre-generated
        from scripts.train_quality_classifier import train_and_save_classifier

        train_and_save_classifier(model_path)
    return fasttext.load_model(str(model_path))


def classify_quality(text: str) -> tuple[str, float]:
    """Classify input text quality as high-quality reference ('wiki') or low-quality ('cc').

    Args:
        text: Input document string.

    Returns:
        tuple[str, float]: (label, confidence_score) where label in {"wiki", "cc"}.
    """
    cleaned_text = text.replace("\n", " ").strip()
    if not cleaned_text:
        return "cc", 1.0

    model = get_quality_model()
    labels, probs = model.predict(cleaned_text, k=1)
    label = labels[0].replace("__label__", "")
    score = float(probs[0])
    return label, score


def gopher_quality_filter(text: str) -> bool:
    """Evaluate whether input text passes the Gopher quality heuristics.

    Rules applied (Rae et al., 2021 Appendix A):
    1. Word count: Must contain between 50 and 100,000 words (inclusive).
    2. Mean word length: Mean characters per word must be in [3.0, 10.0].
    3. Ellipsis ratio: At most 30% of lines end with an ellipsis ('...' or '…').
    4. Alphabetic ratio: At least 80% of words must contain at least one alphabetic character.

    Args:
        text: Raw document text to filter.

    Returns:
        True if the text passes all quality rules, False otherwise.
    """
    words = text.split()
    num_words = len(words)

    # Rule 1: Document length (50 <= num_words <= 100,000)
    if num_words < 50 or num_words > 100_000:
        return False

    # Rule 2: Mean word length (3.0 <= mean_len <= 10.0)
    total_chars = sum(len(w) for w in words)
    mean_len = total_chars / num_words
    if mean_len < 3.0 or mean_len > 10.0:
        return False

    # Rule 3: Ellipsis lines ratio (<= 30%)
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        lines = text.splitlines()
    if lines:
        ellipsis_lines = sum(
            1 for line in lines if line.rstrip().endswith("...") or line.rstrip().endswith("…")
        )
        if (ellipsis_lines / len(lines)) > 0.3:
            return False

    # Rule 4: Alphabetic words ratio (>= 80%)
    alpha_words = sum(1 for w in words if any(c.isalpha() for c in w))
    if (alpha_words / num_words) < 0.8:
        return False

    return True
