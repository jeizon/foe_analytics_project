"""Run the mitmproxy console entrypoint through Python.

Some Windows App Control policies block the generated ``mitmproxy.exe`` shim in
virtual environments. This launcher calls the package entrypoint directly while
preserving all CLI arguments.
"""

from __future__ import annotations

from mitmproxy.tools.main import mitmproxy


if __name__ == "__main__":
    mitmproxy()
