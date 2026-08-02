# Copyright (c) 2026 Shashank Kumar. All rights reserved.
# This file is part of the PAAC (Provably Aligned Core) project.
# See LICENSE for terms.

import os

import click
import yaml

from .monitor.code_monitor import CodeModification, CodeMonitor


@click.group()
def cli():
    """PAAC - Provably Aligned Core"""


@cli.command()
@click.argument("sil_file", type=click.Path(exists=True))
def verify(sil_file):
    """Verify a SIL file for safety violations."""
    with open(os.path.join("config", "default.yaml"), "r") as f:
        config = yaml.safe_load(f)

    with open(sil_file, "r") as f:
        code = f.read()

    monitor = CodeMonitor(config)
    mod = CodeModification(
        func_name="test_func",
        old_code="",
        new_code=code,
        pre_cond="true",
        post_cond="true",
    )

    result = monitor.intercept_modification(mod)
    click.echo(f"Verification Result: {result}")


if __name__ == "__main__":
    cli()
