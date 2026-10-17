@echo off
REM Opens a free Cloudflare quick tunnel to the local game. Look for the https://....trycloudflare.com URL in the output.
REM Install once with:  winget install --id Cloudflare.cloudflared
cloudflared tunnel --url http://127.0.0.1:5000
pause
