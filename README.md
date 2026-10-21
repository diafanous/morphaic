# morphaic

## Morphaic 1.0

Morphaic 1.2.0 adds full-resolution animation exports with optional GPU acceleration, smooth map line gradients, shared hue/hex color tools, Triptych PDF exports and a full-width desktop drag bar. Run `uv run server.py` for the browser UI, or build the Windows executable with `./build-test.ps1` after `uv sync --extra desktop --group build`. The executable is `dist/morphaic-1.2.0.exe`.

The desktop app integrates minimize, maximize/restore and close into a glass bubble beside Export. Drag the full-width top bar or the app name to move the window, double-click either to maximize or restore, and drag any window edge or corner to resize. F11 toggles full screen; Escape leaves full screen.

- Clearer grayscale contrast and slightly larger text. New color grading, film grain and gradient-map controls use collapsible panels.
- Imports start neutral: no scatter, rotation, size variance or drawing pull, one opaque layer. Unchanged single-image imports are resized as one image to avoid seams on odd pixel dimensions.
- Right-click the canvas (or focus it and press Shift+F10) for reset canvas, remove attached images and quick export using the current export settings. Removing sources and resets can be undone.
- The top-bar reset restores neutral edits, original source sizes/pages and default export settings while retaining attached images. Its confirmation includes a persistent "don't show me this again" preference. Canvas reset retains the chosen export format and resolution.
- Color grading adds exposure, temperature, tint and saturation. Gradient maps support up to 16 editable color/brightness stops, presets, reversal and blend amount. These share the existing preview/export pipeline, including animations and collage-based reliefs.
- Film grain supports generated monochrome grain or an imported image texture. Amount starts at zero; raise it to apply. Generated grain size is measured in pixels at 300 dpi. Imported textures have an editable DPI value; their physical scale stays consistent across preview and export resolutions. Grain uses the collage seed. Custom textures repeat and are normalized around neutral gray. Very fine grain is reduced at low preview resolutions to avoid moire. TXT settings include effect values and custom texture name/reference, but do not embed the texture or source images.
- Relief spacing reaches **0.01 mm**. The old 500,000-vertex ceiling is removed. Compact mesh arrays and chunked binary STL encoding support denser meshes; the app shows one estimated file size at the bottom of export settings and checks available physical memory before exporting. Model size, format and backing affect memory requirements. The live preview remains lightweight.
- The cutting mat is a monochrome overlay within the canvas area. Freehand/point cuts, seal/lift, saved stencils, keyboard controls, sound and cut undo/redo remain available.

Validation: `uv run test_collage.py`, `uv run test_animation.py`, `uv run test_map_exports.py`, `uv run test_effects.py`, `uv run test_relief_quality.py`, and `node test_controls.js`. `test_iteration_ui.cjs`, `test_animation_ui.cjs` and `test_map_ui.cjs` use Playwright and installed Edge against an isolated local server (default `http://127.0.0.1:8872`, overridden with `MORPHAIC_TEST_URL`). Its server must use a temporary settings path and export directory because it tests persistent preferences and saves an export. The dense-mesh regression generates 508,362 vertices and 1,016,720 triangles at 0.01 mm spacing and checks the resulting binary STL.

Controller mode in settings hides the menus and canvas controls while retaining the artwork and current edits. F8 toggles this mode; Escape restores the menus. This is a canvas-only display mode, not a new controller driver or mapping system.

The installer offers an optional removal step when it detects a previous per-user Morphaic installation (including test builds). Leaving it unchecked updates in place. Portable EXEs are not registered installations and are left alone.

## Overview

Drop in images or PDFs, cut them into sections, scatter and layer the sections into a new picture, export at print resolution.

```
uv run server.py        # opens http://127.0.0.1:8765  (uv run server.py 9000 for another port)
uv run test_collage.py
```

