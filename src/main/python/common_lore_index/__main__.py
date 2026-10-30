"""Module entry point for ``python -m common_lore_index``."""

import os
import sys

from common_lore_index.service_package.environment import (
    apply_service_environment,
    is_service_environment_request,
)


if is_service_environment_request(tuple(sys.argv[1:])):
    apply_service_environment(os.environ)

from common_lore_index import cli


raise SystemExit(cli.main())
