"""Capture the current Houdini viewport and save a HIP snapshot beside it.

The module can be loaded by the packaged Houdini menu command or run directly.
It never opens Houdini's Flipbook or Save dialogs.
"""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
import traceback
import re
from datetime import datetime
from pathlib import Path

import hou
from PySide6 import QtCore, QtGui, QtWidgets


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# None uses the current viewport's pixel size. Example: (1920, 1080).
RESOLUTION = (1920, 1080)

# "playback" uses Houdini's timeline playback range, "frame" captures only the
# current frame, or supply an explicit (start, end) tuple such as (1001, 1100).
FRAME_RANGE = "playback"

# Capture every Nth frame.
FRAME_INCREMENT = 1

# png is lossless and recommended. jpg produces smaller, lossy files; JPEG
# compression quality is controlled by Houdini's image-output preferences.
IMAGE_FORMAT = "jpg"

# Flipbook antialiasing samples: 1 (off), 2 (fast), 4 (good), or 8 (high).
# None preserves the flipbook's current "use viewport setting" behavior.
ANTIALIAS_SAMPLES = 8

# 100 writes at full size; 50 writes at half size.
OUTPUT_ZOOM_PERCENT = 100

# Also send the captured frames to MPlay.
OPEN_IN_MPLAY = False

# Optional label added to the timestamped output folder and filenames.
OUTPUT_LABEL = "flipbook"

# Encode the sequence with ffmpeg from the system PATH, then remove the source
# images only after a successful encode.
CREATE_MP4 = True
DELETE_IMAGES_AFTER_MP4 = True

# H.264 quality: lower CRF means higher quality/larger files. 18 is visually
# lossless for many viewport captures; 20-23 produces smaller review movies.
MP4_CRF = 18
MP4_PRESET = "medium"

# Optional backup executable. The ffmpeg found in PATH is always tried first.
# Example: r"C:\Tools\ffmpeg\bin\ffmpeg.exe"
FFMPEG_FALLBACK_PATH = ""

# Append progress and full errors to flipbook_and_save_debug.log beside the HIP.
DEBUG_LOGGING = True


def _preferences_path() -> Path:
    pref_dir = hou.getenv("HOUDINI_USER_PREF_DIR")
    root = Path(pref_dir) if pref_dir else Path.home() / "houdini_prefs"
    return root / "flipbook_and_save.json"


def _preference_values() -> dict:
    return {
        "resolution": list(RESOLUTION) if RESOLUTION is not None else None,
        "frame_range": list(FRAME_RANGE) if isinstance(FRAME_RANGE, tuple) else FRAME_RANGE,
        "frame_increment": FRAME_INCREMENT,
        "image_format": IMAGE_FORMAT,
        "antialias_samples": ANTIALIAS_SAMPLES,
        "output_zoom_percent": OUTPUT_ZOOM_PERCENT,
        "open_in_mplay": OPEN_IN_MPLAY,
        "delete_images_after_mp4": DELETE_IMAGES_AFTER_MP4,
        "mp4_crf": MP4_CRF,
        "mp4_preset": MP4_PRESET,
        "ffmpeg_fallback_path": FFMPEG_FALLBACK_PATH,
    }


def _apply_preferences(values: dict) -> None:
    global RESOLUTION, FRAME_RANGE, FRAME_INCREMENT, IMAGE_FORMAT
    global ANTIALIAS_SAMPLES, OUTPUT_ZOOM_PERCENT, OPEN_IN_MPLAY
    global DELETE_IMAGES_AFTER_MP4, MP4_CRF, MP4_PRESET, FFMPEG_FALLBACK_PATH

    resolution = values.get("resolution", RESOLUTION)
    RESOLUTION = tuple(resolution) if resolution is not None else None
    frame_range = values.get("frame_range", FRAME_RANGE)
    FRAME_RANGE = tuple(frame_range) if isinstance(frame_range, list) else frame_range
    FRAME_INCREMENT = int(values.get("frame_increment", FRAME_INCREMENT))
    IMAGE_FORMAT = str(values.get("image_format", IMAGE_FORMAT))
    ANTIALIAS_SAMPLES = values.get("antialias_samples", ANTIALIAS_SAMPLES)
    OUTPUT_ZOOM_PERCENT = int(values.get("output_zoom_percent", OUTPUT_ZOOM_PERCENT))
    OPEN_IN_MPLAY = bool(values.get("open_in_mplay", OPEN_IN_MPLAY))
    DELETE_IMAGES_AFTER_MP4 = bool(
        values.get("delete_images_after_mp4", DELETE_IMAGES_AFTER_MP4)
    )
    MP4_CRF = int(values.get("mp4_crf", MP4_CRF))
    MP4_PRESET = str(values.get("mp4_preset", MP4_PRESET))
    FFMPEG_FALLBACK_PATH = str(
        values.get("ffmpeg_fallback_path", FFMPEG_FALLBACK_PATH)
    ).strip()


