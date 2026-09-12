"""Run unit tests while rejecting external connections and subprocesses."""

import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch


def reject_external(*args, **kwargs):
    raise RuntimeError("External calls are disabled in the offline test suite")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    with patch.object(socket.socket, "connect", reject_external), \
         patch.object(socket.socket, "connect_ex", reject_external), \
         patch.object(socket, "create_connection", reject_external), \
         patch.object(subprocess, "Popen", reject_external):
        suite = unittest.defaultTestLoader.discover("tests")
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
