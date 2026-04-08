from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from ai_routes import router as ai_router

app = FastAPI(title="Daiko AI Engine Private")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ai_router)

@app.get("/")
def health_check():
    return {"status": "online", "engine": "Daiko 2.0", "owner": "Kevin Guevara"}