Needs [uv](https://docs.astral.sh/uv/); the first run installs Pillow, PyMuPDF, the HEIC codec and the MP4 encoder listed in `pyproject.toml`. Python 3.10+. Everything runs locally; the server only listens on 127.0.0.1.

## Desktop apps

### Morphaic 1.0

Export settings now have **2D** and **3D** tabs. 2D retains PNG, TIF, PDF, GIF, MP4, migration map, triptych and TXT, and adds grayscale luminosity PNG/TIF. 3D creates a closed luminosity relief directly from the current collage, including its current edits. It exports ASCII/binary STL and Rhino 3DM. Width, height, relief depth, base thickness and mesh spacing use millimeters, independently of the collage's display units. STL is a unitless format: its numeric coordinates always represent millimeters. 3DM explicitly stores millimeter units. Lower mesh spacing gives finer detail; available memory is checked before export. Grayscale luminosity exports use the relief's physical width/height and output DPI, with a 16 MP limit.

**Open live 3D viewer** shows a shaded, orbitable relief. Drag the viewer title bar to move its window within the program; the focused title also supports arrow keys. Drag the model to rotate, scroll to zoom, and choose live updates or use the title-bar refresh, reset-view and back-view buttons. The preview uses at most 81 samples per axis; exports use the chosen spacing. Type the physical model size in the compact W × H row, using the selected in/cm/mm units. Width and height stay linked to canvas proportions. Add an image or PDF to the canvas before opening the viewer or exporting a relief. Relief depth, base thickness, gamma, contrast, smoothing radius and inversion remain adjustable. White pixels are highest by default. Luminosity uses Rec.709 weights on 8-bit RGB values; the grayscale output contains the same gamma/contrast/smoothing/inversion used for the relief, without the base thickness.

The **cut shape** selector starts with the existing rectangles and cell sizes. Choose ellipse, triangle, diamond, hexagon, star, heart or a custom stencil. **Mix multiple shapes** keeps shares at exactly 100%, redistributing the unlocked shares when one changes. Lock an individual shape percentage to hold it fixed; locks are included in undo/redo and TXT settings. The larger filled radial chart shows actual cut percentages across all layers. Total cuts appear beneath section size. Shape assignments stay fixed while moving, rotating, scaling or changing output resolution. Migration PDFs trace the cut shapes. Enable **end nodes by cut shape** to set separate end markers for each shape, including a miniature of that cut shape.

**Cutting mat** overlays the current artwork directly, with a moving blade, paper shavings and optional synthesized cutting sounds. The normal workspace has a faint drafting grid. Its top bar holds cutting modes, undo/redo arrows, a sound icon and the settings icon for naming and saving stencils, instructions and status. Drag freehand or click corners in point-to-point mode; return to the start ring or choose **seal & lift**, then **save** to apply the lifted outline to collage sections. Ctrl+Z undoes a cut and Ctrl+Shift+Z redoes it while the mat is open; starting a new sheet and lifting a shape can also be undone. Stencils are fitted to each section's bounding rectangle. Crossing cuts and tiny slivers ask for a cleaner outline before lifting. Cut settings, custom stencil points, per-shape markers and relief settings support the existing undo/redo workflow.

**Saved stencils:** open the cutting mat's settings icon to name and save a lifted stencil, or tick **save stencil for future sessions** before using it. Click **saved stencils**, beside **cutting mat**, to open the menu and reload a named outline in future sessions. Edit its name and save again to rename the same library entry. Settings live in the Morphaic application-data folder, with existing Collage settings and stencils preserved on first save.

**French cleat backing:** enable it under 3D export to add a parametric 45-degree hanging rail, lower spacer and optional matching wall cleat. The wall cleat has two hardware holes with a T-pin head slot, clear-plastic-pin head pocket, or screw countersink. Set pin diameter to match the hardware; the screw shank diameter uses 1/16-inch increments. Adjust hole clearance, rail depth, minimum rail height and bevel clearance. The rail height grows to accommodate the heads. A rear pocket with adjustable shell thickness reduces material. STL contains separate closed solids placed side by side; 3DM contains separately named mesh objects. Open **French cleat options** for mounting settings and the **show cleat in live viewer** toggle. The display toggle changes only the preview; the export backing selection stays enabled. Screw-size ticks mark each 1/16-inch step. Use **back view** to inspect the mount. Mounting dimensions are saved in TXT and 3DM metadata; geometry regenerates from these parameters when adjusted.

Version 0.2.0 introduces the morphaic name, relief exports, French-cleat models, mixed cut shapes and the cutting mat. Cut, collage, tone and layers have collapsible panels with disclosure icons on the right. The export icon opens configurations under an **export** header, and display units sit beside each source's page size.

Release downloads include `morphaic-1.2.0.exe` and `morphaic-1.2.0-setup.exe` for Windows and separate `morphaic-1.2.0-macos-apple-silicon.zip` and `morphaic-1.2.0-macos-intel.zip` archives for macOS 15 or later. On a Mac, unzip the matching archive and move `morphaic.app` into Applications. Earlier release downloads retain their historical autocollage names. Mac builds use ad-hoc signing and are not Apple-notarized; macOS may require approval in System Settings > Privacy & Security on first launch.

Run `uv run --extra desktop desktop.py` to open morphaic in its own resizable window. This keeps the existing HTML interface and Python image engine, but does not open an external browser. Windows needs the Microsoft Edge WebView2 Runtime.

GitHub Actions builds and tests the executable before publishing it to [Releases](https://github.com/diafanous/morphaic/releases). To build the local test executable, run `uv sync --extra desktop --group build`, then `./build-test.ps1` on Windows.

Version 0.1.3 adds up to 16 layers, Ctrl+Z/Ctrl+Y edit history, a fixed sidebar header, export settings under the gear button, HEIC imports, and folder selection. Exports save to Downloads by default; choose another folder in settings to remember it. Existing exports receive numbered filenames rather than being overwritten.

Version 0.1.4 adds native Mac builds and a lightweight TXT export of slider values, tone curves, drawing guide points, source metadata, and map settings. The TXT file contains readable UTF-8 JSON and does not embed source images.

GIF and MP4 exports default to **full resolution** (canvas size × export DPI). Choose a 2160, 1440, 1080 or 720 px long edge to render a smaller version without upscaling. There is no GIF MB cap or automatic size-based shrinking. MP4 pads odd dimensions by at most one pixel for codec compatibility. Smoothness controls frame count and pace controls duration (6 seconds by default); both formats have an animation preview and an approximate render-time range measured from a sample at the selected resolution. Large full-resolution animations can take substantial time and disk space. GIF frames are encoded incrementally to keep memory use bounded.

Choose **GPU when available** to composite collage frames on an OpenGL 3.3 GPU for GIF and MP4. Supported MP4 hardware encoders (NVIDIA, Intel, AMD, or Apple) are tested before use; unavailable acceleration falls back to CPU. Image transforms, source decoding, effects, GIF palette encoding, and migration-map rasterization still use CPU. The estimate reports the active compositor and encoder. GPU availability and performance depend on the driver and selected resolution. CPU remains the default renderer, and full resolution is selected on every launch.

The **animate** dropdown switches between collage and migration map. Each migration line grows from its start node while the section outline travels, turns and scales using the map styling. Triptych exports a PNG with original, collage, and map panels. Start/end markers, marker size, colours and opacities remain configurable; use "save map settings as default" to remember map styling.

## How it works

1. **Source.** Add any number of images or PDFs (drag onto the window too). The physical size is read from the PDF page or the image's dpi tag. If an image has no dpi tag the size is assumed at 300 dpi and flagged; type the real width and the height follows. **Random from folder:** paste a folder path, say how many, press *pick*: that many random images/PDFs from the folder (not its sub-folders) replace the previous random pick; files you added yourself stay.
2. **Cut.** Typed physical section sizes set the cut grid. Mix multiple shapes appears first in the Cut panel. *Portion of each file* below 100% cuts only random square portions of each file (*portions per file* of them), each cut into the same grid; sections stay in the part of the canvas their portion came from.
3. **Collage.** Each section goes back where it was cut, then moves. Every slider value can be typed.

   | slider | does |
   |---|---|
   | scale | section size on the canvas, relative to its real physical size |
   | size variance | random spread around that scale |
   | rotation | max random tilt, degrees |
   | scatter | 0 = home position, 100% = anywhere on the canvas |
   | density | share of sections used per layer |
   | layers | how many times the sections are laid down, each on top of the last |
   | opacity | per-section transparency |
   | edge blur | feathers each section's edge into the paper |
   | grid pull / size / irregularity | the **▦ grid** button on the preview shows a guide grid (moving any of these sliders turns it on). Each section settles in its own cell, a dot marks the landing spot; irregularity makes columns and rows uneven |
   | drawing pull | press **✎ draw** on the preview and sketch: sections drift toward your lines (clear erases them) |
   | seed / paper | reroll the randomness / canvas colour |

   Double-click a slider to reset it. With scatter, variance and rotation at 0 and one layer, the output is the source, rebuilt exactly.
4. **Tone.** Contrast, black/white point and gamma, then a tone curve (click the curve to add a point, drag to move it, double-click to remove). Applied to the sources, so preview and export match.
5. **Output.** Size (in / cm / mm), dpi, and `png` (lossless), `tif` (lossless, Deflate) or `pdf` (page of the exact physical size holding the full-resolution image, lossless). Output is capped at 400 MP.

   - **`map`** exports the *migration map* as one full-quality vector PDF the size of the canvas, exactly the drawing the stage shows: the initial outlines, the migration lines and nodes (plus the guide grid and your drawing, faintly, when they steered) and the final outlines, stacked, each layer with its own tone, line opacity, paper colour and paper opacity (0 = no paper). The layers are real PDF layers, for viewers that support them (browsers don't).
   - **also save portion linework** (when *portion of each file* is below 100%) adds a vector PDF to collage exports. Map exports and map animations always produce one file and ignore older portion-linework settings.

The preview is rendered by the same engine as the export, at screen size. Sliders drag at half resolution and sharpen on release. Layout is in inches, so the export matches the preview at any dpi.

## Layout

| file | |
|---|---|
| `collage.py` | engine: load, cut, layout, render, export |
| `server.py` | local HTTP server, serves the UI and the font |
| `desktop.py` | starts the local server in a standalone pywebview window |
| `index.html` | the UI (no build step, no framework) |
| `test_collage.py` | self-checks |
| `fonts/` | linked folder holding `paper-mono-v1.0.zip`; the server reads the font straight from the zip. Not tracked by git. |

## Limits

- 8-bit RGB only, no colour management: 16-bit inputs are scaled to 8-bit, CMYK is converted naively (ignoring ICC profiles), and exports carry no colour profile.
- The migration map and portion linework are vector, but the collage itself is raster, and PDF sources are rasterised, not kept as vectors. They are rendered at the resolution the sections will actually have (72-600 dpi).
- Tone is one curve applied to all channels together (no separate R/G/B curves). The drawing pull and grid use at most 400 sampled points / 48 grid rows.
- A 24 x 36 in, 300 dpi export (78 MP) with ~200 rotated sections takes about 10-15 s and ~1.3 GB of RAM; rotation dominates.


## Windows test installer and canvas updates

Run `./build-installer.ps1` with Inno Setup 6 or newer installed (or pass `-Compiler` with the ISCC.exe path). It builds `dist/morphaic-1.2.0-setup.exe`, a per-user installer with Start menu shortcut, optional desktop shortcut and uninstaller. The standalone `dist/morphaic-1.2.0.exe` remains available. Both use `assets/morphaic.ico`; its vector master and regeneration script are included. Windows builds are unsigned. The build scripts create local artifacts; tagged GitHub builds publish releases.

The liquid-glass study uses translucent cards, soft reflections and a scrollbar four pixels from the right edge. Wheel zooms about the pointer; Shift+wheel pans horizontally and Alt+wheel pans vertically. Space+drag or middle-drag pans the canvas. Arrow keys pan when the canvas has focus. Fit (or Ctrl/Cmd+0) restores the view. These controls do not alter export dimensions. In the cutting mat, arrow keys and Space retain keyboard knife control; middle-drag and wheel still navigate.

## InDesign templates

Choose **InDesign** in 2D export, then **import file**. The selector starts empty and accepts `.indd`, `.indt` and `.idml`. Adobe InDesign must be installed on Windows. Morphaic reads the template's image frames and lets you choose what drawing goes in each; unassigned frames keep their original content. Importing a different template replaces the frame assignments. Templates and assignments are retained only for the current app session.

For automatic placement, set image frame Script Labels in InDesign to `morphaic:collage`, `morphaic:initial`, `morphaic:migration`, `morphaic:final`, `morphaic:map`, or `morphaic:source:1` (source numbers follow the current source list). Labels without the `morphaic:` prefix also work for image frames. Unlabeled frames can be assigned manually. Use `morphaic:title` or `morphaic:seed` on text frames to fill the drawing title or seed. Choose fit entire image or fill frame to control cropping.

Export fills a copy of the template and saves a ZIP containing INDD, IDML, PDF and settings. Generated drawings are embedded; other linked assets remain as supplied by the template. The original file is unchanged. There is no fixed number of drawings or hard-coded layout: the selected template's frames determine placement.

Version 1.0.1: mixed-shape toggle and shape selector share a row; controller mode uses a compact button with shortcut tooltip. Migration nodes include plus signs. GIF/MP4 exports use one eased transition for duplication, rotation and movement, with frame density based on duration and a shared GIF palette.

Version 1.1.0: GIF export has a max-size dropdown (1 to 50 MB; 50 MB is the cap) and shrinks the frames until the file fits. GIF and MP4 can animate the migration map instead of the collage, and animations default to 6 seconds. The map export is one full-quality vector PDF, the drawing shown in the preview. Map settings gain typeable opacity percentages and separate colours for start nodes, end nodes and connecting lines.

Map exports save exactly the displayed drawing as one vector PDF, PNG or TIFF. Raster maps use the selected canvas dimensions and DPI. Each map layer has stroke width (points), tone and opacity controls. Migration lines can use destination cut-shape colors independently of the end-node glyph. Optional tone gradients run from the common line tone to the end tone (or destination cut-shape color); optional opacity gradients use independent start/end values. Start and end nodes each have their own opacity percentage. These styling choices can be saved as map defaults.

Every color swatch has a hue/hex editor with saturation, lightness and the native color picker, including dynamically added gradient stops and cut-shape colors. Opacity controls show editable percentages and percentage tooltips.

The Triptych export has its own PNG/PDF submenu. Both are one-file compositions. PDF places the original and collage panels at the selected DPI and preserves the migration map as vector artwork, including native smooth tone/opacity gradients.
