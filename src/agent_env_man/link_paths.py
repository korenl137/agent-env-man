"""Lexical link identity shared with the standalone update worker."""

import os


def destination_key(value):
    """Ignore only Windows extended prefixes for ordinary absolute paths.

    Do not resolve links or use samefile: a substituted link through an alias
    must not gain ownership merely because it reaches the same current inode.
    Preserve relative paths, case, dot segments, and device namespaces.
    """
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            return "\\\\" + value[8:]
        if (value.startswith("\\\\?\\") and len(value) >= 7
                and value[4].isascii() and value[4].isalpha() and value[5:7] == ":\\"):
            return value[4:]
    return value


def same_destination(actual, expected):
    return (isinstance(actual, str) and isinstance(expected, str)
            and destination_key(actual) == destination_key(expected))
