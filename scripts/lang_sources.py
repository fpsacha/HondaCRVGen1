r"""
The mod's other languages (2026-10-25). One source file per language, scripts\translations\<CODE>.json (UTF-8, no BOM):
one object keyed by the EN Translate file's base name, each holding that file's keys -> the translated text, mirroring
mod\...\42\media\lua\shared\Translate\EN\*.json, e.g.

    {"ItemName": {"Base.CRVGen1_Awning": "..."}, "IG_UI": {...}, "Print_Text": {...}, ...}

<CODE> is the game's own Translate folder code (42.21: media\lua\shared\Translate\<CODE>\language.json; Simplified
Chinese is CN, Traditional CH). gen_scripts.translations() writes Translate\<CODE>\<File>.json from it beside EN.

How the game reads them (projectzomboid.jar 42.21, zombie.core.Translator / Languages):
  * Translator.loadFiles fills every map through forLanguageStack: EN first, then the language's `base` chain, then
    the language itself, each from the game's folder and then every mod's common/ and 42/ folder
    (tryFillMapFromFile: <dir>/media/lua/shared/Translate/<CODE>/<File>.json, Files.readString = UTF-8, org.json).
    A later language overwrites a key unless its value is empty, so a key missing from <CODE> shows the English.
  * Languages lists a mod's Translate/<CODE> folder as a language only when it holds a language.json, and then
    REPLACES the game's entry for that code (ArrayList.set): the mod must never ship one.
  * A JSON error throws "JSON Error in: <file>" (RuntimeException) while the game loads: the files must parse.
  * Placeholders are getText's %1..%9; the rich-text panels (tooltips, the manual's text window, sandbox tooltips)
    break lines at spaces only (ISRichTextPanel.paginate), so vanilla's CN text keeps ASCII punctuation followed by a
    space (", " ". " ": "); this mod's CJK strings do the same, except the owner's manual's words
    (Print_Text_CRVGen1_ManualPage_*), which FunctionMenu.lua wraps per character itself.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = os.path.join(HERE, "translations")
# the language folders the 42.21 game ships (media/lua/shared/Translate/<CODE>/language.json), used when the game is
# not installed here
GAME_LANGUAGES = ("AR", "CA", "CH", "CN", "CS", "DA", "DE", "EN", "ES", "ES_CL", "ES_MX", "FI", "FR", "HU", "ID", "IT",
                  "JP", "KO", "NL", "NO", "PL", "PT", "PTBR", "RO", "RU", "STREW", "TH", "TR", "UA")
MANUAL_PREFIX = "Print_Text_CRVGen1_ManualPage_"     # client/HondaCRVGen1_FunctionMenu.lua M.MANUAL_KEY_PREFIX


class SourceError(Exception):
    pass


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise SourceError("duplicate key %r" % k)
        out[k] = v
    return out


def read_json(path):
    """A JSON file the way the game needs it: UTF-8 without a BOM, no duplicate keys (one would silently win)."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise SourceError("%s starts with a UTF-8 BOM" % path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceError("%s is not UTF-8: %s" % (path, exc))
    try:
        return json.loads(text, object_pairs_hook=_no_dupes)
    except (ValueError, SourceError) as exc:
        raise SourceError("%s: %s" % (path, exc))


def codes():
    """The language codes that have a source file."""
    if not os.path.isdir(SOURCES):
        return []
    return sorted(fn[:-5] for fn in os.listdir(SOURCES) if fn.endswith(".json"))


def load(code):
    return read_json(os.path.join(SOURCES, code + ".json"))


# ---------------------------------------------------------------------------------------- what must match per key
TAG = re.compile(r"<[^<>]*>")
PLACEHOLDER = re.compile(r"%\d")


def signature(s):
    """What a translation must keep from the English: getText's %1..%9 (as a multiset), the rich-text and print-media
    tags in order (<LINE>, <H2>, <br>, <RGB:...>, <type:...>), the manual's **bold** markers, the Print_Text "\n"
    escapes (a literal backslash + n), and the print media parser's "^" line breaks."""
    return {"placeholders": sorted(PLACEHOLDER.findall(s)),
            "tags": [re.sub(r"\s+", " ", t.strip()) for t in TAG.findall(s)],
            "bold": s.count("**"),
            "newlines": s.count("\\n"),
            "carets": s.count("^")}


def problems(code, src, en_tables):
    """Every way the source `src` of language `code` disagrees with the English tables: (kind, message) pairs.
    kind 'unknown' (a file or key the EN files do not have), 'missing' (an EN key without a translation), 'markup'
    (placeholders / tags / markers differ), 'value' (not a non-empty string), 'code' (not a game language)."""
    out = []
    if code == "EN" or code not in GAME_LANGUAGES:
        out.append(("code", "%s is not one of the game's other language folders %s" % (code, ", ".join(GAME_LANGUAGES))))
    if not isinstance(src, dict):
        return out + [("value", "%s: the source is not an object of files" % code)]
    for fname, table in src.items():
        if fname not in en_tables:
            out.append(("unknown", "%s: %s.json is not an EN Translate file" % (code, fname)))
            continue
        if not isinstance(table, dict):
            out.append(("value", "%s %s: not an object of keys" % (code, fname)))
            continue
        for k, v in table.items():
            if k not in en_tables[fname]:
                out.append(("unknown", "%s %s: %s is not an EN key (removed or renamed?)" % (code, fname, k)))
            elif not isinstance(v, str) or not v.strip():
                out.append(("value", "%s %s: %s is empty or not a string" % (code, fname, k)))
            elif signature(v) != signature(en_tables[fname][k]):
                a, b = signature(en_tables[fname][k]), signature(v)
                diff = ", ".join("%s %s -> %s" % (n, a[n], b[n]) for n in a if a[n] != b[n])
                out.append(("markup", "%s %s: %s keeps the English markup (%s)" % (code, fname, k, diff)))
    for fname, table in en_tables.items():
        got = src.get(fname) if isinstance(src.get(fname), dict) else {}
        for k in table:
            if k not in got:
                out.append(("missing", "%s %s: no translation for %s" % (code, fname, k)))
    return out


