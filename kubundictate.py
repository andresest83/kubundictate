"""Entrypoint: dispatches to server.py or client.py based on KUBUNDICTATE_MODE.

See README.md for configuration and setup on each mode.
"""

import os
import sys

MODE = os.environ.get("KUBUNDICTATE_MODE", "").lower()

if MODE == "server":
    from server import main
elif MODE == "client":
    from client import main
else:
    sys.exit(
        "KUBUNDICTATE_MODE is not set (or invalid). Set it to 'server' "
        "(on the GPU box) or 'client' (on a dictation machine) -- see "
        "README.md."
    )

if __name__ == "__main__":
    main()
