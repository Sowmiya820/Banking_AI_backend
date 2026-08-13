import os
import logging
from typing import List, Optional, Dict, Union
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_db
from app.db.models.models import User, Role, ModulePermission, PolicyDocument, AuditLog
from app.core.dependencies import require_roles
from app.schemas.user import UserResponse

logger = logging.getLogger(__name__)

# Router definition
router = APIRouter(prefix="/admin", tags=["Admin Management"])

# Storage path for policy uploads
UPLOAD_DIR = Path("data/policies")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ==========================================
# PYDANTIC SCHEMAS
# ==========================================

class RoleUpdateSchema(BaseModel):
    role: str

class UserStatusSchema(BaseModel):
    is_active: bool

class PermissionItem(BaseModel):
    role_name: str
    module_code: str  # e.g., A1, A2, A3, A4
    is_allowed: bool

class PermissionUpdateSchema(BaseModel):
    permissions: List[PermissionItem]

class AuditLogResponse(BaseModel):
    log_id: int
    user_id: Optional[int] = None
    username: Optional[str] = "SYSTEM/ADMIN"
    action: str
    endpoint: str
    details: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True


# ==========================================
# HELPER FUNCTIONS
# ==========================================

async def record_audit_log(
    db: AsyncSession, 
    user_id: Optional[int], 
    action: str, 
    endpoint: str, 
    details: str
):
    """Helper to queue an audit log record into the active database session."""
    try:
        log_entry = AuditLog(
            user_id=user_id,
            action=action,
            endpoint=endpoint,
            details=details,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(log_entry)
        await db.flush()
    except Exception as e:
        logger.error(f"Failed to record audit log: {e}")


# ==========================================
# 1. OVERVIEW & STATS
# ==========================================

@router.get("/stats")
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    total_users = 0
    active_users = 0
    inactive_users = 0
    role_distribution = {}
    active_policies = 0
    archived_policies = 0
    configured_permissions = 0
    total_audit_logs = 0

    # 1. User metrics
    try:
        total_users_res = await db.execute(select(func.count(User.user_id)))
        total_users = total_users_res.scalar() or 0

        active_users_res = await db.execute(
            select(func.count(User.user_id)).where(User.is_active == True)
        )
        active_users = active_users_res.scalar() or 0
        inactive_users = max(0, total_users - active_users)

        role_stmt = (
            select(Role.role_name, func.count(User.user_id))
            .join(User, User.role_id == Role.role_id, isouter=True)
            .group_by(Role.role_name)
        )
        role_res = await db.execute(role_stmt)
        role_distribution = {
            r_name or "UNKNOWN": count for r_name, count in role_res.all()
        }
    except Exception as e:
        logger.error(f"Error querying user stats: {e}")

    # 2. Policy metrics
    try:
        active_pol_res = await db.execute(
            select(func.count(PolicyDocument.document_id)).where(PolicyDocument.status == "ACTIVE")
        )
        active_policies = active_pol_res.scalar() or 0

        archived_pol_res = await db.execute(
            select(func.count(PolicyDocument.document_id)).where(PolicyDocument.status == "ARCHIVED")
        )
        archived_policies = archived_pol_res.scalar() or 0
    except Exception as e:
        logger.error(f"Error querying policy stats: {e}")

    # 3. Permissions metrics
    try:
        perm_res = await db.execute(select(func.count(ModulePermission.id)))
        configured_permissions = perm_res.scalar() or 0
    except Exception as e:
        logger.error(f"Error querying permissions stats: {e}")

    # 4. Audit logs metrics
    try:
        audit_res = await db.execute(select(func.count(AuditLog.log_id)))
        total_audit_logs = audit_res.scalar() or 0
    except Exception as e:
        logger.error(f"Error querying audit log stats: {e}")

    # Return key aliases matching all potential frontend naming expectations
    return {
        "users": total_users,
        "users_count": total_users,
        "total_users": total_users,
        "active_users": active_users,
        "inactive_users": inactive_users,
        "role_distribution": role_distribution,
        "policies": active_policies,
        "policies_count": active_policies,
        "active_policies": active_policies,
        "archived_policies": archived_policies,
        "configured_permissions": configured_permissions,
        "audit_logs": total_audit_logs,
        "audit_logs_count": total_audit_logs,
        "total_audit_logs": total_audit_logs,
    }


# ==========================================
# 2. USER MANAGEMENT
# ==========================================

@router.get("/users", response_model=List[UserResponse])
async def get_all_users(
    q: Optional[str] = Query(None, description="Search by username or email"),
    role: Optional[str] = Query(None, description="Filter by role name"),
    is_active: Optional[bool] = Query(None, description="Filter active status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        stmt = select(User).options(selectinload(User.role)).order_by(User.user_id)
        
        if q:
            search_pattern = f"%{q.strip()}%"
            stmt = stmt.where((User.username.ilike(search_pattern)) | (User.email.ilike(search_pattern)))
        
        if is_active is not None:
            stmt = stmt.where(User.is_active == is_active)

        result = await db.execute(stmt)
        users = result.scalars().all()

        if role:
            norm_role = role.strip().upper()
            users = [u for u in users if u.role and u.role.role_name.upper() == norm_role]

        return [
            UserResponse(
                user_id=u.user_id,
                username=u.username,
                email=u.email,
                role_name=u.role.role_name if u.role else "USER",
                is_active=u.is_active,
            )
            for u in users
        ]
    except Exception as e:
        logger.error(f"Error listing users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users list."
        )


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    role_in: RoleUpdateSchema,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        stmt = select(User).options(selectinload(User.role)).where(User.user_id == user_id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )

        old_role = user.role.role_name if user.role else "NONE"
        normalized_role_name = role_in.role.strip().upper().replace(" ", "_")

        role_stmt = select(Role).where(Role.role_name == normalized_role_name)
        role_result = await db.execute(role_stmt)
        role = role_result.scalars().first()

        if not role:
            role = Role(role_name=normalized_role_name, description=f"System Role for {normalized_role_name}")
            db.add(role)
            await db.flush()

        user.role_id = role.role_id
        
        await record_audit_log(
            db=db,
            user_id=current_user.user_id if current_user else None,
            action="UPDATE_USER_ROLE",
            endpoint=f"/admin/users/{user_id}/role",
            details=f"Updated User #{user_id} ({user.username}) role from '{old_role}' to '{normalized_role_name}'"
        )
        
        await db.commit()

        return {
            "message": f"User {user.username} role updated to {normalized_role_name}",
            "user_id": user.user_id,
            "role_name": normalized_role_name,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating role for user {user_id}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user role")


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: int,
    status_in: UserStatusSchema,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        stmt = select(User).where(User.user_id == user_id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found",
            )

        if user.user_id == current_user.user_id and not status_in.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admins cannot deactivate their own account.",
            )

        user.is_active = status_in.is_active
        status_str = "ACTIVATED" if status_in.is_active else "DEACTIVATED"

        await record_audit_log(
            db=db,
            user_id=current_user.user_id if current_user else None,
            action=f"USER_{status_str}",
            endpoint=f"/admin/users/{user_id}/status",
            details=f"{status_str} User #{user_id} ({user.username})"
        )

        await db.commit()

        return {
            "message": f"User {user.username} status set to {status_str.lower()}",
            "user_id": user.user_id,
            "is_active": user.is_active,
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating status for user {user_id}: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update user status")


# ==========================================
# 3. ROLES & APPLICATION ACCESS (A1-A4)
# ==========================================

DEFAULT_MODULES = ["A1", "A2", "A3", "A4"]
DEFAULT_ROLES = ["ADMIN", "LOAN_OFFICER", "RELATIONSHIP_MANAGER"]

@router.get("/permissions")
async def get_application_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        roles_result = await db.execute(select(Role))
        db_roles = [r.role_name for r in roles_result.scalars().all()]
        all_roles = list(set(DEFAULT_ROLES + db_roles))

        perms_result = await db.execute(select(ModulePermission))
        existing_perms = perms_result.scalars().all()
        
        perm_map = {(p.role_name, p.module_code): p.is_allowed for p in existing_perms}

        response = []
        for r in sorted(all_roles):
            for m in DEFAULT_MODULES:
                is_allowed = perm_map.get((r, m), True)
                response.append({
                    "role_name": r,
                    "module_code": m,
                    "is_allowed": is_allowed
                })

        return response
    except Exception as e:
        logger.error(f"Error fetching permissions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve permissions matrix"
        )


@router.put("/permissions")
async def update_application_permissions(
    payload: Union[PermissionUpdateSchema, PermissionItem, List[PermissionItem]],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        if isinstance(payload, PermissionUpdateSchema):
            items = payload.permissions
        elif isinstance(payload, PermissionItem):
            items = [payload]
        elif isinstance(payload, list):
            items = payload
        else:
            items = []

        updated_count = 0
        for item in items:
            stmt = select(ModulePermission).where(
                ModulePermission.role_name == item.role_name,
                ModulePermission.module_code == item.module_code
            )
            res = await db.execute(stmt)
            perm = res.scalars().first()

            if perm:
                perm.is_allowed = item.is_allowed
            else:
                perm = ModulePermission(
                    role_name=item.role_name,
                    module_code=item.module_code,
                    is_allowed=item.is_allowed
                )
                db.add(perm)
            updated_count += 1

        await record_audit_log(
            db=db,
            user_id=current_user.user_id if current_user else None,
            action="UPDATE_PERMISSIONS",
            endpoint="/admin/permissions",
            details=f"Updated access matrix for {updated_count} module-role mappings."
        )

        await db.commit()
        return {"message": "Application permissions updated successfully", "count": updated_count}
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating permissions: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save application permissions: {str(e)}"
        )
# ==========================================
# 4. POLICY DOCUMENT MANAGEMENT
# ==========================================

@router.get("/policies")
async def list_policy_documents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        # Fetch all policies so React can filter Active vs Deleted
        stmt = select(PolicyDocument).order_by(PolicyDocument.uploaded_at.desc())
        result = await db.execute(stmt)
        policies = result.scalars().all()

        return [
            {
                "document_id": p.document_id,
                "title": getattr(p, 'title', None) or getattr(p, 'filename', 'Document'),
                "filename": getattr(p, 'filename', ''),
                "category": getattr(p, 'category', 'General Policy'),
                "file_path": getattr(p, 'file_path', ''),
                "version": getattr(p, 'version', '1.0'),
                "status": getattr(p, 'status', 'ACTIVE'),
                "uploaded_by": getattr(p, 'uploaded_by', 'ADMIN'),
                "uploaded_at": p.uploaded_at.isoformat() if getattr(p, 'uploaded_at', None) else None,
            }
            for p in policies
        ]
    except Exception as e:
        logger.error(f"Error retrieving policy documents: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch policy documents: {str(e)}"
        )

@router.post("/policies")
@router.post("/policies/upload")
async def upload_policy_document(
    title: str = Form(""),
    category: Optional[str] = Form("General Policy"),
    version: Optional[str] = Form("1.0"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    if not file.filename.lower().endswith((".pdf", ".txt", ".docx")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only PDF, TXT, and DOCX files are allowed.",
        )

    display_title = title.strip() if title and title.strip() else file.filename

    try:
        saved_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        file_path = UPLOAD_DIR / saved_filename

        contents = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(contents)

        policy = PolicyDocument(
            title=display_title,
            filename=file.filename,
            category=category,
            file_path=str(file_path),
            version=version,
            status="ACTIVE",
            uploaded_by=current_user.username if current_user else "ADMIN",
            uploaded_at=datetime.now(timezone.utc)
        )
        db.add(policy)
        await db.flush()

        await record_audit_log(
            db=db,
            user_id=current_user.user_id if current_user else None,
            action="UPLOAD_POLICY",
            endpoint="/admin/policies",
            details=f"Uploaded policy '{display_title}' v{version} ({file.filename})"
        )

        await db.commit()

        return {
            "message": "Policy document uploaded successfully",
            "document_id": policy.document_id,
            "title": policy.title,
            "version": policy.version,
            "status": policy.status
        }
    except Exception as e:
        await db.rollback()
        logger.error(f"Error uploading policy document: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save policy document: {str(e)}"
        )


@router.patch("/policies/{policy_id}/archive")
async def archive_policy_document(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    """Toggles policy status between ACTIVE and ARCHIVED."""
    try:
        stmt = select(PolicyDocument).where(
            PolicyDocument.document_id == policy_id,
            PolicyDocument.status != "DELETED"
        )
        res = await db.execute(stmt)
        policy = res.scalars().first()

        if not policy:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy document not found")

        new_status = "ARCHIVED" if policy.status == "ACTIVE" else "ACTIVE"
        policy.status = new_status

        await record_audit_log(
            db=db,
            user_id=current_user.user_id if current_user else None,
            action="ARCHIVE_POLICY",
            endpoint=f"/admin/policies/{policy_id}/archive",
            details=f"Changed policy #{policy_id} ('{policy.title}') status to {new_status}"
        )

        await db.commit()
        return {"message": f"Policy status changed to {new_status}", "policy_id": policy_id, "status": new_status}
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error archiving policy {policy_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update policy status"
        )


@router.delete("/policies/{policy_id}")
async def delete_policy_document(
    policy_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    """Soft deletes policy: hides it permanently from UI and vector search without breaking DB foreign keys."""
    try:
        stmt = select(PolicyDocument).where(
            PolicyDocument.document_id == policy_id,
            PolicyDocument.status != "DELETED"
        )
        res = await db.execute(stmt)
        policy = res.scalars().first()

        if not policy:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy document not found or already deleted")

        policy_title = getattr(policy, 'title', None) or getattr(policy, 'filename', f'Policy #{policy_id}')

        # 🔑 Set status to DELETED (hides it everywhere permanently)
        policy.status = "DELETED"

        await record_audit_log(
            db=db,
            user_id=current_user.user_id if current_user else None,
            action="DELETE_POLICY",
            endpoint=f"/admin/policies/{policy_id}",
            details=f"Marked policy #{policy_id} ('{policy_title}') as DELETED"
        )

        await db.commit()
        return {"message": f"Policy '{policy_title}' deleted successfully", "policy_id": policy_id}

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting policy {policy_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete policy document: {str(e)}"
        )
        
# ==========================================
# 5. AUDIT LOGS
# ==========================================

@router.get("/audit-logs", response_model=List[AuditLogResponse])
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        stmt = (
            select(AuditLog)
            .options(selectinload(AuditLog.user))
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        res = await db.execute(stmt)
        logs = res.scalars().all()

        return [
            AuditLogResponse(
                log_id=log.log_id,
                user_id=log.user_id,
                username=log.user.username if log.user else "SYSTEM/ADMIN",
                action=log.action,
                endpoint=log.endpoint,
                details=log.details,
                timestamp=log.timestamp,
            )
            for log in logs
        ]
    except Exception as e:
        logger.error(f"Error fetching audit logs: {str(e)}")
        return []
    
    # ==========================================
# DELETE USER ENDPOINT
# ==========================================

@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN"])),
):
    try:
        stmt = select(User).where(User.user_id == user_id)
        result = await db.execute(stmt)
        user = result.scalars().first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found"
            )

        # Prevent admin from deleting their own account
        if user.user_id == current_user.user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admins cannot delete their own account."
            )

        deleted_username = user.username
        await db.delete(user)

        await record_audit_log(
            db=db,
            user_id=current_user.user_id,
            action="DELETE_USER",
            endpoint=f"/admin/users/{user_id}",
            details=f"Deleted User #{user_id} ({deleted_username})"
        )

        await db.commit()

        return {
            "message": f"User '{deleted_username}' deleted successfully",
            "user_id": user_id
        }
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Error deleting user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user."
        )