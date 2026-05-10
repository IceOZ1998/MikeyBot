import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()
PORT = int(os.getenv("PORT", "8080"))
HTML = (Path(__file__).parent / "index.html").read_text(encoding="utf-8")


@app.get("/")
async def root() -> HTMLResponse:
    return HTMLResponse(HTML)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "מייקיבוט — אימון קוגניטיבי"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
