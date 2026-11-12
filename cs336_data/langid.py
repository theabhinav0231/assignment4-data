from functools import lru_cache
from pathlib import Path
import fasttext
from cs336_data.common import get_shared_assets_path


@lru_cache(maxsize=1)
def get_language_model():
    """Load and cache the FastText language identification model."""
    model_path = get_shared_assets_path() / "classifiers" / "lid.176.bin"
    return fasttext.load_model(str(model_path))


def identify_language(text: str) -> tuple[str, float]:
    """
    Identify the primary language of the text.
    
    Returns:
        (language_code, confidence_score): e.g. ("en", 0.98)
    """
    cleaned_text = text.replace("\n", " ").strip()
    if not cleaned_text:
        return "unknown", 0.0

    model = get_language_model()
    labels, probs = model.predict(cleaned_text, k=1)
    
    lang_code = labels[0].replace("__label__", "")
    score = float(probs[0])
    
    return lang_code, score
