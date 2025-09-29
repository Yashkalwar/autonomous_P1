"""
Simplified Agents implementation for the workflow system (without CrewAI dependency).
"""


class NotifierAgent:
    """Simple notification agent for status updates."""
    
    def __init__(self):
        self.role = 'Notifier'
    
    def send_notification(self, event_type: str, message: str):
        """Send a notification (currently just prints)."""
        print(f"🚀 [NOTIFICATION] {message}")
