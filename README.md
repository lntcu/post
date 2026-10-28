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

If your system uses `python3.10` or `python3.11`, substitute that command on the first line. Allow webcam access when prompted. On Linux, a desktop display server is needed for the OpenCV window.

## Use

Position the camera so your face, shoulders, hips, and preferably elbows are visible. Sit upright and hold still for five seconds while the app calibrates. It opens two windows: a camera preview with status and up to three specific suggestions, and a separate **Measurements and Debug** window with every live indicator. The preview names issues such as a turned head, raised shoulders, or infrequent blinking and suggests an adjustment. A `Poor` pose receives a correction warning after five continuous seconds. A good pose or lost landmarks clears that posture timer. These suggestions are webcam-based comfort cues, not medical diagnoses.

The posture view measures torso lean, shoulder tilt, forward head position in side view, and head tilt, head turn, shoulder elevation, and elbow spread in front view. It compares each available measurement to your upright baseline. Face size relative to calibration gives a **closer to camera** cue; this is not an absolute eye-to-screen distance. A separate timer prompts a position change after 20 minutes of nearly unchanged visible upper-body pose. Normal movement resets it. [OSHA describes head, shoulder, arm, viewing position, and prolonged static posture as workstation considerations](https://www.osha.gov/etools/computer-workstations).

Keep your face visible to track eye openness. The app measures the left and right eye ratios, estimates an open-eye reference from recent frames, and counts brief closures as blinks. A rolling blink count appears immediately; an estimated blink rate appears after five seconds. It also shows continuous closure, the fraction of recent time with eyes closed, and time since the last blink. Low blink rate or a long period without a blink prompts a **blink and look away** warning. Long closure or frequent closure prompts a **rest if tired** warning. These are visual cues, not diagnoses of eye strain, fatigue, or drowsiness. Glasses, lighting, face angle, and face size can affect measurements. Keep at least one eye clearly visible; a front-facing view is most reliable. The [American Academy of Ophthalmology recommends regular blinking and looking away from screens](https://www.aao.org/eye-health/diseases/computer-usage).

- Press **R** to recalibrate after moving your chair or camera.
- Press **V** to cycle camera view mode.
- Press **Q** or **Esc** to quit. These keys work while either OpenCV window is focused.
- For a side view, run `python main.py --view side` for torso lean and forward-head checks.
- For a front view, run `python main.py --view front` for sideways torso lean and shoulder tilt.
- The default `--view auto` estimates the view from shoulder spacing. If the view switches during use, choose it explicitly and recalibrate.
- Use `--camera 1` (or another index) if camera 0 is not the intended webcam.
- `--alert-seconds 5` sets the continuous-poor-posture warning delay.
- `--sound` enables a single Windows system beep when a posture or eye warning begins. Other platforms remain visual-only.

## Debug terminal dashboard

Run `python main.py --tui` from an interactive terminal if you also want text measurements. The two app windows still open. The terminal shows posture and eye measurements, pose landmark visibility, FPS, calibration, and alert timing. Resize the terminal to at least 80 columns by 31 rows.

Press **V** to cycle auto/front/side camera mode, **R** to recalibrate, and **Q** to quit. After changing camera position or view, recalibrate. Front-specific measurements are blank in side mode; forward-head position is blank in front mode. The dashboard is read-only; warning thresholds are defined in the code.

To verify the dashboard and warning sequence without a webcam, run `python main.py --tui --demo`. It repeats synthetic upright, poor, corrected, missing-landmark, and prolonged eye closure phases. The source label clearly reads `DEMO (synthetic)`; this mode checks the UI and timing, not MediaPipe or camera accuracy.

The score is a relative visual deviation from your calibration, **not** a health score. Thresholds are defined in `Thresholds` in `posture_detector.py`. Camera placement, loose clothing, occlusion, and movement affect landmark quality. Front-specific cues need both sides of the face and shoulders; a side camera is better for forward-head position. Shoulder and elbow cues are only available when those joints are visible. The nearly still timer measures visible movement; it cannot determine whether you have been continuously using a screen. A single webcam cannot provide a medical posture assessment.

## Implementation

`main.py` handles the webcam, MediaPipe inference, calibration, camera preview, and debug window. It requests a 960 × 720 camera image for eye landmarks and uses a smaller image for posture inference. `posture_detector.py` extracts torso, shoulder, arm, head, and relative face-size geometry. `activity_monitor.py` times nearly unchanged poses. `eye_detector.py` uses Face Mesh eye landmarks to estimate openness, count blinks, and measure closure patterns. `alerts.py` times consecutive poor posture using a monotonic clock. All processing stays on the computer; dependencies install from PyPI, and no runtime web service is used.

Run the geometry and timing checks with:

```bash
python -m unittest discover -s tests
```
