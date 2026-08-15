"""Repository for human-approval requests."""
from typing import Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval


class ApprovalRepository:
    """Data access for :class:`Approval` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: str,
        tool_name: str,
        arguments: str,
        conversation_id: Optional[str] = None,
    ) -> Approval:
        approval = Approval(
            id=str(uuid4()),
            user_id=user_id,
            tool_name=tool_name,
            arguments=arguments,
            status="pending",
            conversation_id=conversation_id,
        )
        self.session.add(approval)
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(approval)
        return approval

    async def get(
        self, approval_id: str, user_id: Optional[str] = None
    ) -> Optional[Approval]:
        """Fetch an approval by id.

        When ``user_id`` is provided, the result is additionally scoped to that
        user (owner check). A mismatch returns ``None`` so callers can surface a
        404 without disclosing whether the resource exists. When ``user_id`` is
        omitted the original behaviour is preserved (used internally by the
        agent tool gateway where the caller is already trusted).
        """
        stmt = select(Approval).where(Approval.id == approval_id)
        if user_id is not None:
            stmt = stmt.where(Approval.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pending(self, user_id: Optional[str] = None) -> list[Approval]:
        stmt = select(Approval).where(Approval.status == "pending")
        if user_id is not None:
            stmt = stmt.where(Approval.user_id == user_id)
        stmt = stmt.order_by(Approval.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_all(self, user_id: Optional[str] = None) -> list[Approval]:
        stmt = select(Approval)
        if user_id is not None:
            stmt = stmt.where(Approval.user_id == user_id)
        stmt = stmt.order_by(Approval.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        approval: Approval,
        status: str,
        decision_reason: Optional[str] = None,
    ) -> Approval:
        approval.status = status
        approval.decision_reason = decision_reason
        from datetime import datetime

        approval.decided_at = datetime.now()
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        await self.session.refresh(approval)
        return approval
