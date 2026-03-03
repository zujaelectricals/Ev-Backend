"""
Shared utilities for core apps.
"""


def strip_unicode_4byte(s):
    """
    Remove 4-byte UTF-8 characters (e.g. emojis) from a string.
    MySQL 'utf8' charset only supports BMP (up to 3 bytes); use this to avoid
    OperationalError 1366 when saving to utf8 columns.
    """
    if s is None or not isinstance(s, str):
        return s
    return ''.join(c for c in s if ord(c) <= 0xFFFF)
