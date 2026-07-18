"""Capture the current Houdini viewport and save a HIP snapshot beside it.

Intended for a Houdini shelf tool. Running this module executes the capture
immediately; it never opens the Flipbook or Save dialogs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

import hou


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

# Append progress and full errors to flipbook_and_save_debug.log beside the HIP.
DEBUG_LOGGING = True


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


def _scene_viewer() -> hou.SceneViewer:
    """Return the scene viewer containing the currently focused viewport."""
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


def _encode_mp4(image_pattern, mp4_path, start_frame):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg was not found in Houdini's system PATH.")

    ffmpeg_pattern = str(image_pattern).replace("$F4", "%04d")
    fps = "{:.8g}".format(float(hou.fps()))
    command = [
        ffmpeg,
        "-y",
        "-framerate",
        fps,
        "-start_number",
        str(int(start_frame)),
        "-i",
        ffmpeg_pattern,
        "-c:v",
        "libx264",
        "-preset",
        str(MP4_PRESET),
        "-crf",
        str(int(MP4_CRF)),
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(mp4_path),
    ]

    _debug("Encoding MP4 at {} fps: {}".format(fps, mp4_path))
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creation_flags,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg failed with exit code {}:\n{}".format(
                result.returncode, result.stdout
            )
        )

    if DEBUG_LOGGING and result.stdout:
        with _log_path().open("a", encoding="utf-8") as stream:
            stream.write(result.stdout + "\n")
    _debug("MP4 encoding completed")


def run() -> tuple[str, str]:
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

    viewer = _scene_viewer()
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


def execute():
    """Shelf-tool entry point that records failures without opening a dialog."""
    try:
        return run()
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


# Houdini shelf tools do not reliably execute with __name__ == "__main__".
# Call the entry point directly so this entire file can be pasted or loaded into
# a shelf tool's Python Script tab without a separate loader.
execute()
