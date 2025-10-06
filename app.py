import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from playwright.async_api import async_playwright
from pydantic import AnyHttpUrl, BaseModel


class ShotRequest(BaseModel):
    url: AnyHttpUrl
    device: str = "desktop"  # "desktop" | "mobile"
    mode: str = "full"  # "full" | "viewport"
    delay: int | int = 0  # ms


app = FastAPI(title="Web Screenshot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    app.state.playwright = await async_playwright().start()
    app.state.browser = await app.state.playwright.chromium.launch(
        headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
    )


@app.on_event("shutdown")
async def shutdown():
    await app.state.browser.close()
    await app.state.playwright.stop()


@app.post("/api/screenshot", response_class=Response)
async def screenshot(req: ShotRequest):
    if req.device not in {"desktop", "mobile"} or req.mode not in {"full", "viewport"}:
        raise HTTPException(status_code=400, detail="Paramètres invalides.")

    p = app.state.playwright
    browser = app.state.browser
    full_page = req.mode == "full"

    # Contexte selon device
    if req.device == "mobile":
        ctx = await browser.new_context(**p.devices["iPhone 13"])
    else:
        ctx = await browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            ),
        )

    try:
        page = await ctx.new_page()
        # Optionnel: bloquer un peu de bruit (polices, tracking)
        await page.route(
            "**/*",
            lambda route: asyncio.create_task(
                route.abort()
                if route.request.resource_type in {"font", "media"}
                else route.continue_()
            ),
        )
        await page.goto(str(req.url), wait_until="networkidle", timeout=30000)

        # ⬇️ Attente facultative avant capture
        if (req.delay or 0) > 0:
            await page.wait_for_timeout(int(req.delay))
        img = await page.screenshot(full_page=full_page, type="png")
        return Response(content=img, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Capture échouée: {e}")
    finally:
        await ctx.close()


# monter les fichiers statiques APRÈS les routes API
# `html=True` sert index.html sur "/"
app.mount("/", StaticFiles(directory="static", html=True), name="static")
