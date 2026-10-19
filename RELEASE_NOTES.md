# Morphaic 1.1.0

- GIF export has a max-size dropdown (1, 2, 5, 10, 25 or 50 MB). 50 MB is both the largest option and the default, so a GIF that would be bigger is now shrunk until it fits; if shrinking would take it below 120 pixels, the export says so. The animation preview obeys the same limit.
- GIF and MP4 can animate the migration map instead of the collage (new *animate* dropdown): each line grows from its start node while the section outline travels, turns and scales, in the map's own colours and node styles; the map settings appear while it is selected, and the files are named collage-map-process.gif / .mp4.
- Animation pace now defaults to 6 seconds (was 12), so GIF and MP4 exports have fewer frames by default.
- Map settings: a typeable percentage beside every opacity slider, and separate colours for start nodes, end nodes and connecting lines (the nodes follow the line colour until you pick one; the two node colours are saved with the map defaults).
- The map export is now a single full-quality vector PDF with real PDF layers (the drawing the stage shows) instead of a zip of four files. "Also save portion linework" still adds a second file, which makes the download a zip. InDesign templates still receive the separate initial, migration and final drawings.

# Morphaic 1.0.1

- Compact Cut, grain import, animation preview and controller-mode controls; stronger button backgrounds and aligned header edges.
- Editable custom-grain DPI that preserves physical texture scale across preview and export.
- Simultaneous eased duplication, rotation and migration in GIF/MP4, with smoother frame sampling and a shared GIF palette.
- Plus-sign migration start/end markers, including shape-specific end markers.

# Morphaic 1.0

A new glass workspace, integrated window controls, canvas-only controller mode, expanded image effects and high-detail relief exports.

- Improved grayscale UI clarity and text size; collapsible color grading, grain and gradient-map panels.
- Canvas context menu with reset, source removal and quick export; undoable global reset with optional persistent confirmation suppression.
- Neutral import defaults, including seam-free rendering for unchanged images with odd dimensions.
- Exposure, temperature, tint, saturation, seeded physical-scale grain, custom grain textures and multistop gradient maps, shared across preview and export.
- Relief spacing down to 0.01 mm, compact dense meshes beyond 500,000 vertices and chunked binary STL output. Available-memory checks replace the old fixed vertex ceiling.
- Transparent cutting tools over the actual canvas, a faint workspace grid, pointer-centered wheel zoom and two-axis panning.
- Liquid-glass styling in light and dark modes; scrollbar closer to the edge.
- Mix shapes moved to the top of Cut; physical section sizes replace redundant percentage sliders.
- Empty InDesign template importer with label-based placement or manual frame assignments; fills INDD/INDT/IDML copies and exports native, IDML and PDF layouts using installed Windows InDesign.
- Per-user Windows EXE installer, optional desktop shortcut, uninstaller and multi-resolution app icon.
- Integrated glass window-control bubble beside Export replaces the native title bar; app-name dragging, corner resizing and F11/Escape full-screen controls.

- Relief generation uses the edited canvas directly; a single estimated file size replaces detailed mesh and memory readouts.
- Transparent sidebar with cards floating over a continuous grid; outlined header buttons and compact view controls.

- Canvas-only controller display mode in settings, with F8 toggle and Escape exit.
- Optional uninstall of a detected previous Morphaic installation during setup.

Windows downloads: `morphaic-1.0.0.exe` (portable) and `morphaic-1.0.0-setup.exe` (installer).

# morphaic 0.2.0

Collage is now morphaic. Desktop windows and release downloads use the new name, while existing export-folder preferences, map defaults and saved stencils migrate from the previous application settings.

- Separate 2D and 3D export settings. Existing image, document, animation and migration-map exports remain available in 2D.
- Generate luminosity reliefs from an imported image or the current collage. Export STL in ASCII or binary, Rhino 3DM, and grayscale PNG or TIF maps. Model coordinates always use millimeters; typed width and height follow canvas proportions.
- Adjustable relief depth, base thickness, mesh spacing, gamma, contrast, smoothing and inversion. The live 3D viewer supports orbit, zoom, front/back views and a movable window.
- Parametric French-cleat backing, an optional separate wall cleat, T-pin/plastic-pin/screw holes, screw sizes in 1/16-inch increments and an optional rear pocket. Preview visibility can be toggled independently of exports.
- Ellipse, triangle, diamond, hexagon, star, heart and custom shape cuts. Mix shapes with shares totaling 100%, lock individual shares and inspect actual cuts in a filled radial chart. Migration end nodes can vary by cut shape.
- A cutting mat with freehand and point-to-point knife drawing, undo/redo shortcuts, optional sound and named stencils saved for future sessions.
- Collapsible editing panels, compact stencil menus and source-size unit controls.

Downloads: `morphaic-0.2.0.exe`, `morphaic-0.2.0-macos-apple-silicon.zip`, and `morphaic-0.2.0-macos-intel.zip`.
