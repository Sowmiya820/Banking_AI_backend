from fastapi import APIRouter
from app.api.v1.endpoints import banking, deposit_products  # import new endpoint

api_router = APIRouter()

api_router.include_router(banking.router, prefix="/banking", tags=["Banking"])
api_router.include_router(deposit_products.router, prefix="/banking", tags=["Deposit Products"])