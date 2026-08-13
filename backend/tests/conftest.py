import pytest


@pytest.fixture(autouse=True)
def _ensure_tools_registered():
    """Make sure built-in tools are registered before each test."""
    from app.tools import registry
    from app.tools.current_time import CurrentTimeTool

    if registry.get_tool("current_time") is None:
        registry.register(CurrentTimeTool())
    yield
