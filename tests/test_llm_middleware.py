from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.middleware.llm_middleware import DynamicLLMMiddleware, get_llm_context

test_app = FastAPI()
test_app.add_middleware(DynamicLLMMiddleware)

@test_app.get("/test-context")
async def context_route():
    ctx = get_llm_context()
    if ctx:
        return {
            "model_name": ctx.model_name,
            "base_url": ctx.base_url,
            "api_token": ctx.api_token,
            "temperature": ctx.temperature
        }
    return {"status": "no_context"}

client = TestClient(test_app)

def test_middleware_no_headers():
    response = client.get("/test-context")
    assert response.status_code == 200
    assert response.json() == {"status": "no_context"}

def test_middleware_with_custom_headers():
    headers = {
        "X-LLM-Model": "groq/llama-3.1-8b-instant",
        "X-LLM-Base-Url": "http://localhost:8080/v1",
        "X-LLM-Api-Token": "custom-token-xyz",
        "X-LLM-Temperature": "0.9"
    }
    response = client.get("/test-context", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["model_name"] == "groq/llama-3.1-8b-instant"
    assert data["base_url"] == "http://localhost:8080/v1"
    assert data["api_token"] == "custom-token-xyz"
    assert data["temperature"] == 0.9

def test_middleware_context_cleared_after_request():
    # ContextVar must not leak outside request
    client.get("/test-context", headers={"X-LLM-Model": "test-model"})
    assert get_llm_context() is None
