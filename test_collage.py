"""py test_collage.py  (also works under pytest)"""
import io
import json
import math
import pathlib
import struct
import tempfile
import threading
import zipfile
import urllib.request
from collections import Counter

import pymupdf
from PIL import Image, ImageChops

import collage as C
import server
import luminosity as L
import mounting
import shapes

# neutral settings: sections go back exactly where they were cut
FLAT = dict(cw=0.25, ch=0.25, scale=1, var=0, rot=0, scatter=0, density=1, layers=1, opacity=1, bg="#000000")


def png(w, h, dpi=None, color=None):
    im = Image.new("RGB", (w, h), color) if color else Image.effect_noise((w, h), 80).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG", **({"dpi": (dpi, dpi)} if dpi else {}))
    return im, buf.getvalue()


def pdf(w_pt=612, h_pt=792):
    doc = pymupdf.open()
    page = doc.new_page(width=w_pt, height=h_pt)
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(1, 0, 0))
    return doc.tobytes()


def store_of(*sources):
    return {str(i): s for i, s in enumerate(sources)}


def test_size_read_from_file_or_assumed():
    a = C.open_source("a", png(300, 150, dpi=100)[1])
    assert (a.w_in, a.assumed) == (3.0, False)
    b = C.open_source("b", png(300, 150)[1])
    assert (b.w_in, b.assumed) == (1.0, True)               # 300 px at the assumed 300 dpi
    c = C.open_source("c", pdf())
    assert (c.w_in, c.aspect, c.pages, c.assumed) == (8.5, 792 / 612, 1, False)


def test_16bit_gray_is_scaled_not_clipped():
    ramp = b"".join(struct.pack("<H", x * 257) for _ in range(4) for x in range(256))   # 0 .. 65535
    buf = io.BytesIO()
    Image.frombytes("I;16", (256, 4), ramp).save(buf, "PNG")
    out = C.raster(C.open_source("g", buf.getvalue()))
    assert [out.getpixel((x, 0))[0] for x in (0, 64, 128, 255)] == [0, 64, 128, 255]


def test_source_size_is_json_serialisable_for_every_format():
    for fmt in ("PNG", "TIFF", "JPEG"):   # TIFF dpi arrives as a rational, which json can't encode
        buf = io.BytesIO()
        Image.new("RGB", (300, 150), "red").save(buf, fmt, dpi=(300, 300))
        s = C.open_source("x", buf.getvalue())
        assert json.loads(json.dumps(dict(w=s.w_in, aspect=s.aspect)))["w"] == 1.0, fmt


def test_unreadable_file_is_rejected():
    for junk in (b"not an image", b"%PDF-1.4 garbage"):
        try:
            C.open_source("x", junk)
        except ValueError:
            continue
        raise AssertionError("accepted junk")


def test_neutral_settings_rebuild_the_source_exactly():
    im, data = png(200, 160, dpi=100)
    store = store_of(C.open_source("a", data))
    _, out = C.compose({**FLAT, "w": 2, "h": 1.6, "dpi": 100}, [{"id": "0", "w": 2}], store, final=True)
    assert ImageChops.difference(im, out).getbbox() is None


def test_rotated_sections_have_no_dark_fringe():
    _, data = png(100, 100, dpi=100, color="white")
    store = store_of(C.open_source("a", data))
    raw = {**FLAT, "bg": "#ffffff", "rot": 40, "scatter": 0.2, "var": 0.3, "w": 1, "h": 1, "dpi": 100}
    for final in (False, True):
        _, out = C.compose({**raw, "pv": 400}, [{"id": "0", "w": 1}], store, final=final)
        assert out.getextrema() == ((255, 255),) * 3, final


def test_layout_is_deterministic_and_stable():
    p = C.clean({**FLAT, "rot": 30, "scatter": 0.5, "var": 0.4, "seed": 7})
    sizes = [(4, 3)]
    one = C.layout(p, sizes, 8, 6)
    assert one == C.layout(p, sizes, 8, 6)
    assert C.layout({**p, "layers": 3}, sizes, 8, 6)[:len(one)] == one      # more layers only add on top
    moved = C.layout({**p, "scatter": 0.9}, sizes, 8, 6)
    assert [x[6] for x in moved] == [x[6] for x in one]                    # scatter doesn't reshuffle angles
    assert moved != one


def test_exports_carry_size_and_dpi():
    store = store_of(C.open_source("a", png(400, 300, dpi=200)[1]))
    raw = {**FLAT, "rot": 10, "scatter": 0.3, "w": 2, "h": 1.5, "dpi": 200}
    specs = [{"id": "0", "w": 2}]

    out = Image.open(io.BytesIO(C.export(raw, specs, store, "png")[0]))
    assert out.size == (400, 300) and round(out.info["dpi"][0]) == 200

    out = Image.open(io.BytesIO(C.export(raw, specs, store, "tif")[0]))
    assert out.size == (400, 300) and round(out.info["dpi"][0]) == 200 and out.mode == "RGB"

    doc = pymupdf.open(stream=C.export(raw, specs, store, "pdf")[0], filetype="pdf")
    assert len(doc) == 1 and doc[0].rect == pymupdf.Rect(0, 0, 144, 108)    # 2 x 1.5 in
    img = doc[0].get_images(full=True)[0]
    assert doc.extract_image(img[0])["width"] == 400                        # full resolution, not downsampled

    try:
        C.export(raw, specs, store, "bmp")
    except ValueError:
        pass
    else:
        raise AssertionError("accepted bmp")


def test_pdf_source_and_multiple_sources():
    store = store_of(C.open_source("p", pdf()), C.open_source("i", png(200, 100, dpi=100)[1]))
    specs = [{"id": "0", "w": 8.5, "page": 0}, {"id": "1", "w": 2}]
    raw = {**FLAT, "layers": 2, "rot": 20, "scatter": 0.5, "w": 4, "h": 5, "dpi": 100}
    _, out = C.compose(raw, specs, store, final=True)
    assert out.size == (400, 500) and out.getextrema() != ((0, 0),) * 3
    assert C.preview({**raw, "pv": 300}, specs, store)[:2] == b"\xff\xd8"    # JPEG


