## Summary
- Pause the current graph-visual context feature work to avoid SSRF issues flagged in security scans
- Implement new per-file action menu (⋮) with options:
  1. Share file (opens existing share dialog with permanent & temporary links)
  2. History (list versions + restore)
  3. Move to trash (soft delete + note that file is available for 30 days via bot)
- Ensure menu order = Share → History → Move to Trash
- Add history UI (modal with date + restore per version)
- Add share option to the 3-dot menu so users don’t have to scroll
- Add confirmation string for Move to trash ("הקובץ זמין למשך 30 יום בסל המיחזור דרך הבוט")
- Document SSRF risk and create follow-up to revisit graph feature later

## Context
- Current "Visual Context" branch triggered SSRF (DNS rebinding) alarms in CodeQL/Copilot
- We need to revert or park that work until we have a robust approach (e.g., IP validation with one lookup)
- In parallel, ship the file menu + history & sharing improvements

## Tasks
- [ ] Remove or disable the new graph-fetch code path from the branch
- [ ] Implement the 3-option file action menu and related modals
- [ ] Integrate history API (or stub) to show file versions + restore button
- [ ] Integrate existing sharing modal into the menu
- [ ] Soft-delete endpoint + warning copy in the UI
- [ ] Add doc snippet for new UI + mention graph feature will return once SSRF mitigation is ready
- [ ] Optional: create follow-up ticket for implementing safe IP validation (if not done yet)"}