def _load_preferences() -> None:
    path = _preferences_path()
    if not path.is_file():
        return
    try:
        with path.open("r", encoding="utf-8") as stream:
            _apply_preferences(json.load(stream))
    except Exception as error:
        _debug("Could not load preferences: {}".format(error))


def _save_preferences(values: dict) -> None:
    path = _preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(values, stream, indent=2, sort_keys=True)
        stream.write("\n")
    _apply_preferences(values)
    _debug("Saved preferences: {}".format(path))


def _log_path() -> Path:
    """Return a writable log location even when the HIP has not been saved."""
    try:
        hip_parent = Path(hou.hipFile.path()).parent
        if hip_parent.is_dir():
            return hip_parent / "flipbook_and_save_debug.log"
    except Exception:
        pass
    return Path(tempfile.gettempdir()) / "flipbook_and_save_debug.log"


def _debug(message: str, severity=None) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[{}] {}".format(timestamp, message)
    print(line)
    if DEBUG_LOGGING:
        with _log_path().open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    try:
        hou.ui.setStatusMessage(
            message,
            severity=severity or hou.severityType.Message,
        )
    except Exception:
        pass


def _scene_viewer(preferred=None) -> hou.SceneViewer:
    """Return the scene viewer containing the currently focused viewport."""
    if preferred is not None:
        return preferred

    pane = hou.ui.paneTabUnderCursor()
    if pane is not None and pane.type() == hou.paneTabType.SceneViewer:
        return pane

    pane = hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)
    if pane is None:
        raise RuntimeError("No Scene Viewer is available for flipbooking.")
    return pane


def _frame_range() -> tuple[float, float]:
    if FRAME_RANGE == "playback":
        return tuple(hou.playbar.playbackRange())
    if FRAME_RANGE == "frame":
        frame = hou.frame()
        return (frame, frame)
    if isinstance(FRAME_RANGE, (tuple, list)) and len(FRAME_RANGE) == 2:
        return (float(FRAME_RANGE[0]), float(FRAME_RANGE[1]))
    raise ValueError(
        'FRAME_RANGE must be "playback", "frame", or a (start, end) pair.'
    )


def _validate_config() -> None:
    if RESOLUTION is not None:
        if len(RESOLUTION) != 2 or min(RESOLUTION) < 2:
            raise ValueError("RESOLUTION must be None or a (width, height) pair > 1.")
    if int(FRAME_INCREMENT) < 1:
        raise ValueError("FRAME_INCREMENT must be at least 1.")
    if not 1 <= int(OUTPUT_ZOOM_PERCENT) <= 100:
        raise ValueError("OUTPUT_ZOOM_PERCENT must be between 1 and 100.")
    if IMAGE_FORMAT.lower().lstrip(".") not in {"png", "jpg", "jpeg", "exr"}:
        raise ValueError("IMAGE_FORMAT must be png, jpg, jpeg, or exr.")
    if ANTIALIAS_SAMPLES not in {None, 1, 2, 4, 8}:
        raise ValueError("ANTIALIAS_SAMPLES must be None, 1, 2, 4, or 8.")
    if CREATE_MP4 and int(FRAME_INCREMENT) != 1:
        raise ValueError("CREATE_MP4 currently requires FRAME_INCREMENT = 1.")
    if not 0 <= int(MP4_CRF) <= 51:
        raise ValueError("MP4_CRF must be between 0 and 51.")


def _snapshot_path(output_dir: Path, stem: str, extension: str) -> Path:
    return output_dir / "{}_snapshot{}".format(stem, extension)


