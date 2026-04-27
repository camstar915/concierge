CONCIERGE PI CHEATSHEET
Updated 2026-04-27

RESTART AFTER EDITS:
  sudo systemctl restart concierge

STATUS:
  sudo systemctl status concierge
  journalctl -u concierge -f     (live logs)

EDITING:
  Edit concierge.py then restart above.
  Or edit on PC then: scp file camstar915@concierge.local:~/concierge/

GIT:
  cd ~/concierge
  git status
  git add concierge.py README.md
  git commit -m "your message"
  git push

NEVER COMMIT: concierge.db, *.bak, large wav files

QUICK NOTES:
- Dial 2 = xAI Grok (now on grok-voice-think-fast-1.0)
- Add personas in PERSONAS dict
- API keys in systemd service file

Beep boop. Restart after every change.
