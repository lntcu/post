# Posture and Eye Monitor

A small, local webcam app that compares your visible upper-body pose with a five-second upright baseline and tracks simple eye cues. It uses MediaPipe's packaged Pose and Face Mesh models; it does not upload frames or save video. Optional labeled writing recordings can train a local change detector. Starting the app does not download a model.

## Install

Use **Python 3.10–3.12** on macOS, Windows, or Linux. MediaPipe 0.10.21 is pinned because this app uses its packaged Pose solution and that release provides wheels for these Python versions ([PyPI release files](https://pypi.org/project/mediapipe/0.10.21/)). Python 3.13+ is not supported by this pinned release.

```bash
python3.12 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python main.py
```

The app opens a local web dashboard at **http://127.0.0.1:8765**. Click **Start session** to turn on the camera and begin guided setup. The Python process handles video and detection; the browser shows the live feed, setup guidance, measurements, and preferences together. No Python GUI opens by default. Use Dashboard for analytics, Live monitor for simultaneous posture and writing tracking, and Settings for preferences. Settings → Language switches the display between English and Simplified Chinese; the choice is saved in the browser. Body joints, eye outlines, and the selected hand have labeled landmark overlays. Only visible, detected points are connected; blue marks body tracking, amber marks eyes, and mint marks the selected writing hand. Overlays are drawn after measurements. The camera-free demo labels its example landmarks SIMULATED. A shared camera uses one combined feed; a separate desk camera appears alongside the posture feed. Old Writing links redirect to Live monitor. Stop the server with **Ctrl+C** in the terminal.

## App screens, analytics, voice, and writing

The interface now has four dedicated screens: **Dashboard**, **Live monitor**, **Writing studio**, and **Settings**. Launch `python main.py --app` for a dedicated Chrome/Edge app window when an installed compatible browser is available; otherwise it opens the normal browser. You can also install Still using its sidebar button or the browser’s app menu where supported. The local Python server must stay running. The offline shell shows a disconnected state; it never caches video, live measurements, or analytics responses.

**Analytics:** Start and end sessions from the app toolbar. The dashboard shows sampled active time, time near your personal reference, tracking coverage, recurring issues, movement resets, average estimated blink rate, and writing-hand time. It includes minute-by-minute charts, 7/30-day views, per-session details, and CSV export. “Near reference” uses only tracked posture time as its denominator; partially visible measurements are assessed only where available. A tracked interval requires every configured posture camera to have an available assessment; changes in either view count as changed time. Coverage uses those tracked intervals divided by active time, including setup/untracked intervals. Visible body measurements can still be partial and are labeled in Live monitor. Pauses and long observation gaps are excluded. These are visual tracking summaries, not health or performance scores. Each sample represents approximately one second, so very brief events may be missed.

Session summaries are saved locally in `.posture-eye-analytics.sqlite3` beside the preferences file (normally `~/.posture-eye-analytics.sqlite3`), checkpointed every 15 seconds, and capped at 200 sessions. Minute trends retain the latest 24 hours per session. A recovered checkpoint can be shown after an unexpected shutdown. Settings can disable future saves, export CSV, or clear all history after ending monitoring. Changing the saving preference starts a new analytics segment so private intervals are never saved retroactively. Demo sessions stay in memory and never enter real history. No video, images, or raw landmark coordinates are retained.

**Spoken warnings:** In Settings, enable **Speak active warnings**, select a local system voice, choose its volume/rate, and save. Use **Enable & test voice** once per window if your browser requires user activation. Starting or resuming a session also arms voice reminders. Warnings follow the same categories, cooldown, snooze, and quiet hours as dashboard alerts. Only voices reported as local by the browser are used. Speech requires an open app window; background browser/OS behavior can affect delivery. The app coordinates voice ownership between tabs to avoid duplicate speech. The manual voice test works even when automatic speech is off.

**Live guidance and score:** The shared posture-and-writing panel shows immediate suggestions, sustained corrections (amber), and sustained changes at least twice a measurement threshold (red). Green means visible measurements are near the reference; blue indicates a suggestion. Color is accompanied by a text label. These levels describe deviation, not medical urgency. The 0–100 reference-alignment score averages visible measurements within each body camera and available measurement families within the writing view, then weights enabled views equally. Each measurement scores `100 × (1 − min(deviation / threshold, 2) / 2)`; one-sided posture checks ignore decreases. Missing measurements are excluded and marked partial; an entirely unavailable enabled view, pause, or stale feed makes the combined score unavailable. The score does not assess handwriting quality or grip correctness. Reminder settings, snooze, and quiet hours control notifications while live guidance remains visible.

Writing mode adapts posture corrections to paper positioning and forearm support, and combines these with hand guidance. Suggestions to relax the grip and adjust the paper follow [UCLA handwriting ergonomics guidance](https://ergonomics.ucla.edu/injuries-and-prevention/handwriting-tips). The camera cannot verify pressure, pen contact, or comfort.

**Writing and posture in Live monitor:** Enable hand tracking, select the left or right hand in Settings, and start a session. Open Live monitor → Measurements → **Start grip & wrist calibration** to start or reset the live camera reference. The default uses the front camera; an existing dedicated desk camera can also be used. No second writing view or camera triangulation is required. Show the wrist, thumb, index, and middle fingers; an elbow in the same view adds projected wrist alignment. Write normally across the page for **twelve seconds** to learn a personal reference. Tripod, quadrupod, lateral, and adapted grips use their own reference; the app does not infer a grip type. Calibration learns bounded movement allowances using medians and median absolute deviations. References never drift automatically. Estimated MediaPipe world landmarks supply scale- and rigid-rotation-invariant finger distances and joint angles. When world landmarks are unavailable, image geometry is used; calibration never mixes the two coordinate sources. Finger measurements now include index and middle finger joints, thumb joints, thumb opposition, and index–middle spacing. Wrist and pen measurements remain explicitly projected image measurements. A short median filter reduces jumps and sustained changes use the reminder delay. Relearn after changing pen, camera setup, marker placement, grip, or writing style.

**Marked pen tracking:** Under Settings → Hand tracking, enable **Track blue and green pen markers** (on by default). Put a small blue marker near the nib and a green marker farther up the shaft, both visible from the camera. Keep their placement fixed. Use saturated blue/green stickers or bands with good lighting and a plain background; the detector uses HSV color regions near the selected hand. It requires a unique plausible marker pair, and is not a general unmarked-pen detector. Pen angle relative to the hand, projected distances from the thumb/index/middle fingertips to the shaft, and signed hold position along the shaft relative to the blue marker contribute to a separate pen alignment score. The blue marker is **not** a detected physical tip, and projected proximity does not prove finger or paper contact. Both markers should be visible during calibration; if they become visible only afterward, reset the hand reference.

**Writing scores:** Hand measurements shows separate Fingers, Wrist, Pen, and Sensor force scores. Each averages its available reference deviations; the combined Grip & wrist score gives available families equal weight so adding correlated finger features does not drown out wrist or pen changes. Missing families are shown as unassessed, and coverage is partial. These are reference-alignment scores, not validated grip-quality scores. Feature allowances are initial engineering defaults plus personal movement allowances, not ergonomic cutoffs. Comfort remains a separate unsaved self-report.

**Labeled recordings and learning:** The Writing setup panel has been removed from Measurements. Developer recording commands remain available through the authenticated local API: `writing_record_start`, `writing_record_label`, and `writing_record_stop`; download from `/api/writing-recording.jsonl`. Label normal writing, deliberate grip changes, same-grip view changes, or tracking failures as they occur. Recordings contain time-stamped numeric measurements, calibration phases, derived metrics and labels; **no images/video**. Recording is opt-in, held in memory (at most ten minutes/6,000 samples), and downloaded as JSONL. A new recording replaces the previous one; server exit clears it. Download before starting another recording. Collect several sessions per person, with normal writing before and after deliberate changes. Use a different participant for evaluation; include view changes to test unwanted responses.

Train and evaluate locally using the app's Python environment:

```bash
python writing_validation.py writer-a-session1.jsonl writer-b-session1.jsonl --holdout-participant writer-b --output writing-change-model.json
POSTURE_WRITING_MODEL=/absolute/path/writing-change-model.json python main.py
```

The regularized change classifier learns from labeled reference deviations; normal writing and camera rotation are negative examples, deliberate grip changes are positive examples, and tracking failures are reported separately. Training balances sessions/classes, rejects duplicate sessions, keeps the held-out participant out of feature selection and training, and refuses to mix 2D and 3D training sources. The report includes held-out normal false-positive rate, grip-change recall, change rates on view changes, tracking coverage, and reference false alerts per minute of observed normal writing. Rates are frame-level unless stated otherwise; adjacent frames are correlated. Run new held-out participants and sessions before claiming an accuracy improvement. The loaded detector's experimental change likelihood appears separately from alignment and does not control reminders or certify grip quality. Demo recordings are rejected by the trainer because they contain synthetic data. No pretrained change model or real-user accuracy claim is included.

**Optional force sensor:** The camera does not estimate squeezing. A calibrated hardware adapter can send separate `grip_force` or `tip_force` readings in **newtons** to the authenticated localhost command endpoint. Tip force is not grip force. Read `/api/session` for the local token, then POST `/api/command` with header `X-Dashboard-Token` and a JSON body such as:

```json
{"action":"writing_pressure","kind":"grip_force","newtons":2.4,"device":"my-calibrated-grip-sensor"}
```

Send current readings at least 5 times per second; readings expire after 0.5 seconds. Convert the hardware's raw units to newtons using its calibration before sending. Connect the sensor before the twelve-second reference calibration. Connecting afterward requires resetting the reference to score force; raw readings still appear immediately. Changing device identity forces recalibration. Sensor force uses its own score family and does not establish healthy force levels. Hardware and vendor-specific drivers are not bundled.

**Writing limitations:** Estimated 3D landmarks can be wrong under occlusion. Marked-pen and wrist features remain sensitive to viewpoint. The app does not measure paper contact, comfort, pain, handwriting quality, or grip correctness. Force is available only from a calibrated external sensor. Learned predictions are only as useful as the labels and representative held-out evaluation. The app does not prescribe one universally correct pen grip.

**Camera-based tiredness reminders:** The Tiredness cues card uses the existing local Face Mesh eye measurements. It recommends a two-minute break after a closure of at least 1.5 seconds, frequent closure (at least 25% of the recent eye window after 20 seconds of observation), or three completed closures lasting at least 0.5 seconds in 60 seconds. Ordinary short blinks and low blink rate alone do not trigger tiredness reminders. The recommendation stays visible for 15 seconds after the last cue. Missing eye tracking clears the evidence; pauses, camera changes, and recalibration start fresh. These thresholds are unvalidated comfort heuristics, not a determination of fatigue. Lighting, glasses, and face angle can affect them. No additional models or uploads are required.

Use **Take a 2-min break** on the card to pause cameras and snooze reminders. A centered circular countdown replaces the live feed. Choose **End break early** to resume immediately, or **Resume session** after the countdown ends. Monitoring never restarts automatically; a separate manual snooze is preserved. **Tiredness** under Remind me about in Settings controls dashboard, desktop, and spoken notifications independently of eye and movement reminders; snooze, quiet hours, and notification cooldown still apply. Live cues remain visible when reminders are muted. Demo mode uses synthetic eye closures to demonstrate the prompt.

**Focus and break tools:** Start or cancel a configurable focus timer from the dashboard. Taking a two-minute break pauses cameras and snoozes reminders; monitoring resumes only when you choose Resume. Focus timers run while the server is running, including with the dashboard on another screen, and do not persist across a server restart.

## Web dashboard

- **Guided setup:** choose a camera index and front/side/automatic view under Cameras & preferences, save, then start setup. Follow the framing and lighting cues and hold comfortably upright for five seconds. An optional phone camera can be configured here using its webcam index or direct MJPEG/RTSP URL. Both views appear in the same dashboard and calibrate independently.
- **Live measurements:** see changes from your personal reference in degrees or body-relative ratios, the active threshold, and specific suggested adjustments. There is no health score. Missing measurements are explicitly excluded.
- **Tracking coverage:** Available means all relevant measurements have visible landmarks and a baseline; Limited means only some are available; Unavailable means no current assessment can be made. These labels describe coverage, not validated accuracy or diagnostic confidence. Eye coverage is reported separately.
- **Personal reminders:** choose sensitivity, posture delay, stillness interval, separate posture/eye/movement reminders, macOS desktop notifications, and their cooldown. Snooze for 5, 10, or 30 minutes or set quiet hours (computer-local time, including overnight ranges). Quiet hours and snooze suppress reminders while measurements continue. Qualified reminders appear on the next dashboard update, with no extra display delay. The posture delay setting controls how long a deviation must persist before qualification. A reminder does not repeatedly notify while it remains active. Demo mode never sends desktop notifications.
- **Privacy controls:** Pause releases both cameras and clears live measurements; Resume recalibrates. Stop turns off monitoring. Recalibrate after moving either camera. Each camera runs independently and retries connection failures; a delayed feed is marked unavailable.

Preferences are saved in `~/.posture-eye-monitor.json`; calibration starts fresh each session. Set `POSTURE_MONITOR_SETTINGS` to use another preferences file. No video, images, or raw landmarks are saved; optional numeric session summaries are stored locally as described above. The server binds only to `127.0.0.1`, checks the local request host, and requires a session token for control changes. It is intended for this computer, not public hosting or port forwarding. Closing the browser does not stop the Python server or monitoring; use End session or Ctrl+C.

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
- `--sound` enables a single Windows system beep when a posture or eye warning begins. Desktop notifications are off by default. Enable them in Settings on macOS; use `--no-notifications` to disable a previously saved preference. macOS notification settings for the app running the script may control whether banners appear.

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

`web_server.py` serves the loopback dashboard, runs independent camera/detection workers, and handles web preferences and alerts. `web/` contains the app shell, offline shell service worker, and browser speech controls. `analytics.py` tracks local session aggregates, and `writing_detector.py` measures personal hand-reference changes. `main.py` provides shared calibration logic and the optional legacy camera previews. `debug_tui.py` contains the only detailed debug interface. It requests a 1280 × 720 camera image for eye landmarks and uses a smaller image for posture inference. `posture_detector.py` extracts torso, shoulder, arm, head, and relative face-size geometry. `activity_monitor.py` times nearly unchanged poses. `eye_detector.py` uses Face Mesh eye landmarks to estimate openness, count blinks, and measure closure patterns. `alerts.py` times consecutive poor posture using a monotonic clock. All processing stays on the computer; dependencies install from PyPI. A phone network camera, if selected, supplies only a local video stream to the laptop.

Run the geometry and timing checks with:

```bash
python -m unittest discover -s tests
```

The large Live monitor score is a time-weighted session average of available posture, eye, and writing subscores. Smaller rings remain live. Pauses, unavailable scores, and observation gaps are excluded; tracked samples contribute in proportion to elapsed time. New sessions (including privacy segments) reset the average. The server retains the aggregate across page refreshes and includes it in optional local session summaries. An older running server uses an observed average retained in the tab and explicitly labeled “since view opened” until the server is restarted.
