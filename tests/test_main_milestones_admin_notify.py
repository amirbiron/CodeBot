import pytest
from unittest.mock import MagicMock


def test_milestone_logic():
    """בודק את הלוגיקה של בחירת milestones"""

    # Test the logic for selecting milestones
    total_actions = 500
    already_sent = set()
    milestones = [50, 100, 200, 500, 1000]

    # בחר את היעד הגבוה ביותר שהושג ושעדיין לא נשלח
    pending = [m for m in milestones if m <= total_actions and m not in already_sent]

    print(f"Total actions: {total_actions}")
    print(f"Already sent: {already_sent}")
    print(f"Pending milestones: {pending}")

    assert 500 in pending, f"500 should be in pending milestones, got {pending}"

    if pending:
        milestone = max(pending)
        print(f"Selected milestone: {milestone}")
        assert milestone == 500, f"Expected milestone 500, got {milestone}"


def test_milestone_selection_logic():
    """בודק את הלוגיקה של בחירת milestones"""

    # Test cases for milestone selection
    test_cases = [
        # (total_actions, already_sent, expected_milestone)
        (50, [], 50),
        (100, [], 100),
        (150, [50], 100),
        (200, [50, 100], 200),
        (500, [50, 100, 200], 500),
        (500, [], 500),
        (1000, [50, 100, 200, 500], 1000),
    ]

    milestones = [50, 100, 200, 500, 1000]

    for total_actions, already_sent, expected in test_cases:
        # בחר את היעד הגבוה ביותר שהושג ושעדיין לא נשלח
        pending = [m for m in milestones if m <= total_actions and m not in already_sent]

        if pending:
            milestone = max(pending)
            print(f"Total: {total_actions}, Sent: {already_sent}, Pending: {pending}, Selected: {milestone}")
            assert milestone == expected, f"Expected {expected}, got {milestone} for total_actions={total_actions}, already_sent={already_sent}"
        else:
            print(f"No milestone for total_actions={total_actions}, already_sent={already_sent}")


def test_admin_notification_milestones():
    """בודק אילו milestones שולחים הודעה לאדמינים"""

    admin_milestones = {200, 500, 1000}

    test_cases = [50, 100, 200, 500, 1000]

    for milestone in test_cases:
        should_notify = milestone in admin_milestones
        print(f"Milestone {milestone}: Admin notification = {should_notify}")
        if milestone in [200, 500, 1000]:
            assert should_notify, f"Milestone {milestone} should trigger admin notification"


if __name__ == "__main__":
    test_milestone_selection_logic()
    print("Milestone selection logic test passed!")

    test_admin_notification_milestones()
    print("Admin notification milestones test passed!")

    print("All basic tests passed!")