# --------------------------------------------------------------------------------------------- the game's fonts
def needs_fallback(s):
    """FunctionMenu.lua M.needsFallback: a character the game's SDF fonts have no glyph for (Hebrew .. Thai ..
    Hangul Jamo, and CJK / kana / Hangul past U+2FFF) moves the manual string to the language's UI font."""
    return any(0x0590 <= ord(c) < 0x1E00 or ord(c) > 0x2FFF for c in s)


def is_cjk(c):
    """FunctionMenu.lua's per-character break class: CJK ideographs, kana, CJK punctuation, full-width forms
    (Hangul keeps breaking at spaces, as Korean is written with them)."""
    o = ord(c)
    return 0x2E80 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFE30 <= o <= 0xFE4F \
        or 0xFF00 <= o <= 0xFFEF


def _fnt_chars(path):
    with open(path, encoding="utf-8") as f:
        return set(int(m) for m in re.findall(r"^char id=(\d+)", f.read(), re.M))


def _fonts_txt(path):
    """font name -> fnt file name, from a media/fonts/<CODE>/fonts.txt"""
    out = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            for name, body in re.findall(r"font\s+(\w+)\s*\{([^}]*)\}", f.read()):
                m = re.search(r"fnt\s*=\s*([^,\s]+)", body)
                if m:
                    out[name] = m.group(1)
    return out


def font_file(game, code, font):
    """The .fnt TextManager loads for UIFont `font` in language `code` at the default font size: EN's fonts.txt, then
    the language's own over it (TextManager.loadFontsFile, 42.21), the file from media/fonts/<CODE>/1x, <CODE>/,
    EN/1x or media/fonts/."""
    base = os.path.join(game, "media", "fonts")
    table = _fonts_txt(os.path.join(base, "EN", "fonts.txt"))
    table.update(_fonts_txt(os.path.join(base, code, "fonts.txt")))
    fn = table.get(font)
    if not fn:
        return None
    for d in (os.path.join(base, code, "1x"), os.path.join(base, code), os.path.join(base, "EN", "1x"), base):
        p = os.path.join(d, fn)
        if os.path.exists(p):
            return p
    return None


def font_chars(game, code, font):
    p = font_file(game, code, font)
    return _fnt_chars(p) if p else None


def vanilla_chars(game, code):
    """Every character the game's own <CODE> translation uses (media/lua/shared/Translate/<CODE>/*.json)."""
    out = set()
    d = os.path.join(game, "media", "lua", "shared", "Translate", code)

    def walk(v):
        if isinstance(v, str):
            out.update(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.endswith(".json"):
                try:
                    with open(os.path.join(d, fn), encoding="utf-8") as f:
                        walk(json.load(f))
                except ValueError:
                    pass
    return out


def missing_glyphs(game, code, src):
    """Characters a string uses that the font drawing it has no glyph for (they draw nothing): the manual's words
    in the SDF fonts (all five) or, for a fallback string, the language's Medium font; everything else in the
    language's Small and Medium UI fonts. [(file, key, chars)]
    42.21's CN / CH fonts (Noto Sans TC, 15862 glyphs) lack ~870 simplified characters the game's own CN text uses
    (这 们 来 时 为 开 ...): [(file, key, missing chars, the ones the game's own <CODE> text never uses)]; only the
    last are the translation's fault (a character the game itself does not draw is no worse than vanilla)."""
    sdf = None
    for name in ("SdfRegular", "SdfBold", "SdfItalic", "SdfBoldItalic", "SdfCaveat"):
        c = font_chars(game, code, name)
        if c is not None:
            sdf = c if sdf is None else sdf & c
    ui = None
    for name in ("Small", "Medium"):
        c = font_chars(game, code, name)
        if c is not None:
            ui = c if ui is None else ui & c
    med = font_chars(game, code, "Medium")
    vanilla = vanilla_chars(game, code)
    out = []
    for fname, table in src.items():
        for k, v in table.items():
            if not isinstance(v, str):
                continue
            text = TAG.sub("", v).replace("\\n", "")
            if k.startswith(MANUAL_PREFIX):
                have = med if needs_fallback(text) else sdf
            else:
                have = ui
            if have is None:
                continue
            bad = sorted(set(c for c in text if ord(c) >= 32 and ord(c) not in have))
            if bad:
                out.append((fname, k, "".join(bad), "".join(c for c in bad if c not in vanilla)))
    return out
