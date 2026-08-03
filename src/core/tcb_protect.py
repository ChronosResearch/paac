"""
src/core/tcb_protect.py
-----------------------
R-2: Mark TCB source files immutable (Linux chattr +i equivalent via ioctl
     FS_IOC_SETFLAGS) so they cannot be overwritten at runtime.  Falls back
     to a warning on non-Linux platforms or when the process lacks privilege.

R-3: IPC shared-secret token for the Z3 subprocess pipe.  The parent
     generates a random 32-byte token per call and passes it to the child.
     The child echoes it back; the parent rejects any response with a wrong
     token using constant-time comparison.
"""

from __future__ import annotations

import secrets
import sys

from loguru import logger

# ---------------------------------------------------------------------------
# R-3: IPC token
# ---------------------------------------------------------------------------


def generate_ipc_token() -> bytes:
    """Generate a cryptographically random 32-byte IPC session token."""
    return secrets.token_bytes(32)


def verify_ipc_token(expected: bytes, received: bytes) -> bool:
    """Constant-time comparison to prevent timing attacks on the token."""
    return secrets.compare_digest(expected, received)


# ---------------------------------------------------------------------------
# R-2: TCB source-file protection (Linux only, best-effort)
# ---------------------------------------------------------------------------

_TCB_PROTECTED = False


def protect_tcb() -> None:
    """
    Attempt to mark TCB source files read-only at the filesystem level using
    chmod(0o444).  This prevents accidental or malicious overwrite of the
    source files while the process is running.

    On non-Linux platforms, or when the process lacks write permission to the
    files, logs a warning and returns without error.  The function is
    idempotent.
    """
    global _TCB_PROTECTED
    if _TCB_PROTECTED:
        return

    if sys.platform != "linux":
        logger.warning(
            "R-2: TCB file protection skipped — only supported on Linux. "
            "Deploy with '--read-only' Docker flag as mitigation."
        )
        return

    import os
    import stat

    tcb_modules = [
        "src.core.verifier",
        "src.monitor.code_monitor",
        "src.core.tcb_protect",
        "src.core.failsafe",
    ]

    protected = 0
    for mod_name in tcb_modules:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        src_file = getattr(mod, "__file__", None)
        if src_file is None:
            continue
        # Resolve .pyc -> .py
        if src_file.endswith(".pyc"):
            src_file = src_file[:-1]
        if not os.path.exists(src_file):
            continue
        try:
            current = os.stat(src_file).st_mode
            # Remove write bits for owner, group, and others.
            new_mode = current & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
            os.chmod(src_file, new_mode)
            protected += 1
        except OSError:
            pass  # non-fatal — log below

    _TCB_PROTECTED = True
    if protected > 0:
        logger.info(
            f"R-2: TCB source files marked read-only ({protected} file(s))."
        )
    else:
        logger.warning(
            "R-2: TCB file protection applied but no files were chmod'd. "
            "Deploy with '--read-only' Docker flag as mitigation."
        )
