from fastapi import FastAPI

app = FastAPI(
    title="ASI Meal Management API",
    description="Internal API for ASI Meal Management.",
    version="0.1.0",
)


@app.get("/health", tags=["Health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}
