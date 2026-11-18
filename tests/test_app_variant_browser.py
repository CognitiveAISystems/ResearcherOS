"""Main supports only Quick Navigation; exercise its settings in a browser."""
import test_chat_conversations_e2e as fixture
from test_quick_navigation_default_browser import smoke

if __name__ == "__main__":
    fixture.smoke = smoke
    fixture.check()
