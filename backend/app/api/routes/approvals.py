"""Human-approval API routes (human-in-the-loop for HIGH-risk tools)."""
from fastapi import APIRouter, Depends, HTTPException

from app.database.session import get_session
from app.models.approval import Approval
from app.models.user import User
from app.repositories.approval_repository import ApprovalRepository
from app.schemas.approval import ApprovalDecision, ApprovalOut
from app.security.auth import get_current_user

router = APIRouter()


@router.get("/approvals", response_model=list[ApprovalOut])
async def list_approvals(
    session=Depends(get_session),
    pending_only: bool = False,
    current_user: User = Depends(get_current_user),
) -> list[ApprovalOut]:
    """List approval requests (optionally only pending ones) for the user."""
    repo = ApprovalRepository(session)
    approvals = (
        await repo.list_pending(user_id=current_user.id)
        if pending_only
        else await repo.list_all(user_id=current_user.id)
    )
    return [ApprovalOut.model_validate(a) for a in approvals]


@router.get("/approvals/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: str,
    session=Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ApprovalOut:
    repo = ApprovalRepository(session)
    approval = await repo.get(approval_id, user_id=current_user.id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return ApprovalOut.model_validate(approval)


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalOut)
async def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    session=Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> ApprovalOut:
    """Approve or reject a pending approval request.

    Approving sets status to ``approved`` (the agent may then proceed to
    execute the tool). Rejecting sets status to ``rejected`` and the agent
    aborts the paused tool call.
    """
    repo = ApprovalRepository(session)
    approval = await repo.get(approval_id, user_id=current_user.id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"approval already {approval.status}")

    new_status = "approved" if decision.status == "approved" else "rejected"
    approval = await repo.update_status(
        approval, new_status, decision_reason=decision.decision_reason
    )
    return ApprovalOut.model_validate(approval)
