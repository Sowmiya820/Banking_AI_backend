import os
import traceback
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# 1. Load environment variables BEFORE importing routers/modules
load_dotenv()

from fastapi import FastAPI, APIRouter, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.db.session import engine
from app.db.models.models import Base
from app.api.v1.auth import router as auth_router
from app.api.v1.endpoints.deposit_products import router as deposit_products_router
from app.api.v1.endpoints.banking import router as banking_router
from app.api.v1.endpoints.loan_copilot import router as loan_copilot_router
from app.api.v1.endpoints.policy_explainer import router as policy_explainer_router
from app.api.v1.endpoints.letter_writer import router as letter_writer_router
from app.api.v1.endpoints.admin import router as admin_router
from app.core.dependencies import require_roles
from app.db.models.models import User

# Import Vector Store Service for Stage 5 RAG Integration
from app.services.vector_store import initialize_vector_db


def resolve_chroma_path() -> Path:
    """Helper to locate chroma_db directory relative to project root."""
    current_dir = Path(__file__).resolve().parent
    opt1 = current_dir / "data" / "chroma_db"
    opt2 = current_dir / "backend" / "data" / "chroma_db"
    return opt1 if opt1.exists() else opt2


# 2. Modern Lifespan Event Handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Automatic Database Table Creation
    db_status = "⚠️ NOT CONNECTED"
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        db_status = "✅ READY (Tables verified)"
    except Exception as e:
        db_status = f"❌ FAILED ({str(e)})"

    # Check Groq LLM API Key Status
    groq_key = os.getenv("GROQ_API_KEY")
    key_status = "✅ CONFIGURED" if groq_key else "⚠️ MISSING (Falling back to Rule Engine)"

    # Initialize Persistent ChromaDB Vector Store
    chroma_status = "⚠️ NOT INITIALIZED"
    try:
        chroma_dir = resolve_chroma_path()
        collection = initialize_vector_db(chroma_dir)
        app.state.chroma_collection = collection
        chroma_status = f"✅ READY ({collection.count()} chunks indexed)"
    except Exception as e:
        chroma_status = f"❌ FAILED ({str(e)})"
        app.state.chroma_collection = None

    print("\n" + "=" * 65)
    print("🚀 BANKING AI COPILOT PLATFORM STARTED")
    print(f"🗄️ Database Status     : {db_status}")
    print(f"🔑 Groq LLM API Key   : {key_status}")
    print(f"📦 ChromaDB Vector Store: {chroma_status}")
    print("📌 Active Modules:")
    print("   • Module A1: AI Loan Officer        (/api/v1/loan-copilot)")
    print("   • Module A2: AI Deposit Advisor    (/api/v1/deposit-products)")
    print("   • Module A3: Bank Policy Explainer (/api/v1/policy-explainer)")
    print("   • Module A4: Bank Letter Writer    (/api/v1/letter-writer)")
    print("   • Banking Core Engine              (/api/v1/banking)")
    print("   • Admin Console Engine             (/api/v1/admin)")
    print("=" * 65 + "\n")
    
    yield


# 3. Instantiate FastAPI Application
app = FastAPI(
    title=getattr(settings, "PROJECT_NAME", "Banking AI Copilot"),
    version="2.4.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# 4. Configure Allowed CORS Origins
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
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:[0-9]+)?",
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


# 5. Global Exception Handlers
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
    """Ensures unhandled 500 exceptions print tracebacks and return CORS headers."""
    print(f"\n[SERVER UNHANDLED EXCEPTION] {str(exc)}")
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": f"Internal Server Error: {str(exc)}"},
        headers=get_cors_headers(request),
    )


# 6. Include Primary API Routers (/api/v1)
app.include_router(auth_router, prefix="/api/v1")
app.include_router(loan_copilot_router, prefix="/api/v1", tags=["Module A1: AI Loan Officer"])
app.include_router(deposit_products_router, prefix="/api/v1", tags=["Module A2: Deposit Products"])
app.include_router(policy_explainer_router, prefix="/api/v1", tags=["Module A3: Bank Policy Explainer"])
app.include_router(letter_writer_router, prefix="/api/v1", tags=["Module A4: Bank Letter Writer"])
app.include_router(banking_router, prefix="/api/v1/banking", tags=["Banking Core"])

# Admin router defines prefix="/admin" internally in app/api/v1/endpoints/admin.py
app.include_router(admin_router, prefix="/api/v1", tags=["Admin Management Console"])


# 7. System Health & Diagnostic Endpoints
@app.get("/", tags=["Health"])
async def root():
    chroma_count = app.state.chroma_collection.count() if getattr(app.state, "chroma_collection", None) else 0
    return {
        "message": "Banking AI Copilot API is online",
        "status": "healthy",
        "version": "2.4.0",
        "groq_evaluation": "active" if os.getenv("GROQ_API_KEY") else "rule_engine_fallback",
        "vector_store_chunks": chroma_count
    }


@app.get("/api/v1/test/loan-officer-only", tags=["Testing"])
async def test_loan_officer(
    current_user: User = Depends(require_roles(["LOAN OFFICER", "LOAN_OFFICER", "ADMIN"]))
):
    return {"message": f"Hello {current_user.username}! Access granted to Loan Officer area."}


@app.get("/api/v1/test/rm-only", tags=["Testing"])
async def test_rm(
    current_user: User = Depends(require_roles(["RELATIONSHIP MANAGER", "RELATIONSHIP_MANAGER", "ADMIN"]))
):
    return {"message": f"Hello {current_user.username}! Access granted to Relationship Manager area."}