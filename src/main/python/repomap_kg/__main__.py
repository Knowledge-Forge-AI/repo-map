"""Transitional ``python -m repomap_kg`` launch shim (ADR 0123)."""

import os
import sys

from common_lore_index.entrypoints import legacy_main
from common_lore_index.service_package.environment import (
    apply_service_environment,
    is_service_environment_request,
)


# Keep the canonical module's packaged-service environment boundary.
if is_service_environment_request(tuple(sys.argv[1:])):
    apply_service_environment(os.environ)

raise SystemExit(legacy_main())
