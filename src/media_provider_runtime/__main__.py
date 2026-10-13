# Copyright 2026 Yilei Bi
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse

from media_provider_runtime.describe import (
    print_distribution_description,
)
from media_provider_runtime.worker import (
    main as worker_main,
)


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--describe-distribution",
        type=str,
        default=None,
    )

    args = parser.parse_args()

    if args.describe_distribution:
        print_distribution_description(
            args.describe_distribution
        )
        return

    worker_main()


if __name__ == "__main__":
    main()