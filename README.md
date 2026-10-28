# Posture and Eye Monitor

A small, local webcam app that compares your visible upper-body pose with a five-second upright baseline and tracks simple eye cues. It uses MediaPipe's packaged Pose and Face Mesh models; it does not train a model, upload frames, or save video. Starting the app does not download a model.

## Install

Use **Python 3.10–3.12** on macOS, Windows, or Linux. MediaPipe 0.10.21 is pinned because this app uses its packaged Pose solution and that release provides wheels for these Python versions ([PyPI release files](https://pypi.org/project/mediapipe/0.10.21/)). Python 3.13+ is not supported by this pinned release.

```bash
python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

The app opens a local web dashboard at **http://127.0.0.1:8765**. Click **Start setup** to turn on the camera. The Python process handles video and detection; the browser shows the live feed, setup guidance, measurements, and preferences together. No Python GUI opens by default. Stop the server with **Ctrl+C** in the terminal.

## Web dashboard

- **Guided setup:** choose a camera index and front/side/automatic view under Cameras & preferences, save, then start setup. Follow the framing and lighting cues and hold comfortably upright for five seconds. An optional phone camera can be configured here using its webcam index or direct MJPEG/RTSP URL. Both views appear in the same dashboard and calibrate independently.
- **Live measurements:** see changes from your personal reference in degrees or body-relative ratios, the active threshold, and specific suggested adjustments. There is no health score. Missing measurements are explicitly excluded.
- **Tracking coverage:** Available means all relevant measurements have visible landmarks and a baseline; Limited means only some are available; Unavailable means no current assessment can be made. These labels describe coverage, not validated accuracy or diagnostic confidence. Eye coverage is reported separately.
- **Personal reminders:** choose sensitivity, posture delay, stillness interval, separate posture/eye/movement reminders, macOS desktop notifications, and their cooldown. Snooze for 5, 10, or 30 minutes or set quiet hours (computer-local time, including overnight ranges). Quiet hours and snooze suppress reminders while measurements continue. A reminder does not repeatedly notify while it remains active. Demo mode never sends desktop notifications.
- **Privacy controls:** Pause releases both cameras and clears live measurements; Resume recalibrates. Stop turns off monitoring. Recalibrate after moving either camera. Each camera runs independently and retries connection failures; a delayed feed is marked unavailable.

Preferences are saved in `~/.posture-eye-monitor.json`; calibration starts fresh each session. Set `POSTURE_MONITOR_SETTINGS` to use another preferences file. No video, images, or measurement history is saved. The server binds only to `127.0.0.1`, checks the local request host, and requires a session token for control changes. It is intended for this computer, not public hosting or port forwarding. Closing the browser does not stop the Python server or monitoring; use Stop camera or Ctrl+C.

```bash
python main.py --port 8765       # choose a different localhost port if needed
python main.py --no-browser      # open the printed address manually
python main.py --demo            # synthetic feed and stats; no camera access
python main.py --legacy-gui      # previous separate OpenCV windows
python main.py --tui             # existing terminal diagnostics + previews
```

Desktop banners are currently supported on macOS. In-dashboard reminders work on all supported platforms. The web dashboard requires no additional dependencies or frontend build. Camera indices are platform-specific; start with 0 and use the preview to check the selected device.

If your system uses `python3.10` or `python3.11`, substitute that command on the first line. Allow webcam access when prompted. On Linux, a desktop display server is only needed for the optional legacy OpenCV windows.

## Tracking behavior and legacy preview controls

Use the laptop screen at a normal viewing angle so your face and both shoulders are visible. Hips and elbows are optional. The app requests a wide 1280 × 720 camera mode and resets hardware zoom where supported. The preview tells you when to move closer, move back, recenter, or turn side-on. Once framed, sit upright and hold still for five seconds while the app calibrates. Moving during calibration restarts the countdown. It opens a camera preview with status and up to three specific suggestions. Use `--tui` for detailed live measurements in the terminal; there is no debug GUI window. The preview names issues such as a turned head, raised shoulders, or infrequent blinking and suggests an adjustment. A `Poor` pose receives a correction warning after five continuous seconds. A good pose or lost landmarks clears that posture timer. On macOS, distinct posture and eye issues, the stillness reminder, lost tracking, and phone disconnection can send system notifications while the camera window is behind another app. Repeated notifications for the same issue are limited to once per minute. These suggestions are webcam-based comfort cues, not medical diagnoses.

The posture view measures shoulder tilt, head tilt, head turn, and shoulder elevation from the upper body. Elbow spread is checked when elbows are visible; torso lean is checked only when hips are visible. A side view can also check forward head position. It compares each available measurement to your upright baseline. Face size relative to calibration gives a **closer to camera** cue; this is not an absolute eye-to-screen distance. A separate timer prompts a position change after 20 minutes of nearly unchanged visible upper-body pose. Normal movement resets it. [OSHA describes head, shoulder, arm, viewing position, and prolonged static posture as workstation considerations](https://www.osha.gov/etools/computer-workstations).

Keep your face visible to track eye openness. The app measures the left and right eye ratios, estimates an open-eye reference from recent frames, and counts brief closures as blinks. A rolling blink count appears immediately; an estimated blink rate appears after five seconds. It also shows continuous closure, the fraction of recent time with eyes closed, and time since the last blink. Low blink rate or a long period without a blink prompts a **blink and look away** warning. Long closure or frequent closure prompts a **rest if tired** warning. These are visual cues, not diagnoses of eye strain, fatigue, or drowsiness. Glasses, lighting, face angle, and face size can affect measurements. Keep at least one eye clearly visible; a front-facing view is most reliable. The [American Academy of Ophthalmology recommends regular blinking and looking away from screens](https://www.aao.org/eye-health/diseases/computer-usage).

- Press **R** to recalibrate after moving your chair or either camera.
- Press **V** to cycle camera view mode.
- Press **Q** or **Esc** to quit. These keys work while either camera window is focused.
- For a side view, run `python main.py --view side` for torso lean and forward-head checks.
- For a front view, run `python main.py --view front` for head and shoulder checks; torso lean is added when hips happen to be visible.
- The default `--view auto` estimates the view from shoulder spacing. If the view switches during use, choose it explicitly and recalibrate.
- Use `--camera 1` (or another index) if camera 0 is not the intended webcam.
- `--alert-seconds 5` sets the continuous-poor-posture warning delay.
- `--sound` enables a single Windows system beep when a posture or eye warning begins. On macOS, system notifications are enabled by default for posture, eye, activity, and camera warnings; use `--no-notifications` to disable them. macOS notification settings for the app running the script may control whether banners appear.

## Phone side camera

In web mode, both feeds appear in the dashboard. Use **Recalibrate** to reset both references; the separate window and keyboard controls below apply to legacy mode.

Connect a phone as a second camera while the laptop webcam keeps tracking the front view and eyes. Set the phone at your side, roughly shoulder height, with your ear, nose, and shoulder visible. Your hips can be outside the phone frame, so the phone can sit closer. Each camera calibrates independently for five seconds. The laptop shows a **Phone side view** live preview with its own posture status and forward-head detection. It also checks torso lean when a hip is visible. A poor side posture triggers the normal continuous-warning timer. The side baseline uses upper-body landmarks, and torso lean is omitted when the hip is out of frame. Press **R** to recalibrate both views after moving either camera.

Choose one connection method:

- **USB or system webcam mode:** connect the phone and enable its webcam feature (for example, iPhone Continuity Camera or Android USB webcam mode). Find its OpenCV camera index, then run `python main.py --view front --side-camera 1`. The side index must differ from `--camera`.
- **Network camera app:** start an MJPEG or RTSP stream on the phone while it and the laptop share a local network. Use the stream's direct video URL, for example `python main.py --view front --side-url http://192.168.1.23:8080/video`. A web page URL alone will not work; it must be a video stream readable by OpenCV.

The phone stream is read locally by the laptop. If it drops, the side preview shows a disconnected state and the app retries every three seconds. Reconnection starts a fresh side calibration. Phone camera permissions and network access depend on the phone's webcam or streaming app.

## Debug terminal dashboard

Run `python main.py --tui` from an interactive terminal to see text measurements. The camera preview remains open; adding a phone opens the side preview too. The terminal shows posture and eye measurements, pose landmark visibility, FPS, calibration, and alert timing. Resize the terminal to at least 80 columns by 31 rows, or 39 rows when using a phone.

Press **V** to cycle auto/front/side camera mode, **R** to recalibrate, and **Q** to quit. After changing camera position or view, recalibrate. Front-specific measurements are blank in side mode; forward-head position is blank in front mode. The terminal dashboard is read-only; use the web dashboard to personalize warning sensitivity and reminders.

To verify the dashboard and warning sequence without a webcam, run `python main.py --tui --demo`. It repeats synthetic upright, poor, corrected, missing-landmark, and prolonged eye closure phases. The source label clearly reads `DEMO (synthetic)`; this mode checks the UI and timing, not MediaPipe or camera accuracy.

The score is a relative visual deviation from your calibration, **not** a health score. Thresholds are defined in `Thresholds` in `posture_detector.py`. Camera placement, loose clothing, occlusion, and movement affect landmark quality. Front-specific cues need both sides of the face and shoulders; a side camera is better for forward-head position. Shoulder and elbow cues are only available when those joints are visible. The nearly still timer measures visible movement; it cannot determine whether you have been continuously using a screen. A single webcam cannot provide a medical posture assessment.

## Implementation

`web_server.py` serves the loopback dashboard, runs independent camera/detection workers, and handles web preferences and alerts. `web/` contains its HTML, CSS, and JavaScript. `main.py` provides shared calibration logic and the optional legacy camera previews. `debug_tui.py` contains the only detailed debug interface. It requests a 1280 × 720 camera image for eye landmarks and uses a smaller image for posture inference. `posture_detector.py` extracts torso, shoulder, arm, head, and relative face-size geometry. `activity_monitor.py` times nearly unchanged poses. `eye_detector.py` uses Face Mesh eye landmarks to estimate openness, count blinks, and measure closure patterns. `alerts.py` times consecutive poor posture using a monotonic clock. All processing stays on the computer; dependencies install from PyPI. A phone network camera, if selected, supplies only a local video stream to the laptop.

Run the geometry and timing checks with:

```bash
python -m unittest discover -s tests
```
