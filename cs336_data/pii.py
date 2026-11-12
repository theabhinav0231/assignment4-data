import re

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(
    r"(?:(?:\+?1\s*(?:[.-]\s*)?)?(?:\(\s*\d{3}\s*\)|\b\d{3})[-. ]?\d{3}[-. ]?\d{4}\b)"
)
IP_REGEX = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\b"
)


def mask_emails(text: str) -> tuple[str, int]:
    """Mask email addresses with |||EMAIL_ADDRESS|||."""
    return EMAIL_REGEX.subn("|||EMAIL_ADDRESS|||", text)


def mask_phone_numbers(text: str) -> tuple[str, int]:
    """Mask common US phone number formats with |||PHONE_NUMBER|||."""
    return PHONE_REGEX.subn("|||PHONE_NUMBER|||", text)


def mask_ips(text: str) -> tuple[str, int]:
    """Mask IPv4 addresses with |||IP_ADDRESS|||."""
    return IP_REGEX.subn("|||IP_ADDRESS|||", text)
