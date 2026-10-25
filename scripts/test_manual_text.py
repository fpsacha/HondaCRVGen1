r"""
H-SAVES-I5: the owner's manual's words are translatable. The spreads ship without them (scripts/manual_art.py records
every string with its box) and client/HondaCRVGen1_FunctionMenu.lua lays getText(Print_Text_CRVGen1_ManualPage_<id>)
over the art with the game's SDF fonts, as vanilla's newspapers do (text elements in the print media data string).

  * the art: drawing the spreads puts no words into the texture, only the allowed decorative glyphs (badge numbers
    and letters, "kg", "!", heading numbers, the dealer's stamp);
  * the keys: every string in HondaCRVGen1_ManualLayout.lua has its English in the generated Print_Text.json;
  * the window: openPrintMedia hands vanilla's parser one text element per line / run, in the player's language
    (a stub language), "<", ">" and "^" (the parser's own markers) stripped;
  * the layout under lupa with the game's own .fnt metrics (TextManager.MeasureStringX = AngelCodeFont.getWidth):
    English fills its boxes at full size; a ~40% longer pseudo-German re-wraps inside every box, shrinks no
    further than M.MIN_FIT, and stays on the page; flows push their paragraphs down; **bold** runs, glued
    punctuation; a string the SDF fonts cannot draw falls back to the language's UI font.

    python scripts\test_manual_text.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manual_art as MA                      # noqa: E402
from lua_harness import Side                 # noqa: E402

TRANSLATE = os.path.join(MA.ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "lua", "shared", "Translate", "EN")
FAILS = []


def check(ok, msg):
    if not ok:
        FAILS.append(msg)
        print("FAIL", msg)


def side(strings, measure=True):
    fonts = {n: MA.Fnt(n) for n in MA.SDF_FONTS}
    s = Side("sp")
    g = s.L.globals()
    g.PY_MEASURE = lambda name, t: fonts[name].width(t) if name in fonts else 10 * len(t)
    g.PY_TEXT = lambda k: strings.get(k, k)
    s.run("""
        getText = function(k) return PY_TEXT(k) end
        UIFont = { FromString = function(n) return n end }
        ISVehicleMenu = { FillMenuOutsideVehicle = function() end, showRadialMenuOutside = function() end }
        ISWorldObjectContextMenu = {}
        HondaCRVGen1 = { Function = { MANUAL_SPREADS = {}, KNOW_HOW = "K" }, Shared = {} }
    """)
    if measure:
        s.run("""getTextManager = function() return { MeasureStringX = function(self, f, t) return PY_MEASURE(f, t) end,
                                                      getFontHeight = function(self, f) return 26 end } end""")
    s.load("client/HondaCRVGen1_ManualLayout.lua", "client/HondaCRVGen1_FunctionMenu.lua")
    return s


def strings_en():
    with open(MA.STRINGS_JSON, encoding="utf-8") as f:
        return json.load(f)


def test_art_has_no_words():
    """Drawing the spreads: every string PIL draws into the texture is an allowed decorative glyph."""
    from PIL import ImageDraw
    drawn = []
    orig = ImageDraw.ImageDraw.text

    def spy(self, xy, text, *a, **k):
        drawn.append(text)
        return orig(self, xy, text, *a, **k)
    ImageDraw.ImageDraw.text = spy
    try:
        spreads = MA.draw_spreads()
    finally:
        ImageDraw.ImageDraw.text = orig
    allowed = {"kg", "!", "NOLAN'S USED CARS", "MULDRAUGH  ·  KENTUCKY", "PRE-LOVED CARS   ·   NO LEMONS"}
    words = sorted(set(t for t in drawn if t not in allowed and not re.fullmatch(r"[0-9A-Z]", t)))
    check(not words, "the art carries no words (only badges, glyphs, the stamp): %s" % words[:12])
    n = [len(items) for _img, items in spreads]
    check(min(n) >= 50, "every spread overlays its strings: %s" % n)
    ids = [it["k"] for _img, items in spreads for it in items]
    check(set(ids) == set(MA._STRINGS), "every recorded string has an id")
    print("ART: %d strings overlaid (%s per spread), %d drawn glyphs all decorative" % (len(ids), n, len(drawn)))
    return spreads


def test_keys(spreads):
    with open(os.path.join(TRANSLATE, "Print_Text.json"), encoding="utf-8") as f:
        pt = json.load(f)
    en = strings_en()
    recorded = {MA.KEY_PREFIX + k: v for k, v in MA._STRINGS.items()}
    check(en == recorded, "manual_strings.json is what manual_art.py records (run scripts/manual_art.py)")
    missing = [k for k in en if pt.get(k) != en[k]]
    check(not missing, "Print_Text.json has every manual string's English (run gen_scripts): %s" % missing[:5])
    with open(MA.LAYOUT_LUA, encoding="utf-8") as f:
        lua = f.read()
    ids = set(re.findall(r'\bk = "([^"]+)"', lua))
    check(ids == set(MA._STRINGS), "HondaCRVGen1_ManualLayout.lua names exactly the recorded strings (run manual_art.py)")
    check(lua == MA.layout_lua([items for _img, items in spreads]), "HondaCRVGen1_ManualLayout.lua is up to date")
    print("KEYS: %d Print_Text_CRVGen1_ManualPage_* keys, English in Print_Text.json, layout up to date" % len(en))


def test_window():
    """openPrintMedia: the art's layout string, then the words in the player's language."""
    en = strings_en()
    fr = {k: "FR " + v for k, v in en.items()}
    fr[MA.KEY_PREFIX + "YourCrv"] = "Votre <b>CRV^</b>"
    s = side(fr)
    s.run("""
        F = HondaCRVGen1.Function
        F.MANUAL_SPREADS = { { id = "CRVGen1_Manual", title = "T1", info = "INFO1", text = "TXT1" },
                             { id = "CRVGen1_Manual2", title = "T2", info = "INFO2", text = "TXT2" } }
        PM = nil
        PZAPI = { UI = { PrintMedia = function(args)
            local w = { children = { bar = { children = { name = {} } } } }
            function w:instantiate() end
            w.javaObj = { setAlwaysOnTop = function() end }
            function w:centerOnScreen() end
            PM = w
            return w
        end } }
        M = F.Menu
        M.template = false
        M.openPrintMedia(0, 1)
    """)
    data = s.eval("PM.data")
    check(data.startswith("INFO1<type:text, "), "the window's data: the art's layout first, then text elements")
    els = MA.parse_elements(data[len("INFO1"):])
    texts = " ".join(t for _p, t in els)
    check(len(els) > 100 and texts.count("FR ") > 80, "the words are the player's language (%d elements)" % len(els))
    check("Votre bCRV/b" in texts and "<" not in texts and ">" not in texts and "^" not in texts,
          "a translation's < > ^ are stripped (the parser's markers)")
    check(all(p.get("font") in MA.SDF_FONTS for p, _t in els), "the game's SDF fonts")
    check(all(-5 <= float(p["x"]) <= MA.W + 5 and -20 <= float(p["y"]) <= MA.H for p, _t in els), "on the page")
    check(s.eval("M.overlayCache[1] ~= nil"), "laid out once per spread")
    # no TextManager (a changed game): the art alone, no error
    s2 = side(en, measure=False)
    check(s2.eval("HondaCRVGen1.Function.Menu.manualWords(1)") == "", "no metrics: no words, no error")
    print("WINDOW: %d text elements on spread 1 in the player's language, markers stripped" % len(els))


def layout_report(s, page, ld_check=True):
    """Every item of a spread through M.fit / M.fitFlow: (item, fit, lines, height)."""
    s.run("""
        function REPORT(page)
            local M, out = HondaCRVGen1.Function.Menu, {}
            local items = HondaCRVGen1.ManualLayout.spreads[page]
            local measure = M.measurer()
            local i = 1
            while i <= #items do
                local it = items[i]
                local p = M.prepare(it, getText(M.MANUAL_KEY_PREFIX .. it.k))
                if it.gr and it.gh then
                    local ps, n = { p }, i + 1
                    while n <= #items and items[n].gr == it.gr do
                        ps[#ps + 1] = M.prepare(items[n], getText(M.MANUAL_KEY_PREFIX .. items[n].k)); n = n + 1
                    end
                    local placed = M.fitFlow(ps, measure)
                    local last = placed[#placed]
                    local _l, h = M.linesAt(last.p, last.f, measure)
                    for j, q in ipairs(placed) do
                        local w = 0
                        for _, l in ipairs(q.lines) do w = math.max(w, l.w) end
                        out[#out + 1] = { i = i + j - 1, f = q.f, n = #q.lines, w = w, h = (j == #placed) and (last.top + h) or 0, flow = 1 }
                    end
                    i = n
                else
                    local f, lines, h = M.fit(p, measure)
                    local w = 0
                    for _, l in ipairs(lines) do w = math.max(w, l.w) end
                    out[#out + 1] = { i = i, f = f, n = #lines, w = w, h = h }
                    i = i + 1
                end
            end
            return out
        end
    """)
    rep = s.eval("REPORT(%d)" % page)
    return [dict(rep[k]) for k in sorted(rep.keys())]


def test_layout():
    en = strings_en()
    ps = {k: MA.pseudo(v) for k, v in en.items()}
    longer = sum(len(v) for v in ps.values()) / sum(len(v) for v in en.values())
    check(longer > 1.3, "the pseudo-language is %.0f%% longer" % ((longer - 1) * 100))
    s_en, s_ps = side(en), side(ps)
    lay = s_en.eval("HondaCRVGen1.ManualLayout.spreads")
    shrunk_en, worst = [], 1.0
    for page in (1, 2, 3):
        items = lay[page]
        for lang, s in (("en", s_en), ("pseudo", s_ps)):
            for r in layout_report(s, page):
                it = items[r["i"]]
                f = r["f"]
                if lang == "en" and f < 0.999:
                    shrunk_en.append((page, it.k, round(f, 2)))
                if lang == "pseudo":
                    worst = min(worst, f)
                    check(f >= s.eval("HondaCRVGen1.Function.Menu.MIN_FIT") - 0.001 or not it.w,
                          "a wrapped string shrinks to MIN_FIT at the most (%s %s)" % (page, it.k))
                if it.w:
                    check(r["w"] <= it.w + 2.0 or r["n"] == 1, "%s %d %s: its lines stay %s wide (%.1f)" % (lang, page, it.k, it.w, r["w"]))
                    if r.get("flow"):
                        if r["h"]:
                            gh = [items[j].gh for j in range(r["i"], 0, -1) if items[j].gh][0]
                            check(r["h"] <= gh + 0.5 or f <= 0.701, "%s %d: the flow stays in its box" % (lang, page))
                    else:
                        check(r["h"] <= it.mh + 0.5 or f <= 0.701, "%s %d %s: in its room %.1f (%.1f)" % (lang, page, it.k, it.mh, r["h"]))
                else:
                    check(r["w"] <= it.mw + 0.5 or f <= 0.601, "%s %d %s: one line in %s (%.1f)" % (lang, page, it.k, it.mw, r["w"]))
        # pseudo: the data string's elements stay on the page
        els = MA.parse_elements(s_ps.eval("HondaCRVGen1.Function.Menu.manualWords(%d)" % page))
        check(all(-2 <= float(p["x"]) <= MA.W and 0 <= float(p["y"]) <= MA.H for p, _t in els), "pseudo %d: on the page" % page)
    check(not shrunk_en, "English fills its boxes at full size: %s" % shrunk_en[:6])
    print("LAYOUT: English at full size in every box; pseudo-German (+%.0f%%) re-wraps in its boxes, smallest fit %.2f"
          % ((longer - 1) * 100, worst))


def test_runs_and_fallback():
    s = side({})
    s.run("""
        M = HondaCRVGen1.Function.Menu
        W = M.manualRuns("Fold into a **flat floor and a bed**, then sleep.", "SdfRegular")
        IT = { x = 10, y = 20, s = 9, f = "SdfRegular", c = { 0, 0, 0, 1 }, al = 0, w = 1000, mh = 50, ld = 1.3, a0 = 8 }
        E = M.layoutString(IT, "Fold into a **flat floor and a bed**, then sleep.", M.measurer(), {})
    """)
    words = [(s.eval("W[%d].w" % i), s.eval("W[%d].f" % i), s.eval("W[%d].glue" % i)) for i in range(1, s.eval("#W") + 1)]
    check(words[3] == ("flat", "SdfBold", False) and words[8] == (",", "SdfRegular", True) if len(words) > 8 else False,
          "runs: **bold** words in SdfBold, punctuation glued: %s" % words)
    els = [(s.eval("E[%d].font" % i), s.eval("E[%d].text" % i)) for i in range(1, s.eval("#E") + 1)]
    check(els == [("SdfRegular", "Fold into a"), ("SdfBold", "flat floor and a bed"), ("SdfRegular", ", then sleep.")],
          "one element per run on a line: %s" % els)
    check(abs(s.eval("E[2].y") - s.eval("E[1].y")) < 0.01 and s.eval("E[2].x") > s.eval("E[1].x") + 30, "runs side by side")
    # a string the SDF fonts have no glyph for (here: anything past 127, as Kahlua's UTF-16 codes past U+2FFF)
    s.run("M.FALLBACK_ABOVE = 127; E2 = M.layoutString(IT, 'caf' .. string.char(195, 169), M.measurer(), {}); M.FALLBACK_ABOVE = 12287")
    check(s.eval("E2[1].font") == "Medium", "no SDF glyph: the language's UI font")
    # rotation: a 90-degree line reads upwards from its origin
    s.run("E3 = M.layoutString({ x = 100, y = 200, s = 10, f = 'SdfBold', al = 0, an = 90, mw = 500 }, 'TAB', M.measurer(), {})")
    check(s.eval("E3[1].angle") == 90 and s.eval("E3[1].x") < 100 and abs(s.eval("E3[1].y") - 200) < 0.01,
          "an angle turns the line about its origin (the top-left of the line box lands left of a 90-degree origin)")
    print("RUNS: bold runs, glued punctuation, one element per run, fallback font, rotation")


def main():
    spreads = test_art_has_no_words()
    test_keys(spreads)
    test_window()
    test_layout()
    test_runs_and_fallback()
    if FAILS:
        print("MANUAL TEXT TESTS FAILED: %d" % len(FAILS))
        sys.exit(1)
    print("MANUAL TEXT TESTS OK")


if __name__ == "__main__":
    main()
