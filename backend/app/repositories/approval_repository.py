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
        await self.session.commit()
        await self.session.refresh(approval)
        return approval

    async def get(self, approval_id: str) -> Optional[Approval]:
        result = await self.session.execute(
            select(Approval).where(Approval.id == approval_id)
        )
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
        await self.session.commit()
        await self.session.refresh(approval)
        return approval
