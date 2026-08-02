# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

import sys

from loguru import logger


def setup_logging():
    logger.remove()
    logger.add(sys.stdout, level="INFO")
    logger.add("paac_core.log", rotation="10 MB", level="DEBUG")


setup_logging()
