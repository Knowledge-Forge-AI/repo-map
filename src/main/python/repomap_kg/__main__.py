"""Module entry point for ``python -m repomap_kg``."""

import os
import sys

from repomap_kg.service_package.environment import (
    apply_service_environment,
    is_service_environment_request,
)


if is_service_environment_request(tuple(sys.argv[1:])):
    apply_service_environment(os.environ)

from repomap_kg import cli


raise SystemExit(cli.main())
