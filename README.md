CONCIERGE PI CHEATSHEET
Updated 2026-04-27

RESTART AFTER EDITS:
  sudo systemctl restart concierge

WEB INVENTORY (bar + recipes + call log):
  http://concierge.local:8080
  (or http://10.0.0.50:8080)
  Runs on concierge-inventory-web.service

STATUS:
  sudo systemctl status concierge
  journalctl -u concierge -f     (live logs)

EDITING:
  Edit concierge.py then restart.
  Or scp from PC.

GIT:
  cd ~/concierge
  git status
  git add concierge.py README.md
  git commit -m "msg"
  git push

NEVER COMMIT: concierge.db, *.bak, large files

NOTES:
- Dial 2 = Grok Voice (think-fast-1.0)
- Sue (dial 4) reads recipes from DB
- Restart web UI: sudo systemctl restart concierge-inventory-web

Beep boop. Restart after changes.
