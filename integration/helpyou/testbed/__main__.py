from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "testbed.app:app",
        host=os.environ.get("HELPYOU_TESTBED_HOST", "127.0.0.1"),
        port=int(os.environ.get("HELPYOU_TESTBED_PORT", "8010")),
        reload=False,
    )
