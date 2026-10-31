"""Canonical JSON for hashing: the RFC 8785 (JCS) rules for the value space the prototype allows.

Allowed values are null, booleans, strings, integers within ±(2^53 − 1), lists, and objects with string keys.
Floats are rejected rather than formatted. Python's float repr differs from the ECMAScript formatting
JCS requires, so scores are stored as integer parts per million (JC-35).
"""
import hashlib
import json

MAX_SAFE_INT = 2**53 - 1


class CanonicalError(ValueError):
    pass


def _str(s: str) -> str:
    try:
        s.encode("utf-8")
    except UnicodeEncodeError as e:
        raise CanonicalError("string contains a lone surrogate (not I-JSON)") from e
    # json.dumps with ensure_ascii=False escapes exactly what JCS escapes: " \ and control characters.
    return json.dumps(s, ensure_ascii=False)


def _encode(value, path: str) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INT:
            raise CanonicalError(f"{path}: integer beyond ±2^53")
        return str(value)
    if isinstance(value, float):
        raise CanonicalError(f"{path}: floats are not allowed (store integer ppm)")
    if isinstance(value, str):
        return _str(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode(v, f"{path}[{i}]") for i, v in enumerate(value)) + "]"
    if isinstance(value, dict):
        for k in value:
            if not isinstance(k, str):
                raise CanonicalError(f"{path}: object key {k!r} is not a string")
        keys = sorted(value, key=lambda k: k.encode("utf-16-be"))   # JCS sorts by UTF-16 code units
        return "{" + ",".join(f"{_str(k)}:{_encode(value[k], f'{path}.{k}')}" for k in keys) + "}"
    raise CanonicalError(f"{path}: unsupported type {type(value).__name__}")


def dumps(value) -> bytes:
    return _encode(value, "$").encode("utf-8")


def _no_duplicates(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise CanonicalError(f"duplicate key {k!r}")
        obj[k] = v
    return obj


def _reject_constant(name):
    raise CanonicalError(f"non-finite number {name}")


def _reject_float(text):
    raise CanonicalError(f"float {text} is not allowed")


def loads(data):
    """Parse JSON text or bytes, enforcing the same I-JSON rules as dumps()."""
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        value = json.loads(data, object_pairs_hook=_no_duplicates,
                           parse_constant=_reject_constant, parse_float=_reject_float)
        _encode(value, "$")   # range checks on integers, lone surrogates
    except CanonicalError:
        raise
    except (ValueError, RecursionError) as e:   # JSONDecodeError, UnicodeDecodeError, int digit limit, deep nesting
        raise CanonicalError(f"invalid JSON: {e}") from e
    return value


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_obj(value) -> str:
    return sha256_hex(dumps(value))
