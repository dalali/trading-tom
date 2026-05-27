from fastapi import FastAPI

app = FastAPI(title="trading-tom")


@app.get("/health")
def health():
    return {"status": "ok"}
