"""Stable retained selection identity shared by direct and projection audits."""

import hashlib
import json

from ci.retained_python_records import BaselineDocument


def selection_digest(document: BaselineDocument) -> str:
    encoded = json.dumps(document["selection"]["modules"], ensure_ascii=False,
                         separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()