def test_output_size_limit_and_clamping():
    store = store_of(C.open_source("a", png(50, 50, dpi=50)[1]))
    try:
        C.compose({"w": 200, "h": 200, "dpi": 1200}, [{"id": "0", "w": 1}], store, final=True)
    except ValueError as e:
        assert "limit" in str(e)
    else:
        raise AssertionError("no limit")
    p = C.clean({"cw": -5, "layers": 99, "bg": "red; drop table"})
    assert (p["cw"], p["layers"], p["bg"]) == (0.05, 16, "#f4f2ee")


def two_sections():
    """A 4in x 3in white source on an 8 x 6 canvas."""
    store = store_of(C.open_source("a", png(400, 300, dpi=100, color="white")[1]))
    return store, [{"id": "0", "w": 4}], {**FLAT, "w": 8, "h": 6, "dpi": 50}


def pieces(raw, size=(4, 3)):
    p = C.clean(raw)
    return C.layout(p, [size], p["w"], p["h"])


def test_corners_turn_the_way_pillow_rotates():
    tile = Image.new("RGBA", (100, 60), (255, 255, 255, 255))
    tile.paste((0, 0, 0, 255), (0, 0, 10, 10))                       # black mark in the top-left corner
    rot = tile.rotate(30, Image.BICUBIC, expand=True)
    dark = [(x, y) for y in range(rot.height) for x in range(rot.width)
            if rot.getpixel((x, y))[3] > 200 and rot.getpixel((x, y))[0] < 60]
    mark = (sum(x for x, _ in dark) / len(dark) - rot.width / 2, sum(y for _, y in dark) / len(dark) - rot.height / 2)
    tl = C.corners(0, 0, 100, 60, 30)[0]
    assert abs(mark[0] - tl[0]) < 10 and abs(mark[1] - tl[1]) < 10, (mark, tl)   # mark sits at corner 0, not another


def test_grid_pull_lands_sections_on_the_nodes():
    raw = {**FLAT, "w": 8, "h": 6, "scatter": 0.7, "gs": 1, "gn": 4, "gi": 0}
    on_node = lambda v, cell: abs((v / cell - 0.5) - round(v / cell - 0.5)) < 1e-9       # v = (i + .5) * cell
    for pc in pieces(raw):
        assert on_node(pc[2], 2) and on_node(pc[3], 2), pc                              # 8in / 4 cols, 6in / 3 rows
    assert any(not on_node(pc[2], 2) for pc in pieces({**raw, "gi": 1}))               # irregular grid moves the nodes


def test_drawn_strokes_pull_sections_toward_them():
    line = [[0.9, y / 40] for y in range(41)]                                          # a vertical stroke at 90% across
    raw = {**FLAT, "w": 8, "h": 6, "scatter": 0.8, "pts": line, "draw": 1}
    assert all(abs(pc[2] - 7.2) < 1e-9 for pc in pieces(raw))
    assert any(abs(pc[2] - 7.2) > 0.5 for pc in pieces({**raw, "draw": 0}))            # pull 0 leaves them alone


def test_portions_cut_only_part_of_each_file():
    raw = {**FLAT, "ps": 0.4, "pn": 2}
    part, whole = pieces(raw), pieces({**FLAT, "ps": 1})
    assert len(part) == 2 * 16 and len(whole) == 16
    rects = C._portions(C.clean(raw), 0)
    for pc in part:
        u0, v0, u1, v1 = pc[1]
        assert any(a - 1e-9 <= u0 and u1 <= c + 1e-9 and b - 1e-9 <= v0 and v1 <= d + 1e-9 for a, b, c, d in rects)
    assert rects == C._portions(C.clean(raw), 0)                                       # stable for a seed


def test_tone_lut():
    assert C.tone_lut(C.clean({})) == C.IDENT
    hi = C.tone_lut(C.clean({"con": 1}))
    assert hi[64] < 64 and hi[192] > 192                                               # contrast spreads
    lv = C.tone_lut(C.clean({"lb": 100, "lw": 200}))
    assert lv[100] == 0 and lv[200] == 255 and abs(lv[150] - 127.5) < 1.5
    assert C.tone_lut(C.clean({"lg": 2}))[64] > 64                                     # gamma > 1 lifts the mids
    inv = list(range(255, -1, -1))
    assert C.tone_lut(C.clean({"curve": inv}))[0] == 255                               # the curve is applied
    assert C.clean({"curve": [1, 2, 3]})["curve"] == C.IDENT                           # wrong-length curve ignored
    store = store_of(C.open_source("w", png(50, 50, 50, "white")[1]))
    _, im = C.compose({**FLAT, "w": 1, "h": 1, "dpi": 50, "curve": inv}, [{"id": "0", "w": 1}], store, final=True)
    assert im.getpixel((10, 10)) == (0, 0, 0)                                          # white source comes out black


