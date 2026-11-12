from functools import lru_cache
from pathlib import Path
import fasttext
from cs336_data.common import get_shared_assets_path


@lru_cache(maxsize=1)
def get_nsfw_model():
    """Load and cache the Dolma Jigsaw FastText NSFW classifier model."""
    model_path = get_shared_assets_path() / "classifiers" / "dolma_fasttext_nsfw_jigsaw_model.bin"
    return fasttext.load_model(str(model_path))


@lru_cache(maxsize=1)
def get_toxic_speech_model():
    """Load and cache the Dolma Jigsaw FastText toxic speech classifier model."""
    model_path = get_shared_assets_path() / "classifiers" / "dolma_fasttext_hatespeech_jigsaw_model.bin"
    return fasttext.load_model(str(model_path))


def classify_nsfw(text: str) -> tuple[str, float]:
    """
    Classify whether the text is NSFW or not.

    Returns:
        (label, score): ("nsfw" | "non-nsfw", confidence_float)
    """
    cleaned_text = text.replace("\n", " ").strip()
    if not cleaned_text:
        return "non-nsfw", 0.0

    model = get_nsfw_model()
    labels, probs = model.predict(cleaned_text, k=1)
    label = labels[0].replace("__label__", "")
    score = float(probs[0])
    return label, score


def classify_toxic_speech(text: str) -> tuple[str, float]:
    """
    Classify whether the text is toxic speech or not.

    Returns:
        (label, score): ("toxic" | "non-toxic", confidence_float)
    """
    cleaned_text = text.replace("\n", " ").strip()
    if not cleaned_text:
        return "non-toxic", 0.0

    model = get_toxic_speech_model()
    labels, probs = model.predict(cleaned_text, k=1)
    label = labels[0].replace("__label__", "")
    score = float(probs[0])
    return label, score
