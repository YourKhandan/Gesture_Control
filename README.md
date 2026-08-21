# HandDeck (Streamlit version)

Gesture-controlled slide viewer. Upload a `.pptx`/`.ppt`/`.pdf`, allow camera
access in your browser, and page through it with hand gestures.

## Files
- `app.py` — frontend: file upload UI, slide viewer, wires up the webcam widget.
- `upload_converter.py` — backend: pptx/ppt → pdf (via LibreOffice) → images (via PyMuPDF). PDFs skip straight to the image step.
- `gesture_control.py` — backend: the original OpenCV contour/convexity-defect finger counter, now driven by `streamlit-webrtc` instead of `cv2.VideoCapture` + `pyautogui` + `tkinter`.
- `requirements.txt` — Python deps.
- `packages.txt` — system (apt) deps — just `libreoffice`, needed for the pptx→pdf step.

## Why the original script had to change
- **`pyautogui`** pressed keys on whatever machine ran the script. On a hosted
  Streamlit app, that machine is Anthropic/Streamlit's server — not your
  laptop — so those key presses would go nowhere useful. Gestures now update
  the app's own slide state instead of pressing OS-level keys.
- **`cv2.VideoCapture(0)`** opens a camera attached to the machine running the
  code — again, the server, not your device. `streamlit-webrtc` replaces this:
  it prompts the *visitor's browser* for camera permission and streams their
  frames to the server for the same OpenCV processing.
- **`tkinter` / `cv2.imshow`** windows only make sense on a local desktop.
  They're replaced by Streamlit's web UI.

## Run locally
```bash
pip install -r requirements.txt
# LibreOffice must also be installed locally if you want pptx upload support:
#   macOS:   brew install libreoffice
#   Ubuntu:  sudo apt install libreoffice
#   Windows: install LibreOffice, ensure `soffice` is on PATH
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Push this folder to a GitHub repo (keep `app.py`, `upload_converter.py`,
   `gesture_control.py`, `requirements.txt`, `packages.txt` all at the repo root).
2. Go to https://share.streamlit.io → "New app" → point it at the repo, branch,
   and `app.py`.
3. Streamlit Cloud reads `packages.txt` automatically and apt-installs
   LibreOffice before your app starts — no extra config needed.
4. Camera access requires HTTPS; Streamlit Cloud serves your app over HTTPS
   by default, so the browser's permission prompt will work out of the box.

## Known limitation
WebRTC (the tech behind the camera stream) sometimes struggles to connect
across strict corporate/school networks or certain NATs, since only a public
STUN server is configured here (free, no signup). If gesture control won't
connect for some visitors, the fix is adding a TURN server (e.g. via
Twilio's or Cloudflare's free tier) to `RTC_CONFIGURATION` in `app.py`.
