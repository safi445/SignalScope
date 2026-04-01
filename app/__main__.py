from __future__ import annotations

import os

import uvicorn

from app.server import create_app


def main() -> None:
    host = os.environ.get("RECON_HOST", "127.0.0.1")
    port = int(os.environ.get("RECON_PORT", "5000"))
    db_path = os.environ.get("RECON_DB", os.path.join(os.getcwd(), "recon.db"))
    app = create_app(db_path=db_path)

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

