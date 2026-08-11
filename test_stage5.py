"""
test_stage5.py

Verification script for Stage 5 FastAPI REST API Endpoints.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from dotenv import load_dotenv

load_dotenv()

current_file_dir = Path(__file__).resolve().parent
if str(current_file_dir) not in sys.path:
    sys.path.insert(0, str(current_file_dir))

try:
    from app.main import app
    from app.core.dependencies import get_current_user
except ModuleNotFoundError:
    from main import app
    from core.dependencies import get_current_user

# Mock user with role object and role string support
async def mock_get_current_user():
    return SimpleNamespace(
        id="test_admin_id",
        user_id="test_admin_id",
        username="admin_tester",
        email="admin@bank.com",
        role=SimpleNamespace(role_name="ADMIN"),
        is_active=True
    )

app.dependency_overrides[get_current_user] = mock_get_current_user


def run_stage5_test():
    print("==================================================")
    print("      STAGE 5: FASTAPI REST ENDPOINTS VERIFICATION")
    print("==================================================\n")

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        # 1. Health Endpoint
        print("1. Testing Root / Health Endpoint (GET /) ...")
        health_res = client.get("/")
        print(f"   Status Code : {health_res.status_code}")
        print(f"   Response    : {health_res.json()}\n")
        assert health_res.status_code == 200

        # 2. Policy Query Endpoint
        print("2. Testing Policy Query Endpoint (POST /api/v1/policy-explainer/query) ...")
        payload = {
            "query": "When is an asset classified as a Non-Performing Asset (NPA)?",
            "category": "loans",
            "top_k": 2
        }

        headers = {"Authorization": "Bearer mock_test_token_12345"}
        query_res = client.post("/api/v1/policy-explainer/query", json=payload, headers=headers)

        print(f"   Status Code : {query_res.status_code}")

        if query_res.status_code == 200:
            data = query_res.json()
            explanation = data.get("explanation") or data.get("answer") or "No text returned"
            citations = data.get("citations") or []
            evaluator = data.get("evaluator", "Unknown Engine")

            print(f"\n   ⚡ Evaluator Engine : {evaluator}")
            print(f"   💬 Explanation      :\n{explanation}\n")
            print(f"   📖 Citations        : {len(citations)} source(s) attached.")
            for idx, c in enumerate(citations, 1):
                doc = c.get("document", "Unknown")
                page = c.get("page", 0)
                snippet = c.get("quoted_snippet", "")[:80]
                print(f"      {idx}. Doc: {doc} (Page {page}) -> '{snippet}...'")
            print("\nSTATUS: [SUCCESS]\n")
        else:
            print(f"   Response Body: {query_res.json()}")
            print("\nSTATUS: [FAILURE]\n")
            sys.exit(1)

    print("==================================================")
    print("STAGE 5 VERIFICATION VERDICT: FASTAPI SERVER READY")
    print("==================================================")


if __name__ == "__main__":
    run_stage5_test()