def _temporary_image_dir(stem: str) -> Path:
    """Create a unique local folder, preferring Houdini's temp location."""
    houdini_temp = hou.getenv("HOUDINI_TEMP_DIR")
    temp_root = Path(houdini_temp) if houdini_temp else Path(tempfile.gettempdir())
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        temp_path = tempfile.mkdtemp(prefix=stem + "_", dir=str(temp_root))
    except OSError:
        temp_path = tempfile.mkdtemp(prefix=stem + "_")
    return Path(temp_path)


def _validate_flipbook_frames(temp_dir, stem, image_ext, capture_range):
    """Verify the complete sequence produced by Houdini's blocking flipbook."""
    start, end = capture_range
    start_frame = int(round(float(start)))
    end_frame = int(round(float(end)))
    if abs(float(start) - start_frame) > 1e-6 or abs(float(end) - end_frame) > 1e-6:
        raise RuntimeError("MP4 encoding requires whole-number start and end frames.")
    expected_frames = list(range(start_frame, end_frame + 1, int(FRAME_INCREMENT)))
    if not expected_frames:
        raise RuntimeError("The flipbook frame range contains no frames.")

    pattern = "{}.*.{}".format(stem, image_ext)
    filename_pattern = re.compile(
        r"^{}\.(-?\d+)\.{}$".format(re.escape(stem), re.escape(image_ext)),
        re.IGNORECASE,
    )
    captured = {}
    for path in temp_dir.glob(pattern):
        match = filename_pattern.match(path.name)
        if match:
            captured[int(match.group(1))] = path

    missing = [frame for frame in expected_frames if frame not in captured]
    if missing:
        raise RuntimeError(
            "Houdini's flipbook omitted {} of {} frames: {}. "
            "Temporary files were retained in {}.".format(
                len(missing), len(expected_frames),
                ", ".join(str(frame) for frame in missing), temp_dir,
            )
        )
    if not captured:
        raise RuntimeError("No numbered flipbook frames were found in {}.".format(temp_dir))

    _debug(
        "Flipbook sequence complete: {} / {} frames".format(
            len(captured), len(expected_frames)
        )
    )


def _encode_mp4(image_pattern, mp4_path, start_frame):
    candidates = []
    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        candidates.append(("system PATH", path_ffmpeg))

    fallback = FFMPEG_FALLBACK_PATH.strip().strip('"')
    if fallback and Path(fallback).is_file():
        fallback_resolved = str(Path(fallback).resolve())
        if not any(
            os.path.normcase(executable) == os.path.normcase(fallback_resolved)
            for _, executable in candidates
        ):
            candidates.append(("configured fallback", fallback_resolved))

    if not candidates:
        details = "ffmpeg was not found in Houdini's system PATH."
        if fallback:
            details += " Configured fallback does not exist: {}".format(fallback)
        else:
            details += " No fallback executable is configured."
        raise RuntimeError(details)

    ffmpeg_pattern = str(image_pattern).replace("$F4", "%04d")
    fps = "{:.8g}".format(float(hou.fps()))
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    failures = []
    result = None
    used_source = None
    for source, executable in candidates:
        command = [
            executable, "-y", "-framerate", fps,
            "-start_number", str(int(start_frame)),
            "-i", ffmpeg_pattern,
            "-c:v", "libx264", "-preset", str(MP4_PRESET),
            "-crf", str(int(MP4_CRF)),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(mp4_path),
        ]
        _debug("Trying ffmpeg from {}: {}".format(source, executable))
        try:
            attempt = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
            )
        except OSError as error:
            failures.append("{} ({}) could not start: {}".format(source, executable, error))
            continue
        if attempt.returncode == 0:
            result = attempt
            used_source = source
            break
        failures.append(
            "{} ({}) exited {}:\n{}".format(
                source, executable, attempt.returncode, attempt.stdout
            )
        )

    if result is None:
        raise RuntimeError("All ffmpeg attempts failed:\n\n{}".format("\n\n".join(failures)))

    if DEBUG_LOGGING and result.stdout:
        with _log_path().open("a", encoding="utf-8") as stream:
            stream.write(result.stdout + "\n")
    _debug("MP4 encoding completed using ffmpeg from {}".format(used_source))