def test_edge_blur_fades_section_edges_only():
    store, specs, raw = two_sections()
    raw = {**raw, "cw": 1, "ch": 1, "bg": "#000000"}                                   # one section, the whole source
    sharp = C.compose(raw, specs, store, final=True)[1]
    soft = C.compose({**raw, "blur": 0.6}, specs, store, final=True)[1]
    w, h = sharp.size
    assert sharp.getpixel((w // 2, h // 2)) == (255, 255, 255) == soft.getpixel((w // 2, h // 2))   # centre untouched
    edge = (w // 2 - 98, h // 2)                                                       # 2px inside the section's left edge
    assert sharp.getpixel(edge) == (255, 255, 255) and soft.getpixel(edge)[0] < 60


def test_grid_spreads_sections_one_per_cell():
    raw = {**FLAT, "w": 8, "h": 6, "scatter": 0.7, "gs": 1, "gn": 8, "gi": 0}          # 8 x 6 = 48 cells for 16 sections
    spots = [(round(pc[2], 6), round(pc[3], 6)) for pc in pieces(raw)]
    assert len(set(spots)) == 16                                                       # nobody shares a cell
    assert len({round(pc[2], 6) for pc in pieces({**raw, "gn": 3})}) <= 3             # coarse grid: only 3 columns exist


def test_irregular_grid_has_uneven_cells():
    even = C._grid(C.clean({**FLAT, "w": 8, "h": 6, "gn": 6, "gi": 0}), 8, 6)
    odd = C._grid(C.clean({**FLAT, "w": 8, "h": 6, "gn": 6, "gi": 1}), 8, 6)
    widths = lambda xs: [b - a for a, b in zip(xs, xs[1:])]
    assert max(widths(even[0])) - min(widths(even[0])) < 1e-9 and len(even[0]) == 7
    assert max(widths(odd[0])) / min(widths(odd[0])) > 1.5                             # visibly uneven
    assert abs(odd[0][-1] - 8) < 1e-9 and abs(odd[1][-1] - 6) < 1e-9                  # still fills the canvas


def test_preview_overlay_draws_the_grid_only_when_asked():
    store, specs, raw = two_sections()
    raw = {**raw, "pv": 400, "gs": 1, "gn": 4}
    plain = Image.open(io.BytesIO(C.preview(raw, specs, store))).convert("RGB")
    grid = Image.open(io.BytesIO(C.preview(raw, specs, store, show_grid=True))).convert("RGB")
    def orange(im):
        d = im.tobytes()
        return sum(1 for i in range(0, len(d), 3) if d[i] > 200 and 60 < d[i + 1] < 130 and d[i + 2] < 100)
    assert orange(plain) == 0 and orange(grid) > 200
    out = C.export(raw, specs, store, "png")[0]                                        # exports never carry the overlay
    assert orange(Image.open(io.BytesIO(out)).convert("RGB")) == 0


def map_raw():
    store, specs, raw = two_sections()
    return store, specs, {**raw, "scatter": 0.8, "rot": 40, "m1p": "#ffffff", "m2c": "#ff0000", "m2o": 0.5, "m3a": 0.5, "m3p": "#00ff00"}


def test_map_layers_have_their_own_tone_opacity_and_paper():
    store, specs, raw = map_raw()
    pdfs = C.migration_pdfs(raw, specs, store)
    assert sorted(pdfs) == ["collage-1-initial.pdf", "collage-2-migration.pdf", "collage-3-final.pdf", "collage-map-layers.pdf"]
    docs = {n: pymupdf.open(stream=d, filetype="pdf") for n, d in pdfs.items()}
    for d in docs.values():
        assert len(d) == 1 and d[0].rect == pymupdf.Rect(0, 0, 8 * 72, 6 * 72) and d[0].get_images() == []   # vector, canvas-sized
    one, two, three = (docs[f"collage-{n}.pdf"][0].get_drawings() for n in ("1-initial", "2-migration", "3-final"))
    assert one[0]["fill"] == (1.0, 1.0, 1.0) and one[0]["fill_opacity"] == 1                           # layer 1 paper: white, opaque
    assert all(d["fill"] is None or d["fill"] == (1.0, 0.0, 0.0) for d in two)                         # layer 2 has no paper
    assert two[0]["color"] == (1.0, 0.0, 0.0) and abs(two[0]["stroke_opacity"] - 0.5) < 1e-2            # tone + line opacity honoured
    assert three[0]["fill"] == (0.0, 1.0, 0.0) and abs(three[0]["fill_opacity"] - 0.5) < 1e-2          # layer 3 paper: green, half opaque
    assert len(two[0]["items"]) == 16                                                                  # one center-to-node path per section


def test_map_shows_the_grid_and_strokes_that_steered_it():
    store, specs, raw = map_raw()
    plain = pymupdf.open(stream=C.migration_pdf(raw, specs, store), filetype="pdf")[0].get_drawings()
    steered = pymupdf.open(stream=C.migration_pdf({**raw, "gs": 1, "gn": 4, "pts": [[0.1, 0.1], [0.9, 0.9]], "draw": 1}, specs, store), filetype="pdf")[0].get_drawings()
    assert len(steered) == len(plain) + 2                                                             # a grid drawing and a stroke drawing


def test_combined_map_layers_switch_off_on_their_own():
    store, specs, raw = map_raw()
    raw = {**raw, "m2a": 0, "m3a": 0}
    pdf = C.migration_pdf(raw, specs, store)
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    assert sorted(o["name"] for o in doc.get_ocgs().values()) == ["1 initial", "2 migration", "3 final"]
    assert [x["layer"] for x in doc[0].get_drawings() if x.get("layer")][:2] == ["1 initial", "1 initial"]   # paper + outlines

    def inked(hide):
        d = pymupdf.open(stream=pdf, filetype="pdf")
        for ui in d.layer_ui_configs():
            if ui["text"] in hide:
                d.set_layer_ui_config(ui["number"], 2)                                  # 2 = off
        px = d[0].get_pixmap(dpi=30, alpha=False).samples
        return sum(1 for i in range(0, len(px), 3) if px[i:i + 3] != b"\xff\xff\xff")

    base = inked(())
    assert all(inked((n,)) < base for n in ("1 initial", "2 migration", "3 final"))
    assert inked(("1 initial", "2 migration", "3 final")) == 0
    im = Image.open(io.BytesIO(C.preview({**raw, "pv": 400}, specs, store, as_map=True)))
    assert im.size[0] == 400                                                            # the stage can show it


def test_portion_linework_and_zip():
    store, specs, raw = two_sections()
    raw = {**raw, "ps": 0.5, "pn": 3}
    pdf = pymupdf.open(stream=C.portions_pdf(raw, specs, store), filetype="pdf")
    assert len(pdf) == 1 and pdf[0].rect == pymupdf.Rect(0, 0, 4 * 72, 3 * 72)
    assert sum(1 for d in pdf[0].get_drawings() if d.get("width") == 1.5) == 3         # one heavy outline per portion
    data, name = C.export(raw, specs, store, "png", lines=True)
    assert name == "collage.zip" and sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == ["collage-portions.pdf", "collage.png"]
    data, name = C.export(raw, specs, store, "map")
    assert name == "collage-map.pdf" and data[:4] == b"%PDF"                            # one drawing, not a zip
    data, name = C.export(raw, specs, store, "map", lines=True)
    assert name == "collage-map.zip" and sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == ["collage-map.pdf", "collage-portions.pdf"]   # + portion linework
    try:
        C.export({**raw, "ps": 1}, specs, store, "png", lines=True)
    except ValueError as e:
        assert "portion" in str(e)
    else:
        raise AssertionError("linework without portions")


def test_random_folder_pick():
    with tempfile.TemporaryDirectory() as d:
        for i in range(5):
            (pathlib.Path(d) / f"{i}.png").write_bytes(png(20, 20, 50)[1])
        (pathlib.Path(d) / "notes.txt").write_text("x")
        (pathlib.Path(d) / "sub").mkdir()
        got, total = server.pick_files(f'"{d}"', 3)                                    # quoted, as Explorer's Copy as path gives it
        assert total == 5 and len(got) == 3 and len({f.name for f in got}) == 3 and all(f.suffix == ".png" for f in got)
        assert len(server.pick_files(d, 99)[0]) == 5
        assert len({frozenset(f.name for f in server.pick_files(d, 2)[0]) for _ in range(30)}) > 1   # genuinely random
        for bad in (d + "-missing", d + "/notes.txt"):
            try:
                server.pick_files(bad, 1)
            except ValueError:
                continue
            raise AssertionError(bad)
    with tempfile.TemporaryDirectory() as empty:
        try:
            server.pick_files(empty, 1)
        except ValueError as e:
            assert "no images" in str(e)
        else:
            raise AssertionError("empty folder")


def test_a_busy_port_is_never_shared():
    a = server.Server(("127.0.0.1", 0), server.Handler)
    port = a.server_address[1]
    threading.Thread(target=a.serve_forever, daemon=True).start()
    try:
        assert server.running(port) == server.STAMP                      # a copy of this code is recognised and reused
        try:
            server.Server(("127.0.0.1", port), server.Handler)           # Windows would silently share the port otherwise
        except OSError:
            pass
        else:
            raise AssertionError("a second server bound the same port")
    finally:
        a.shutdown()
        a.server_close()
    assert server.running(port) is None                                  # nothing answers once it has stopped


def test_heic_animation_and_triptych_exports():
    import imageio_ffmpeg
    buf = io.BytesIO()
    Image.new('RGB',(80,60),'#ed6139').save(buf,'HEIF',quality=95)
    src = C.open_source('sample.heic',buf.getvalue())
    assert src.thumbs[0].size == (80,60)
    store, specs = {'heic':src}, [{'id':'heic','w':1,'page':0}]
    raw = dict(w=1,h=.75,dpi=48,rot=35,scatter=.6,layers=2,opacity=.6,smoothness=4,pace=3)
    frames = list(C.animation_frames(raw,specs,store))
    items,_ = C._gif_items(C.clean(raw),specs,store)
    final = C.render(C.clean(raw),items,raw['dpi'],Image.BILINEAR)
    assert len(frames)==C.animation_timing(C.clean(raw))[0] and ImageChops.difference(frames[-1],final).getbbox() is None
    gif = Image.open(io.BytesIO(C.export(raw,specs,store,'gif')[0]))
    assert gif.is_animated and gif.info['loop']==0
    with tempfile.TemporaryDirectory() as folder:
        path = pathlib.Path(folder)/'process.mp4'
        path.write_bytes(C.export(raw,specs,store,'mp4')[0])
        reader = imageio_ffmpeg.read_frames(str(path),pix_fmt='rgb24')
        metadata = next(reader)
        assert len(list(reader))==C.animation_timing(C.clean(raw))[0] and abs(metadata['duration']-3)<.25
    triple = Image.open(io.BytesIO(C.export(raw,specs,store,'triptych')[0]))
    assert triple.size==(158,36) and round(triple.info['dpi'][0])==48
    _, normal = C.compose(raw,specs,store,final=True)
    assert ImageChops.difference(triple.crop((55,0,103,36)),normal).getbbox() is None


def test_gif_keeps_full_resolution_without_size_cap():
    store, specs = {'n': C.open_source('noise.png', png(300, 200, 100)[1])}, [{'id': 'n', 'w': 3, 'page': 0}]
    raw = dict(w=3, h=2, dpi=300, scatter=.6, layers=2, smoothness=4, pace=3)
    big = C.export({**raw, 'gifmb': 50}, specs, store, 'gif')[0]
    assert len(big) > 1_000_000 and Image.open(io.BytesIO(big)).size == (900,600)
    small = C.export({**raw, 'gifmb': 1}, specs, store, 'gif')[0]
    gif = Image.open(io.BytesIO(small))
    assert len(small)>1_000_000 and gif.is_animated and gif.size==(900,600) and gif.info['loop']==0
    assert 'gifmb' not in C.clean({'gifmb':1})


def test_animation_pace_default_is_six_seconds_everywhere():
    import re
    html = pathlib.Path(C.__file__).with_name('index.html').read_text(encoding='utf-8')
    default = C.SPEC['pace'][2]
    frames, fps = C.animation_timing(C.clean({}))
    assert default == 6 and C.clean({})['pace'] == 6 and abs(frames / fps - 6) < 1e-9           # engine default and real duration
    assert re.search(r'id="pace"[^>]*value="6"', html) and 'pace: 6,' in html and '>6 seconds<' in html   # slider, its label, page state


def test_map_settings_node_colours_and_typed_percentages():
    import re
    html = pathlib.Path(C.__file__).with_name('index.html').read_text(encoding='utf-8')
    for key in re.findall(r'(\w+):', re.search(r'map: \{([^}]*)\}', html).group(1)):
        assert f'id="{key}"' in html, key                                  # a setting with no control would stop the page's setup loop
    for key in ('m1o', 'm1a', 'm2o', 'm2a', 'm3o', 'm3a'):
        assert f'id="{key}_pct"' in html, key                              # typed percentage beside every opacity slider
    follows = C.clean({'m2c': '#112233'})                                  # unset node colours follow the line colour (old settings look the same)
    assert follows['m2s'] == follows['m2e'] == '#112233'
    apart = C.clean({'m2c': '#112233', 'm2s': '#00ff00', 'm2e': 'oops'})
    assert (apart['m2s'], apart['m2e']) == ('#00ff00', '#112233')          # a bad value falls back to the line colour
    assert 'm2s' in server.MAP_KEYS and 'm2e' in server.MAP_KEYS           # saved as map defaults too
    store, specs, raw = map_raw()
    raw = {**raw, 'm2c': '#ff0000', 'm2s': '#00ff00', 'm2e': '#0000ff', 'm2o': 1, 'node_start': 'dot', 'node_end': 'dot', 'scatter': .8}
    layer2 = [d for d in pymupdf.open(stream=C.migration_pdf(raw, specs, store), filetype='pdf')[0].get_drawings() if d.get('layer') == '2 migration']
    assert {d['color'] for d in layer2} >= {(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)}          # lines red, start nodes green, end nodes blue
    assert {d['fill'] for d in layer2} >= {(0.0, 1.0, 0.0), (0.0, 0.0, 1.0)}


def test_map_exports_one_drawing_and_can_be_animated():
    store, specs, raw = map_raw()
    html = pathlib.Path(C.__file__).with_name('index.html').read_text(encoding='utf-8')
    assert 'downloads a zip' not in html and 'separate vector pdfs' not in html          # the zip note is gone from the map menu
    assert 'id="anim"' in html and 'migration map</option>' in html
    data, name = C.export(raw, specs, store, 'map')
    assert name == 'collage-map.pdf' and data[:4] == b'%PDF'
    pixels = lambda pdf: pymupdf.open(stream=pdf, filetype='pdf')[0].get_pixmap(dpi=40, alpha=False).samples   # PDFs embed a timestamp, so compare what they draw
    assert pixels(data) == pixels(C.migration_pdf(raw, specs, store))                    # exactly the drawing the stage shows
    assert 'collage-3-final.pdf' in C.migration_pdfs(raw, specs, store)                  # the InDesign export still gets the separate layers
    assert C.clean({'anim': 'oops'})['anim'] == 'collage' and C.clean({'anim': 'map'})['anim'] == 'map'
    anim = {**raw, 'anim': 'map', 'smoothness': 4, 'pace': 3}
    frames = list(C.animation_frames(anim, specs, store))
    assert len(frames) == C.animation_timing(C.clean(anim))[0]
    page = pymupdf.open(stream=C.migration_pdf(anim, specs, store), filetype='pdf')[0]
    z = max(C.animation_size(C.clean(anim))) / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z), alpha=False)
    still = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    assert ImageChops.difference(frames[-1], still).getbbox() is None                    # the last frame IS the finished map
    assert ImageChops.difference(frames[0], frames[-1]).getbbox() is not None            # and the map moved to get there
    gif, name = C.export(anim, specs, store, 'gif')
    assert name == 'collage-map-process.gif' and Image.open(io.BytesIO(gif)).is_animated
    mp4, name = C.export(anim, specs, store, 'mp4')
    assert name == 'collage-map-process.mp4' and mp4[4:8] == b'ftyp'
    assert C.export({**anim, 'anim': 'collage'}, specs, store, 'gif')[1] == 'collage-process.gif'   # the default still animates the collage


def test_migration_node_boundaries_and_scaling():
    import math
    for scale in (.25,1,6):
        for style in ('none','dot','ring','square','plus','arrow'):
            p = C.clean(dict(node_end=style,node_end_size=scale))
            for cx,cy in ((1,0),(0,1),(1,1),(-1,1)):
                pc = (0,(0,0,1,1),cx,cy,1,1,0,0,0,1,1)
                end = C.migration_line_end(p,pc)
                gap = math.hypot(cx-end[0],cy-end[1])
                if style in ('dot','ring'):
                    assert abs(gap-.045*scale)<1e-9
                elif style=='square':
                    assert abs(max(abs(cx-end[0]),abs(cy-end[1]))-.045*scale)<1e-9
                elif style=='plus':
                    expected = .045*scale*(.3*math.sqrt(2) if cx and cy else 1)
                    assert abs(gap-expected)<1e-9
                elif style=='arrow':
                    assert abs(gap-min(.12*scale,math.hypot(cx,cy)/3))<1e-9
                else:
                    assert gap<1e-9


def test_plus_nodes_are_preserved_and_drawn():
    raw = dict(w=2,h=2,cols=2,rows=2,scatter=.7,node_start='plus',node_end='plus')
    p = C.clean(raw)
    assert p['node_start']==p['node_end']=='plus'
    by_shape = C.clean({**raw,'node_by_shape':True,'node_end_shapes':{'rectangle':'plus'}})
    assert by_shape['node_end_shapes']['rectangle']=='plus'
    store = {'source':C.open_source('plus.png',png(64,64,color='red')[1])}
    doc = pymupdf.open(stream=C._map_doc(p,[{'id':'source','w':2}],store,(2,)),filetype='pdf')
    assert any(len(d['items'])>=12 for d in doc[0].get_drawings())


def test_plain_text_settings_preserve_alterations_without_image_data():
    raw = {**FLAT,'layers':16,'rot':42,'unit':'cm','grid_visible':True,
           'node_end':'ring','node_end_size':3,'pts':[[.1,.2],[.8,.9]],'curve':list(range(256))}
    data,name = C.export(raw,[],{},'txt',lines=True)
    saved = json.loads(data)
    assert name=='collage-settings.txt' and len(data)<10000
    assert saved['parameters']['layers']==16 and saved['parameters']['rot']==42
    assert saved['parameters']['pts']==raw['pts'] and saved['parameters']['curve']==raw['curve']
    assert saved['parameters']['node_end_size']==3 and saved['units']=='cm'
    assert saved['portion_linework'] and saved['guides']['grid_visible']
    assert saved['sources']==[]


def test_sixteen_layers_supported():
    p = C.clean({**FLAT,'layers':16,'w':1,'h':1,'dpi':64})
    assert p['layers']==16
    assert len(C.layout(p,[(1,1)],1,1))==16*len(C.layout({**p,'layers':1},[(1,1)],1,1))
    store = {'source':C.open_source('layers.png',png(64,64,color='red')[1])}
    _, im = C.compose(p,[{'id':'source','w':1}],store,final=True)
    assert im.size==(64,64)


def test_export_folder_persistence_and_no_overwrite():
    original_settings, original_folder = server.SETTINGS_PATH, server.EXPORT_FOLDER
    try:
        with tempfile.TemporaryDirectory() as folder:
            server.SETTINGS_PATH = pathlib.Path(folder)/'settings.json'
            selected = server.set_export_folder(folder)
            assert json.loads(server.SETTINGS_PATH.read_text())['export_folder']==str(selected)
            first = server.save_export(b'one','collage.png')
            second = server.save_export(b'two','collage.png')
            assert first.name=='collage.png' and second.name=='collage (1).png'
            assert first.read_bytes()==b'one' and second.read_bytes()==b'two'
            defaults = server.save_map_defaults({'m2c':'#ff0000','m2s':'#00ff00','m2e':'#0000ff','node_end':'ring','node_end_size':3})
            server.set_export_folder(folder)
            assert server.map_defaults()==defaults and defaults['node_end_size']==3
            assert defaults['m2c']=='#ff0000' and defaults['node_end']=='ring' and defaults['m2s']=='#00ff00' and defaults['m2e']=='#0000ff'
    finally:
        server.SETTINGS_PATH, server.EXPORT_FOLDER = original_settings, original_folder


def test_shape_cuts_default_and_transparent_corners():
    store = {'a': C.open_source('white.png', png(120,120,dpi=120,color='white')[1])}
    spec = [{'id':'a','w':1}]
    raw = {**FLAT,'cw':1,'ch':1,'w':1,'h':1,'dpi':120}
    _, rectangle = C.compose(raw,spec,store,final=True)
    assert rectangle.getextrema() == ((255,255),)*3
    for shape in ('ellipse','triangle','diamond','hexagon','star','heart','custom'):
        _, image = C.compose({**raw,'cut_shape':shape,'custom_shape':[[.5,0],[1,1],[0,1]]},spec,store,final=True)
        assert image.getpixel((0,0)) == (0,0,0), shape
        assert image.getpixel((60,60)) == (255,255,255), shape


def test_mixed_shapes_are_stable_across_motion_resolution_and_layers():
    p = C.clean({**FLAT,'multi_shape':True,'shape_weights':{'rectangle':30,'ellipse':70},'cw':.05,'ch':.05})
    pcs = C.layout(p,[(1,1)],1,1)
    before = {pc[:2]:shapes.shape_for(p,pc) for pc in pcs}
    moved = C.layout({**p,'scatter':1,'rot':150,'scale':2,'layers':3},[(1,1)],1,1)
    assert all(shapes.shape_for(p,pc)==before[pc[:2]] for pc in moved)
    counts = shapes.counts(p,pcs)
    assert sum(counts.values()) == 400 and 230 < counts['ellipse'] < 330
    assert C.clean({})['cut_shape']=='rectangle' and not C.clean({})['multi_shape']


def test_custom_stencil_and_shares_validation():
    for raw in ({'shape_weights':{'ellipse':float('nan')}}, {'shape_weights':{'star':-1}},
                {'multi_shape':True,'shape_weights':{'custom':100}}, {'custom_shape':[[float('inf'),0]]}):
        try:
            C.clean(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f'invalid stencil accepted: {raw}')
    assert C.clean({'shape_weights':{}})['shape_weights']['rectangle']==100


def test_shape_migration_outlines_and_per_shape_marker_trimming():
    raw={**FLAT,'cut_shape':'triangle','node_by_shape':True,'node_end_shapes':{'triangle':'ring'},'node_end':'square'}
    p=C.clean(raw)
    pc=(0,(0,0,1,1),1,1,.5,.5,0,0,1,.5,.5)
    assert shapes.end_style(p,pc)=='ring'
    assert C.migration_line_end(p,pc)==(.955,1)
    p['node_end_shapes']['triangle']='cut'
    end=C.migration_line_end(p,pc)
    assert abs(end[0]-.9775)<1e-9 and end[1]==1
    store={'a':C.open_source('a.png',png(100,100,color='white')[1])}
    for shape in ('rectangle','ellipse','triangle','diamond','hexagon','star','heart','custom'):
        data=C.migration_pdf({**raw,'cut_shape':shape,'custom_shape':[[.5,0],[1,1],[0,1]],'w':1,'h':1},[{'id':'a','w':1}],store)
        doc=pymupdf.open(stream=data,filetype='pdf')
        assert len(doc)==1 and doc[0].get_drawings()


def luminosity_fixture():
    image=Image.new('RGB',(16,8),'black')
    ImageDraw = __import__('PIL.ImageDraw',fromlist=['Draw'])
    ImageDraw.Draw(image).rectangle((8,0,15,7),fill='white')
    buf=io.BytesIO();image.save(buf,'PNG')
    store={'a':C.open_source('half.png',buf.getvalue())}
    return store, [{'id':'a','w':1}], {**FLAT,'w':1,'h':.5,'dpi':100}, dict(source='import',source_id='a',width_mm=20,height_mm=10,spacing_mm=2,base_mm=2,relief_mm=8)


def test_relief_mesh_is_closed_outward_and_in_millimeters():
    store,spec,raw,options=luminosity_fixture()
    model=L.mesh(raw,spec,store,options)
    assert model['units']=='mm' and model['grid']==[11,6]
    assert min(v[0] for v in model['vertices'])==0 and max(v[0] for v in model['vertices'])==20
    assert min(v[1] for v in model['vertices'])==0 and max(v[1] for v in model['vertices'])==10
    assert min(v[2] for v in model['vertices'])==0 and max(v[2] for v in model['vertices'])==10
    edges=Counter()
    volume=0
    for face in model['faces']:
        for a,b in zip(face,face[1:]+face[:1]):edges[a,b]+=1
        a,b,c=[model['vertices'][i] for i in face]
        volume += (a[0]*(b[1]*c[2]-b[2]*c[1])+a[1]*(b[2]*c[0]-b[0]*c[2])+a[2]*(b[0]*c[1]-b[1]*c[0]))/6
    assert all(count==1 and edges[b,a]==1 for (a,b),count in edges.items())
    assert volume>0
    inverse=L.mesh(raw,spec,store,{**options,'invert':True})
    assert abs(model['vertices'][0][2]+inverse['vertices'][0][2]-12)<1e-8


def test_stl_encodings_and_3dm_round_trip():
    import rhino3dm
    store,spec,raw,options=luminosity_fixture()
    model=L.mesh(raw,spec,store,options)
    for encoding in ('ascii','binary'):
        data,name=L.export(raw,spec,store,{**options,'encoding':encoding},'stl')
        assert name.endswith('-mm.stl')
        if encoding=='ascii':
            assert data.startswith(b'solid morphaic_mm') and data.count(b'facet normal')==len(model['faces'])
            assert b'vertex 20 ' in data
        else:
            assert len(data)==84+50*len(model['faces']) and struct.unpack_from('<I',data,80)[0]==len(model['faces'])
    data,name=L.export(raw,spec,store,options,'3dm')
    doc=rhino3dm.File3dm.FromByteArray(data)
    assert doc.Settings.ModelUnitSystem==rhino3dm.UnitSystem.Millimeters
    assert len(doc.Objects)==1 and doc.Objects[0].Geometry.IsClosed
    assert len(doc.Objects[0].Geometry.Faces)==len(model['faces'])


def test_luminosity_raster_exports_and_current_collage():
    store,spec,raw,options=luminosity_fixture()
    for source in ('import','collage'):
        for fmt in ('png','tif'):
            data,name=L.export(raw,spec,store,{**options,'source':source},fmt)
            im=Image.open(io.BytesIO(data))
            assert im.mode=='L' and im.size==(79,39) and abs(im.info['dpi'][0]-100)<.1
            assert im.getpixel((1,1))==0 and im.getpixel((77,1))==255
    for key,value in [('spacing_mm',0),('width_mm',float('nan')),('base_mm',0)]:
        try:L.mesh(raw,spec,store,{**options,key:value})
        except ValueError:pass
        else:raise AssertionError(f'invalid geometry accepted: {key}')
    try:L.mesh(raw,spec,store,{**options,'width_mm':5000,'height_mm':5000,'spacing_mm':.05})
    except ValueError as error:assert 'increase mesh spacing' in str(error)
    else:raise AssertionError('oversized mesh accepted')
    assert max(L.mesh(raw,spec,store,{**options,'width_mm':5000,'height_mm':5000,'spacing_mm':.05},preview=True)['grid'])<=81


def test_saved_named_stencils_preserve_settings_and_rename():
    original=server.SETTINGS_PATH
    try:
        with tempfile.TemporaryDirectory() as folder:
            server.SETTINGS_PATH=pathlib.Path(folder)/'settings.json'
            server.update_settings({'export_folder':folder,'map_defaults':{'node_end':'ring'}})
            saved=server.save_stencil({'name':'My leaf','points':[[.5,0],[1,.7],[.5,1],[0,.7]]})
            assert server.stencil_library()[0]['name']=='My leaf'
            renamed=server.save_stencil({**saved,'name':'Leaf stencil'})
            assert renamed['id']==saved['id'] and len(server.stencil_library())==1
            data=json.loads(server.SETTINGS_PATH.read_text())
            assert data['export_folder']==folder and data['map_defaults']['node_end']=='ring'
            assert data['stencils'][0]['name']=='Leaf stencil'
            for invalid in ({'name':'','points':saved['points']},{'name':'Line','points':[[0,0],[.5,.5],[1,1]]}):
                try:server.save_stencil(invalid)
                except ValueError:pass
                else:raise AssertionError('invalid saved stencil accepted')
    finally:server.SETTINGS_PATH=original


def test_morphaic_settings_read_legacy_and_write_new_location():
    original=(server.SETTINGS_PATH,server.DEFAULT_SETTINGS_PATH,server.LEGACY_SETTINGS_PATH)
    try:
        with tempfile.TemporaryDirectory() as folder:
            root=pathlib.Path(folder)
            server.DEFAULT_SETTINGS_PATH=server.SETTINGS_PATH=root/'Morphaic'/'settings.json'
            server.LEGACY_SETTINGS_PATH=root/'Collage'/'settings.json'
            server.LEGACY_SETTINGS_PATH.parent.mkdir()
            legacy={'export_folder':folder,'stencils':[{'id':'old','name':'Old stencil','points':[[0,0],[1,0],[.5,1]]}]}
            server.LEGACY_SETTINGS_PATH.write_text(json.dumps(legacy))
            assert server.stencil_library()[0]['id']=='old'
            server.update_settings({'new_feature':True})
            assert server.SETTINGS_PATH.exists() and server.read_settings()['stencils']==legacy['stencils']
            assert json.loads(server.LEGACY_SETTINGS_PATH.read_text())==legacy
    finally:server.SETTINGS_PATH,server.DEFAULT_SETTINGS_PATH,server.LEGACY_SETTINGS_PATH=original


def test_shape_shares_reject_totals_above_one_hundred():
    try:C.clean({'shape_weights':{'rectangle':100,'ellipse':70}})
    except ValueError as error:assert '100%' in str(error)
    else:raise AssertionError('overallocated percentages accepted')
    assert sum(C.clean({'shape_weights':{'ellipse':70}})['shape_weights'].values())==100


def test_french_cleat_parts_hardware_holes_and_rear_pocket():
    import manifold3d as m
    import numpy as np
    import rhino3dm
    store,spec,raw,options=luminosity_fixture()
    options={**options,'width_mm':100,'height_mm':75,'base_mm':3,'cleat':True}
    for hardware in ('t-pins','plastic-pins','screws'):
        model=L.mesh(raw,spec,store,{**options,'hardware':hardware})
        assert len(model['parts'])==2 and model['mounting']['bevel_degrees']==45
        for part in model['parts']:
            solid=m.Manifold(m.Mesh(np.asarray(part['vertices'],dtype=np.float32),np.asarray(part['faces'],dtype=np.uint32)))
            assert solid.status()==m.Error.NoError and solid.volume()>0
        body_part=model['parts'][0]
        body=m.Manifold(m.Mesh(np.asarray(body_part['vertices'],dtype=np.float32),np.asarray(body_part['faces'],dtype=np.uint32)))
        assembled_wall=solid.translate((options['width_mm']*(1-options.get('cleat_width',.8))/2-options['width_mm']-8,model['mounting']['assembly_wall_offset_y_mm']-5,0))
        assert (body^assembled_wall).volume()<1e-5
        p=L.clean({**options,'hardware':hardware})
        c=mounting.parameters(p)
        radius=c['hole_diameter']/2
        polygon_area=48/2*math.sin(2*math.pi/48)*radius**2
        expected=c['width']*(c['height']-p['cleat_gap_mm']-c['depth']/2)-2*polygon_area
        assert abs(solid.slice(-c['depth']/2).area()-expected)<.02,hardware
        doc=rhino3dm.File3dm.FromByteArray(L.three_dm(model))
        assert len(doc.Objects)==2 and all(o.Geometry.IsClosed for o in doc.Objects)
        assert 'wall cleat' in doc.Objects[1].Attributes.Name
    plain=L.mesh(raw,spec,store,options)['parts'][0]
    hollow=L.mesh(raw,spec,store,{**options,'hollow_back':True})['parts'][0]
    def volume(part):return m.Manifold(m.Mesh(np.asarray(part['vertices'],dtype=np.float32),np.asarray(part['faces'],dtype=np.uint32))).volume()
    assert volume(hollow)<volume(plain)
    no_wall=L.mesh(raw,spec,store,{**options,'include_wall_cleat':False})
    assert len(no_wall['parts'])==1
    assert mounting.parameters(L.clean({**options,'screw_sixteenths':4}))['hole_diameter']==6.35+.3
    try:L.mesh(raw,spec,store,{**options,'width_mm':10})
    except ValueError:pass
    else:raise AssertionError('undersized cleat accepted')


def test_luminosity_http_exports_and_cut_counts():
    original_folder = server.EXPORT_FOLDER
    original_settings = server.SETTINGS_PATH
    http = server.Server(('127.0.0.1',0),server.Handler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    base = f'http://127.0.0.1:{http.server_address[1]}'
    source_ids = []
    def post(path, data):
        return urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'}),timeout=10)
    try:
        with tempfile.TemporaryDirectory() as folder:
            server.EXPORT_FOLDER=pathlib.Path(folder)
            server.SETTINGS_PATH=pathlib.Path(folder)/'settings.json'
            with post('/stencils',{'name':'HTTP saved stencil','points':[[0,0],[1,0],[.5,1]]}) as response:stencil=json.load(response)['stencil']
            with urllib.request.urlopen(base+'/stencils') as response:library=json.load(response)['stencils']
            assert library[0]['id']==stencil['id'] and library[0]['name']=='HTTP saved stencil'
            with post('/luminosity/demo',{}) as response:source=json.load(response)
            source_ids.append(source['id'])
            assert source['aspect']==.75
            request=dict(p={**FLAT,'w':1,'h':.75,'dpi':100,'multi_shape':True,'shape_weights':{'rectangle':40,'ellipse':60}},
                         sources=[{'id':source['id'],'w':1}],luminosity=dict(source='import',source_id=source['id'],width_mm=20,height_mm=15,spacing_mm=2))
            with post('/luminosity/preview',request) as response:model=json.load(response)
            assert model['units']=='mm' and model['preview']
            with post('/preview',request) as response:
                counts=json.loads(response.headers['X-Cut-Counts'])
                assert sum(counts.values())==16 and counts['rectangle']>0 and counts['ellipse']>0
            for fmt in ('stl','3dm','png','tif'):
                with post('/luminosity/export/'+fmt,request) as response:result=json.load(response)
                saved=pathlib.Path(result['path'])
                assert saved.parent==pathlib.Path(folder).resolve(), (saved,folder)
                assert saved.stat().st_size>100, (fmt,saved.stat().st_size)
            with post('/export/txt',request) as response:result=json.load(response)
            data=json.loads(pathlib.Path(result['path']).read_text())
            assert data['parameters']['multi_shape'] and data['luminosity']['width_mm']==20
            with urllib.request.urlopen(base+'/studio.js') as response:assert b'knifeSeal' in response.read()
    finally:
        server.EXPORT_FOLDER=original_folder
        server.SETTINGS_PATH=original_settings
        for sid in source_ids:server.STORE.pop(sid,None)
        http.shutdown();http.server_close()


def test_animation_moves_rotates_and_duplicates_together():
    p = C.clean(dict(w=4,h=3,layers=3,rot=90,scatter=.8))
    pieces = C.layout(p,[(4,3)],4,3)
    counts = [0]+[len(C.layout(dict(p,layers=i),[(4,3)],4,3)) for i in range(1,4)]
    layers = [layer for layer in range(3) for _ in range(counts[layer+1]-counts[layer])]
    halfway = C.animation_pose(pieces,layers,.5)
    assert any(abs(pc[6])>1 for pc in pieces)
    assert any(abs(pc[2]-pc[7])>.01 for pc in pieces)
    for pc, current, layer in zip(pieces,halfway,layers):
        assert abs(current[6]-pc[6]*.5)<1e-9
        assert abs(current[2]-(pc[7]+pc[2])*.5)<1e-9
        assert current[-1] == (1 if layer==0 else .5)
    assert all(current[:-1]==pc and current[-1]==1 for pc,current in zip(pieces,C.animation_pose(pieces,layers,1)))


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
