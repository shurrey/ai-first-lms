from __future__ import annotations

import uvicorn

from engine.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("engine.__main__:app", host="0.0.0.0", port=8000, reload=True)
