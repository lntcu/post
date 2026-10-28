# MVP Brief: AI Posture Monitor (Python)

## Overview
Build a lightweight Python desktop application that uses a webcam and computer vision to monitor a user's sitting posture in real time. When poor posture (e.g., slouching, leaning forward, or excessive sideways tilting) is detected for a sustained period, the application displays a warning to encourage correction.

**Key requirement:** No custom model training, datasets, or fine-tuning. Use existing pretrained pose estimation models and rule-based posture detection.

## Tech Stack
- **Python 3.10+** — Core application
- **OpenCV** — Webcam capture, video processing, and visual overlays
- **MediaPipe Pose** — Pretrained body landmark detection
- **NumPy** — Angle and coordinate calculations
- **Tkinter or OpenCV UI** — Visual posture warnings
- **Optional:** `winsound` or `pygame` for audible alerts

## Core Features

1. **Real-Time Webcam Monitoring**
   - Capture webcam frames using OpenCV.
   - Detect body landmarks using pretrained MediaPipe Pose.
   - Track relevant landmarks, including shoulders, ears, nose, and hips.

2. **Posture Detection**
   - Estimate posture through geometric calculations using detected landmarks.
   - Detect potential slouching, forward-head posture, and sideways leaning.
   - Use configurable thresholds rather than a trained classifier.
   - Support a short initial calibration where the user sits upright for 5 seconds to establish their personal baseline.

3. **Warning System**
   - Display a green indicator when posture is acceptable.
   - Display a red warning when poor posture persists for 5 consecutive seconds.
   - Optionally play an alert sound.
   - Clear the warning once the user corrects their posture.

4. **Live Visualization**
   - Show the webcam feed with pose landmarks overlaid.
   - Display posture status: `Good`, `Poor`, or `Not Detected`.
   - Show a simple posture score or deviation from baseline.

## Detection Logic

Use MediaPipe's pretrained pose landmarks and simple rule-based heuristics:

| Condition | Detection approach |
|---|---|
| Slouching | Changes in shoulder–hip alignment compared with calibration |
| Forward-head posture | Head position relative to shoulders, when the camera angle supports it |
| Sideways leaning | Horizontal displacement or tilt of shoulder and hip landmarks |
| Poor landmark visibility | Mark posture as `Not Detected` rather than triggering an alert |

**Important:** A side-facing webcam generally provides better forward-slouch detection than a front-facing webcam. With a front-facing webcam, prioritize shoulder asymmetry and sideways leaning. A single webcam cannot reliably measure all forms of slouching.

## Application Flow

1. Launch the Python application and initialize the webcam.
2. Detect the user's upper-body landmarks.
3. Ask the user to sit upright for 5 seconds to calibrate.
4. Continuously compare detected posture against the baseline.
5. If poor posture persists for 5 seconds, trigger a visual or audio warning.
6. Remove the warning when posture improves.

## MVP Constraints

- No custom-trained AI models or model fine-tuning.
- No external API calls or cloud processing.
- All webcam processing happens locally.
- No storage or recording of webcam footage.
- Support standard laptop webcams.
- Target responsive performance (approximately 15–30 FPS on typical hardware).
- Use only open-source Python libraries and publicly available pretrained models.

## Deliverables

- `main.py` — Webcam processing and application loop
- `posture_detector.py` — Pose landmark analysis and posture classification
- `alerts.py` — Warning logic and notifications
- `requirements.txt` — Dependencies
- `README.md` — Installation, calibration, and usage instructions

## Success Criteria

The MVP should run locally with a standard webcam, identify visible deviations from a calibrated sitting posture, and trigger a warning when those deviations persist for at least 5 seconds, without requiring any custom machine learning training.

**Priority:** Reliable detection of a few simple posture deviations over attempting comprehensive medical-grade posture analysis.
