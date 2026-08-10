import os
import traceback
from pathlib import Path
from dotenv import load_dotenv

# 1. Load environment variables BEFORE importing routers/modules
load_dotenv()

from fastapi import FastAPI, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


from app.core.config import settings
from app.api.v1.auth import router as auth_router
from app.api.v1.endpoints.deposit_products import router as deposit_products_router
from app.api.v1.endpoints.banking import router as banking_router
from app.api.v1.endpoints.loan_copilot import router as loan_copilot_router
from app.api.v1.endpoints.policy_explainer import router as policy_explainer_router
from app.api.v1.endpoints.letter_writer import router as letter_writer_router
from app.core.dependencies import require_roles
from app.db.models.models import User

# 2. Instantiate FastAPI Application
app = FastAPI(
    title=getattr(settings, "PROJECT_NAME", "NexusSuit Banking AI Platform"),
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs"
)

# 3. Configure Allowed CORS Origins
cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# Merge with settings.CORS_ORIGINS if defined in app/core/config.py
if hasattr(settings, "CORS_ORIGINS"):
    if isinstance(settings.CORS_ORIGINS, list):
        cors_origins.extend(settings.CORS_ORIGINS)
    elif isinstance(settings.CORS_ORIGINS, str):
        cors_origins.append(settings.CORS_ORIGINS)

# Deduplicate origins list
allowed_origins = list(set(cors_origins))

# Add CORS Middleware with Regex for dynamic local development ports
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:[0-9]+)?",  # Matches any local port
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


# Helper for adding CORS headers to custom exception responses
def get_cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin")
    headers = {}
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    else:
        headers["Access-Control-Allow-Origin"] = "*"
    return headers


# 4. Exception Handlers to Prevent Missing CORS Headers on Errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handles 422 validation errors gracefully with CORS headers."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": exc.body},
        headers=get_cors_headers(request),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handles 404, 401, 403, and 400 HTTP errors with CORS headers."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=get_cors_headers(request),
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Ensures unhandled 500 exceptions print tracebacks and return CORS headers 
    so the frontend receives descriptive errors rather than generic browser CORS blocks.
    """
    print(f"\n[SERVER UNHANDLED EXCEPTION] {str(exc)}")
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Internal Server Error: {str(exc)}"},
        headers=get_cors_headers(request),
    )


# 5. Include API Routers
# Primary Route Prefix (/api/v1)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(loan_copilot_router, prefix="/api/v1", tags=["Module A1: AI Loan Officer"])
app.include_router(deposit_products_router, prefix="/api/v1", tags=["Module A2: Deposit Products"])
app.include_router(banking_router, prefix="/api/v1/banking", tags=["Banking Core"])

# Root Route Aliases (Ensures fallback requests without /api/v1 prefix succeed seamlessly)
app.include_router(loan_copilot_router, prefix="", tags=["Module A1: AI Loan Officer (Fallback)"])
app.include_router(policy_explainer_router, prefix="/api/v1", tags=["Module A3: Bank Policy Explainer"])
app.include_router(letter_writer_router, prefix="/api/v1", tags=["Module A4: Bank Letter Writer"])


# 6. System Health, Diagnostics & Role Endpoints
@app.on_event("startup")
async def startup_event():
    groq_key = os.getenv("GROQ_API_KEY")
    key_status = "✅ CONFIGURED" if groq_key else "⚠️ MISSING (Falling back to Rule Engine)"
    print("\n" + "=" * 60)
    print("🚀 NEXUSSUIT AI BANKING PLATFORM STARTED")
    print(f"🔑 Groq LLM API Key: {key_status}")
    print("📌 Loan Copilot Endpoints Active:")
    print("   - POST /api/v1/loan-copilot/evaluate")
    print("   - POST /api/v1/loan-copilot/evaluate/{app_id}")
    print("   - GET  /api/v1/loan-copilot/applications")
    print("📌 Deposit Advisor Endpoints Active:")
    print("   - GET  /api/v1/deposit-products")
    print("   - POST /api/v1/deposit-products/recommend")
    print("=" * 60 + "\n")


@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "NexusSuit Banking AI Copilot API is running",
        "status": "online",
        "version": "2.4.0",
        "groq_evaluation": "active" if os.getenv("GROQ_API_KEY") else "rule_engine_fallback"
    }


@app.get("/api/v1/test/loan-officer-only", tags=["Testing"])
async def test_loan_officer(current_user: User = Depends(require_roles(["LOAN_OFFICER", "ADMIN"]))):
    return {"message": f"Hello {current_user.username}! Access granted to Loan Officer area."}


@app.get("/api/v1/test/rm-only", tags=["Testing"])
async def test_rm(current_user: User = Depends(require_roles(["RELATIONSHIP_MANAGER", "ADMIN"]))):
    return {"message": f"Hello {current_user.username}! Access granted to Relationship Manager area."}