def run(scene_viewer=None) -> tuple[str, str]:
    """Run the flipbook and return ``(mp4_or_images, hip_snapshot)``."""
    _debug("Flipbook and Save started")
    _validate_config()
    _debug("Configuration validated")

    if hou.hipFile.isNewFile():
        raise RuntimeError(
            "Save the current HIP file once before running Flipbook and Save."
        )

    original_hip = Path(hou.hipFile.path())
    if not original_hip.parent.is_dir():
        raise RuntimeError("The current HIP file does not have a valid directory.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    label = OUTPUT_LABEL.strip().replace(" ", "_") or "flipbook"
    stem = "{}_{}_{}".format(original_hip.stem, label, timestamp)
    output_dir = original_hip.parent / "flipbook"
    output_dir.mkdir(parents=False, exist_ok=True)
    temp_image_dir = _temporary_image_dir(stem)
    _debug("Output folder: {}".format(output_dir))
    _debug("Temporary image folder: {}".format(temp_image_dir))

    image_ext = IMAGE_FORMAT.lower().lstrip(".")
    image_pattern = temp_image_dir / "{}.$F4.{}".format(stem, image_ext)
    hip_snapshot = _snapshot_path(output_dir, stem, original_hip.suffix)
    mp4_path = output_dir / "{}.mp4".format(stem)

    viewer = _scene_viewer(scene_viewer)
    viewport = viewer.curViewport()
    _debug("Using Scene Viewer: {}; viewport: {}".format(viewer.name(), viewport.name()))
    settings = viewer.flipbookSettings().stash()
    capture_range = _frame_range()
    settings.frameRange(capture_range)
    settings.frameIncrement(int(FRAME_INCREMENT))
    settings.output(str(image_pattern).replace(os.sep, "/"))
    settings.outputToMPlay(bool(OPEN_IN_MPLAY))
    settings.outputZoom(int(OUTPUT_ZOOM_PERCENT))
    settings.useSheetSize(False)
    settings.beautyPassOnly(False)
    settings.renderAllViewports(False)
    _debug("Capturing selected viewport only")
    settings.scopeChannelKeyframesOnly(False)
    settings.appendFramesToCurrent(False)
    settings.leaveFrameAtEnd(False)

    if RESOLUTION is None:
        settings.useResolution(False)
    else:
        settings.useResolution(True)
        settings.resolution(tuple(int(value) for value in RESOLUTION))

    if ANTIALIAS_SAMPLES is not None:
        antialias_modes = {
            1: hou.flipbookAntialias.Off,
            2: hou.flipbookAntialias.Fast,
            4: hou.flipbookAntialias.Good,
            8: hou.flipbookAntialias.HighQuality,
        }
        settings.antialias(antialias_modes[int(ANTIALIAS_SAMPLES)])

    # open_dialog=False is explicit: this tool must execute without UI prompts.
    _debug("Starting flipbook: {}".format(image_pattern))
    viewer.flipbook(viewport, settings, open_dialog=False)
    _debug("Flipbook call completed")
    _validate_flipbook_frames(
        temp_image_dir,
        stem,
        image_ext,
        capture_range,
    )

    # Saving to another path behaves like Save As, so restore Houdini's in-memory
    # scene name immediately afterward. The snapshot includes current unsaved work.
    original_name = hou.hipFile.name()
    try:
        _debug("Saving HIP snapshot: {}".format(hip_snapshot))
        hou.hipFile.save(str(hip_snapshot), save_to_recent_files=False)
    finally:
        hou.hipFile.setName(original_name)

    final_media = image_pattern
    if CREATE_MP4:
        _encode_mp4(image_pattern, mp4_path, capture_range[0])
        final_media = mp4_path
        if DELETE_IMAGES_AFTER_MP4:
            images = list(temp_image_dir.glob("{}.*.{}".format(stem, image_ext)))
            for image in images:
                image.unlink()
            _debug("Removed {} temporary {} images".format(len(images), image_ext))
            try:
                temp_image_dir.rmdir()
                _debug("Removed temporary image folder")
            except OSError as error:
                _debug("Could not remove temporary image folder: {}".format(error))

    _debug("Complete. Media: {}; HIP snapshot: {}".format(final_media, hip_snapshot))
    return (str(final_media), str(hip_snapshot))


def execute(scene_viewer=None):
    """Shelf-tool entry point that records failures without opening a dialog."""
    try:
        return run(scene_viewer)
    except Exception as error:
        details = traceback.format_exc()
        try:
            _debug(
                "FAILED: {}\n{}".format(error, details),
                severity=hou.severityType.Error,
            )
        except Exception:
            print(details)
        return None


class ConfigDialog(QtWidgets.QDialog):
    """Compact persistent settings editor for the shelf tool."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flipbook and Save Settings")
        self.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(430)

        form = QtWidgets.QFormLayout()

        self.use_resolution = QtWidgets.QCheckBox("Use custom resolution")
        self.use_resolution.setChecked(RESOLUTION is not None)
        resolution_row = QtWidgets.QHBoxLayout()
        self.width = QtWidgets.QSpinBox()
        self.height = QtWidgets.QSpinBox()
        for widget in (self.width, self.height):
            widget.setRange(2, 16384)
        width, height = RESOLUTION or (1920, 1080)
        self.width.setValue(int(width))
        self.height.setValue(int(height))
        resolution_row.addWidget(self.width)
        resolution_row.addWidget(QtWidgets.QLabel("×"))
        resolution_row.addWidget(self.height)
        form.addRow(self.use_resolution)
        form.addRow("Resolution", resolution_row)
        self.use_resolution.toggled.connect(self.width.setEnabled)
        self.use_resolution.toggled.connect(self.height.setEnabled)
        self.width.setEnabled(self.use_resolution.isChecked())
        self.height.setEnabled(self.use_resolution.isChecked())

        self.range_mode = QtWidgets.QComboBox()
        self.range_mode.addItem("Playback range", "playback")
        self.range_mode.addItem("Current frame", "frame")
        self.range_mode.addItem("Custom range", "custom")
        custom_range = isinstance(FRAME_RANGE, tuple)
        mode = "custom" if custom_range else FRAME_RANGE
        index = self.range_mode.findData(mode)
        self.range_mode.setCurrentIndex(max(index, 0))
        form.addRow("Frames", self.range_mode)

        range_row = QtWidgets.QHBoxLayout()
        self.start_frame = QtWidgets.QDoubleSpinBox()
        self.end_frame = QtWidgets.QDoubleSpinBox()
        for widget in (self.start_frame, self.end_frame):
            widget.setRange(-1000000, 1000000)
            widget.setDecimals(3)
        start, end = FRAME_RANGE if custom_range else hou.playbar.playbackRange()
        self.start_frame.setValue(float(start))
        self.end_frame.setValue(float(end))
        range_row.addWidget(self.start_frame)
        range_row.addWidget(QtWidgets.QLabel("to"))
        range_row.addWidget(self.end_frame)
        form.addRow("Custom range", range_row)
        self.range_mode.currentIndexChanged.connect(self._update_range_enabled)
        self._update_range_enabled()

        self.antialias = QtWidgets.QComboBox()
        for label, value in (
            ("Use viewport setting", None),
            ("Off", 1),
            ("Fast (2 samples)", 2),
            ("Good (4 samples)", 4),
            ("High (8 samples)", 8),
        ):
            self.antialias.addItem(label, value)
        aa_index = self.antialias.findData(ANTIALIAS_SAMPLES)
        self.antialias.setCurrentIndex(max(aa_index, 0))
        form.addRow("Antialiasing", self.antialias)

        self.image_format = QtWidgets.QComboBox()
        self.image_format.addItem("JPEG (faster, smaller)", "jpg")
        self.image_format.addItem("PNG (lossless)", "png")
        format_value = IMAGE_FORMAT.lower().lstrip(".")
        if format_value == "jpeg":
            format_value = "jpg"
        format_index = self.image_format.findData(format_value)
        self.image_format.setCurrentIndex(max(format_index, 0))
        form.addRow("Intermediate images", self.image_format)

        self.zoom = QtWidgets.QSpinBox()
        self.zoom.setRange(1, 100)
        self.zoom.setSuffix(" %")
        self.zoom.setValue(int(OUTPUT_ZOOM_PERCENT))
        form.addRow("Output scale", self.zoom)

        self.crf = QtWidgets.QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(int(MP4_CRF))
        self.crf.setToolTip("Lower values produce higher quality and larger files.")
        form.addRow("MP4 quality (CRF)", self.crf)

        self.preset = QtWidgets.QComboBox()
        presets = [
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow",
        ]
        self.preset.addItems(presets)
        preset_index = self.preset.findText(MP4_PRESET)
        self.preset.setCurrentIndex(max(preset_index, presets.index("medium")))
        form.addRow("FFmpeg preset", self.preset)

        ffmpeg_row = QtWidgets.QWidget()
        ffmpeg_layout = QtWidgets.QHBoxLayout(ffmpeg_row)
        ffmpeg_layout.setContentsMargins(0, 0, 0, 0)
        self.ffmpeg_fallback = QtWidgets.QLineEdit(FFMPEG_FALLBACK_PATH)
        self.ffmpeg_fallback.setPlaceholderText("Optional path to ffmpeg.exe")
        browse_button = QtWidgets.QPushButton("Browse…")
        browse_button.clicked.connect(self._browse_ffmpeg)
        ffmpeg_layout.addWidget(self.ffmpeg_fallback, 1)
        ffmpeg_layout.addWidget(browse_button)
        form.addRow("FFmpeg fallback", ffmpeg_row)

        self.open_mplay = QtWidgets.QCheckBox("Also send frames to MPlay")
        self.open_mplay.setChecked(bool(OPEN_IN_MPLAY))
        form.addRow(self.open_mplay)

        self.delete_images = QtWidgets.QCheckBox(
            "Delete temporary JPEGs after successful encoding"
        )
        self.delete_images.setChecked(bool(DELETE_IMAGES_AFTER_MP4))
        form.addRow(self.delete_images)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _update_range_enabled(self):
        enabled = self.range_mode.currentData() == "custom"
        self.start_frame.setEnabled(enabled)
        self.end_frame.setEnabled(enabled)

    def _browse_ffmpeg(self):
        current = self.ffmpeg_fallback.text().strip()
        start_dir = str(Path(current).parent) if current else ""
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Choose FFmpeg executable",
            start_dir,
            "FFmpeg executable (ffmpeg.exe);;Executable files (*.exe);;All files (*)",
        )
        if filename:
            self.ffmpeg_fallback.setText(filename)

    def _save(self):
        mode = self.range_mode.currentData()
        frame_range = (
            [self.start_frame.value(), self.end_frame.value()]
            if mode == "custom"
            else mode
        )
        values = _preference_values()
        values.update(
            {
                "resolution": (
                    [self.width.value(), self.height.value()]
                    if self.use_resolution.isChecked()
                    else None
                ),
                "frame_range": frame_range,
                "antialias_samples": self.antialias.currentData(),
                "image_format": self.image_format.currentData(),
                "output_zoom_percent": self.zoom.value(),
                "open_in_mplay": self.open_mplay.isChecked(),
                "delete_images_after_mp4": self.delete_images.isChecked(),
                "mp4_crf": self.crf.value(),
                "mp4_preset": self.preset.currentText(),
                "ffmpeg_fallback_path": self.ffmpeg_fallback.text().strip(),
            }
        )
        try:
            _save_preferences(values)
        except Exception as error:
            _debug(
                "Could not save preferences: {}".format(error),
                severity=hou.severityType.Error,
            )
            return
        self.accept()


def show_configurator():
    dialog = ConfigDialog(hou.qt.mainWindow())
    dialog.setWindowFlag(QtCore.Qt.Window, True)
    dialog.exec()


def show_tool_menu():
    """Show the shelf tool's action menu at the mouse cursor."""
    menu = hou.qt.Menu()
    viewers = [
        pane_tab
        for pane_tab in hou.ui.currentPaneTabs()
        if pane_tab.type() == hou.paneTabType.SceneViewer
    ]
    viewers.sort(
        key=lambda viewer: (
            viewer.qtScreenGeometry().center().y(),
            viewer.qtScreenGeometry().center().x(),
        )
    )

    viewer_actions = {}
    if len(viewers) <= 1:
        run_action = menu.addAction("Flipbook and Save")
        viewer_actions[run_action] = viewers[0] if viewers else None
    else:
        run_menu = menu.addMenu("Flipbook and Save")
        for index, viewer in enumerate(viewers):
            viewport = viewer.curViewport()
            label = "Scene Viewer {} — {} ({})".format(
                index + 1, viewer.name(), viewport.name()
            )
            viewer_actions[run_menu.addAction(label)] = viewer

    configure_action = menu.addAction("Configure…")
    selected = menu.exec(QtGui.QCursor.pos())
    if selected in viewer_actions:
        execute(viewer_actions[selected])
    elif selected == configure_action:
        show_configurator()


_load_preferences()

if __name__ == "__main__":
    show_tool_menu()
