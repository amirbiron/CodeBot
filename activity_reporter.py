"""
Basic activity reporter - minimal functionality
"""

class SimpleActivityReporter:
    def __init__(self, mongodb_uri=None, service_id=None, service_name=None):
        """
        Basic activity reporter with minimal functionality
        """
        self.connected = False  # Disable for simplicity
    
    def report_activity(self, user_id):
        """Basic activity reporting - simplified"""
        # Do nothing for now - keeping system simple
        pass

def create_reporter(mongodb_uri=None, service_id=None, service_name=None):
    """Create a simple reporter"""
    return SimpleActivityReporter()