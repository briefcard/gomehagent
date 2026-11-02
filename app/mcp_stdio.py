"""The data layer over stdio — for a Claude Code session on the owner's machine.

The HTTP door (`/mcp` on the web service) needs two things a session may not
have: a network path to the deploy, and `MCP_KEY`. This entry point needs
neither. It runs the SAME server object — the same five tools, the same gates,
the same trust boundary — in-process, against whatever `DATABASE_URL` names
(the Render Postgres external URL, for the live data).

    claude mcp add gomehagent-local --env DATABASE_URL=<render external url> \\
      -- python3 -m app.mcp_stdio          # run from the repo root

WHY NO BEARER HERE. Whoever can start this process already holds
DATABASE_URL, which is every row; a key in front of it would guard nothing.

WHY IT REFUSES WITHOUT DATABASE_URL. `config.DATABASE_URL` falls back to
`sqlite:///local.db`, and a planning session pointed at an empty local file
would answer "nothing is planned" — a wrong answer that looks like a right
one. `GOMEH_MCP_ALLOW_LOCAL=1` is the explicit opt-in for a test database.

STDOUT IS THE PROTOCOL. Anything the app prints at import would corrupt the
JSON-RPC stream, so imports run with stdout pointed at stderr, and the schema
is never migrated from here — the web service owns migrations.
"""
from __future__ import annotations

import contextlib
import os
import sys


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url and os.environ.get("GOMEH_MCP_ALLOW_LOCAL") != "1":
        print("gomehagent-local: DATABASE_URL is not set, so this would read an "
              "empty local database and report nothing as if it were the truth. "
              "Set DATABASE_URL to the Render Postgres external URL "
              "(or GOMEH_MCP_ALLOW_LOCAL=1 for a test database).", file=sys.stderr)
        return 2
    with contextlib.redirect_stdout(sys.stderr):
        from . import mcp_server
    mcp_server.server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
