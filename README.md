# Concierge Rotary Phone - Maintenance Guide

**Last updated:** 2026-04-27

This document lives on the Pi at `~/concierge/README.md`. Read it with:
```bash
cat ~/concierge/README.md | less
```

## Quick Commands

### Restart the phone service (after code changes)
```bash
sudo systemctl restart concierge
```

### Check if it's running
```bash
sudo systemctl status concierge
```

### Live logs
```bash
journalctl -u concierge -f
```

### Stop / Start
```bash
sudo systemctl stop concierge
sudo systemctl start concierge
```

## Editing Code

1. Edit `concierge.py` (main file)
2. **Always restart** the service after changes (`sudo systemctl restart concierge`)
3. Test by picking up the phone and dialing your persona

**Pro tip:** Edit on your main PC, then copy to Pi:
```bash
scp concierge.py camstar915@concierge.local:~/concierge/
```

## Git / GitHub

```bash
cd ~/concierge

# See what changed
git status

# Stage only the files you want (DO NOT commit concierge.db)
git add concierge.py README.md

# Commit
git commit -m "Update to grok-voice-think-fast-1.0 model"

# Push
git push
```

**Never commit:**
- `concierge.db`
- `*.bak`
- Large audio files

## Important Notes

- **API Keys**: Set via environment in the systemd service (see `/etc/systemd/system/concierge.service`)
- **Model switching**: Change the `?model=` parameter in `XAI_URL` or `URL`
- **New personas**: Add entries to the `PERSONAS` dictionary in `concierge.py`
- **Audio issues**: Check `arecord`/`aplay` devices with `arecord -l` and `aplay -l`
- **Dial 2**: Currently uses xAI Grok Voice (now on `grok-voice-think-fast-1.0`)

## Useful Paths
- Main code: `~/concierge/concierge.py`
- Systemd service: `/etc/systemd/system/concierge.service`
- Logs: `journalctl -u concierge`

---

**Beep boop. Edit responsibly. Restart after every change.**
