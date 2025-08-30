"""
GitHub service - thin abstraction to centralize GitHub API use.
For now it proxies to existing GitHub handlers/utilities to keep behavior.
"""
from typing import Any, Dict, List, Optional, Tuple

from github_menu_handler import GitHubMenuHandler  # compatibility bridge


def get_handler() -> GitHubMenuHandler:
    return GitHubMenuHandler()

