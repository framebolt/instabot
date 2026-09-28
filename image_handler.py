"""Pollinations image generation. No API key needed."""
import os
import tempfile
import urllib.parse
import uuid

import httpx

WIDTH = 1024
HEIGHT = 1024


async def generate_image(prompt: str) -> str:
    """Download Pollinations image to temp dir, return local path."""
    clean = (prompt or "").strip()
    if not clean:
        raise ValueError("empty image prompt")
    if len(clean) > 500:
        clean = clean[:500]
    encoded = urllib.parse.quote(clean)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={WIDTH}&height={HEIGHT}&nologo=true&model=flux"
    )
    out_path = os.path.join(tempfile.gettempdir(), f"ig_img_{uuid.uuid4().hex}.jpg")
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, timeout=60.0)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "image" not in ctype and len(resp.content) < 5000:
            raise RuntimeError(f"pollinations returned non-image: {ctype}")
        with open(out_path, "wb") as f:
            f.write(resp.content)
    return out_path
