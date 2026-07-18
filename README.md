# Houdini Flipbook and Save

`flipbook_and_save.py` captures the current Scene View exactly as displayed,
encodes the JPEG sequence to H.264 MP4 with FFmpeg, removes the temporary JPEGs,
and saves a snapshot of the current HIP scene in a `flipbook` folder beside the
scene.
It runs immediately and opens no dialogs.

## Install as a shelf tool

1. In Houdini, create a new shelf tool.
2. Set the tool's **Script Language** to **Python**.
3. Paste or load the complete contents of `flipbook_and_save.py` into the
   **Script** tab. Copy from the local `.py` file rather than rendered chat text.
4. Click the shelf tool while the mouse is over the Scene View you want to
   capture.

The script calls its entry point directly at the bottom because Houdini shelf
tools do not reliably use `__name__ == "__main__"`.

The HIP file must have been saved at least once. Output is created beside it:

```text
shot_010.hip
flipbook/
    shot_010_flipbook_20260718_103000_123456.mp4
    shot_010_flipbook_20260718_103000_123456_snapshot.hip
```

During capture, `$F4` JPEG frames are written into a unique local folder under
Houdini's `$HOUDINI_TEMP_DIR` (normally in Windows `%TEMP%`). Python's system
temporary directory is used as a fallback. This prevents intermediate frames
from being uploaded by synced or cloud-backed project storage such as
LucidLink. The temporary folder is removed after FFmpeg succeeds and retained
if encoding fails.

## Configuration

Edit the constants at the top of the script:

- `RESOLUTION`: `(width, height)`, or `None` for current viewport size.
- `FRAME_RANGE`: `"playback"`, `"frame"`, or `(start, end)`.
- `FRAME_INCREMENT`: capture interval in frames.
- `IMAGE_FORMAT`: `"png"`, `"jpg"`, `"jpeg"`, or `"exr"`.
- `ANTIALIAS_SAMPLES`: `1`, `2`, `4`, or `8`; `None` uses the viewport setting.
- `OUTPUT_ZOOM_PERCENT`: output scaling from 1 to 100 percent.
- `OPEN_IN_MPLAY`: whether to also send frames to MPlay.
- `OUTPUT_LABEL`: label used in the output folder and filenames.
- `CREATE_MP4`: encode an H.264 movie using `ffmpeg` from the system `PATH`.
- `DELETE_IMAGES_AFTER_MP4`: remove source images after a successful encode.
- `MP4_CRF`: H.264 quality; lower is better quality and larger (`18` default).
- `MP4_PRESET`: encoding speed/compression tradeoff (`"medium"` default).
- `DEBUG_LOGGING`: writes progress and errors to a persistent text log.

JPEG is the default intermediate format for faster viewport capture. Houdini
controls JPEG compression through its image-output preferences. FFmpeg uses the
current Houdini scene FPS and produces a broadly compatible H.264/yuv420p MP4.
Temporary frames are retained if FFmpeg fails.

## Notes

- The current viewport, camera/view, shading, guides, visualizers, lighting,
  color correction, and other visible viewport state are used by the flipbook.
- Flipbook settings are copied before modification, so the interactive Flipbook
  dialog settings are not changed.
- The HIP snapshot includes current unsaved changes. Houdini remains pointed at
  the original HIP filename after the snapshot is written.

## Debugging

Progress appears in Houdini's status bar. A persistent log named
`flipbook_and_save_debug.log` is appended beside the current HIP file. If the
HIP has never been saved, the log is written to the operating system's temporary
folder instead. The log includes the full Python traceback for any failure.

For the quickest test, temporarily use:

```python
FRAME_RANGE = "frame"
OPEN_IN_MPLAY = True
```

This captures one frame and makes a successful capture immediately visible in
MPlay. Also check whether a timestamped output folder was created beside the
HIP: if it exists, the log will identify the next operation that failed.
