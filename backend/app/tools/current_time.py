"""CurrentTimeTool: returns the current local date and time."""
from datetime import datetime

from app.tools.base import BaseTool


class CurrentTimeTool(BaseTool):
    name = "current_time"
    description = (
        "返回当前的日期和时间。当用户询问现在几点、今天几号、当前时间等时调用。"
    )

    async def execute(self, arguments: dict, user_id: str = "") -> str:
        now = datetime.now()
        return now.strftime("%Y-%m-%d %H:%M:%S %A")
