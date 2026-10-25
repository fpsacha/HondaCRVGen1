r"""
The mod's other languages (scripts/lang_sources.py): every scripts\translations\<CODE>.json, checked against the
generated English (mod\...\Translate\EN\*.json) and the game's own rules for that language (42.21 bytecode,
zombie.core.Translator / Languages / TextManager):

  * the code is one of the game's language folders (media/lua/shared/Translate/<CODE>/language.json; the list in
    lang_sources.GAME_LANGUAGES when the game is not installed);
  * the source is UTF-8 without a BOM, valid JSON, no duplicate keys, shaped like the EN files (file -> key -> text);
  * every EN key of every EN file has a non-empty translation, and no key or file the English does not have;
  * per key the markup matches the English: %1..%9, rich-text / print-media tags in order (<LINE>, <H2>, <br>,
    <type:...>), the manual's **bold** markers, Print_Text's "\n" escapes, "^";
  * the generated Translate\<CODE>\*.json are exactly the source (re-generated here into a temp folder and compared
    with the shipped ones), UTF-8 without a BOM, parse as JSON, and the folder has no language.json (a mod's one
    replaces the game's entry for that language);
  * with the game installed: every character has a glyph in the font that draws it (the language's Small / Medium UI
    fonts; the owner's manual's words in the SDF fonts, or the Medium UI font when they fall back) - a missing glyph
    draws nothing. 42.21's CN fonts have no en / em dash, ellipsis or curly quotes, for one.

    python scripts\test_translations.py
"""
import json
import os
import shutil
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):            # Windows consoles default to cp1252: CJK/Cyrillic output
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lang_sources as LS                    # noqa: E402

ROOT = os.path.dirname(HERE)
TRANSLATE = os.path.join(ROOT, "mod", "Contents", "mods", "HondaCRVGen1", "42", "media", "lua", "shared", "Translate")
FAILS = []


def check(ok, msg):
    if not ok:
        FAILS.append(msg)
        print("FAIL", msg)
    return ok


def game_dir():
    try:
        with open(os.path.join(ROOT, "local_paths.json"), encoding="utf-8") as f:
            g = json.load(f).get("game")
        return g if g and os.path.isdir(g) else None
    except (OSError, ValueError):
        return None


def en_tables():
    en_dir = os.path.join(TRANSLATE, "EN")
    return {fn[:-5]: LS.read_json(os.path.join(en_dir, fn)) for fn in sorted(os.listdir(en_dir)) if fn.endswith(".json")}


def test_game_languages(game):
    """GAME_LANGUAGES is the game's list (so a source for a code the game does not know is refused)."""
    if not game:
        print("GAME: not installed here, the built-in 42.21 language list stands")
        return
    t = os.path.join(game, "media", "lua", "shared", "Translate")
    have = tuple(sorted(d for d in os.listdir(t) if os.path.exists(os.path.join(t, d, "language.json"))))
    check(have == tuple(sorted(LS.GAME_LANGUAGES)), "lang_sources.GAME_LANGUAGES is the game's list: %s" % (have,))
    print("GAME: %d language folders, as GAME_LANGUAGES" % len(have))


def test_checker_refuses():
    """The checker itself: each kind of mistake is caught (so a clean pass means something)."""
    en = {"IG_UI": {"A": "Take %1 <LINE> out", "B": "plain"}, "Print_Text": {"C": "**bold** x\\ny"}}
    good = {"IG_UI": {"A": "取出 %1 <LINE> 出", "B": "普通"}, "Print_Text": {"C": "**粗**体\\n行"}}
    check(LS.problems("CN", good, en) == [], "a faithful translation passes: %s" % LS.problems("CN", good, en))
    cases = [
        ("missing", {"IG_UI": {"A": "取出 %1 <LINE> 出"}, "Print_Text": {"C": "**粗**体\\n行"}}),
        ("unknown", dict(good, IG_UI=dict(good["IG_UI"], Z="?"))),
        ("unknown", dict(good, Nope={"A": "x"})),
        ("markup", dict(good, IG_UI=dict(good["IG_UI"], A="取出 <LINE> 出"))),          # %1 lost
        ("markup", dict(good, IG_UI=dict(good["IG_UI"], A="取出 %1 出"))),               # tag lost
        ("markup", dict(good, Print_Text={"C": "**粗体\\n行"})),                         # bold marker lost
        ("markup", dict(good, Print_Text={"C": "**粗**体 行"})),                          # \n lost
        ("value", dict(good, IG_UI=dict(good["IG_UI"], B=" "))),
    ]
    for kind, src in cases:
        kinds = [k for k, _m in LS.problems("CN", src, en)]
        check(kind in kinds, "the checker reports %s: %s" % (kind, kinds))
    check([k for k, _m in LS.problems("XX", good, en)] == ["code"], "an unknown language code is refused")
    check([k for k, _m in LS.problems("EN", good, en)] == ["code"], "EN is not a translation source")
    # the source reader: BOM, duplicate keys
    tmp = tempfile.mkdtemp(prefix="crv_lang_")
    try:
        p = os.path.join(tmp, "x.json")
        for raw, why in ((b"\xef\xbb\xbf{}", "BOM"), (b'{"a": {"k": "1", "k": "2"}}', "duplicate"), (b"{,}", "")):
            with open(p, "wb") as f:
                f.write(raw)
            try:
                LS.read_json(p)
                check(False, "read_json refuses %r" % raw)
            except LS.SourceError as exc:
                check(why in str(exc), "read_json refuses %r (%s)" % (raw, exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("CHECKER: missing / unknown / markup / empty / code / BOM / duplicate keys all caught")


def test_language(code, en, game, path=None):
    """path: a source elsewhere (--sources DIR, another branch's file, read only): checked the same way except for the
    generated files, which only this checkout's sources have."""
    try:
        src = LS.load(code) if path is None else LS.read_json(path)
    except LS.SourceError as exc:
        check(False, "%s: %s" % (code, exc))
        return
    probs = LS.problems(code, src, en)
    for _kind, msg in probs:
        check(False, msg)
    counts = {f: len(src.get(f) or {}) for f in en}
    if path is not None:
        test_glyphs(code, src, game, counts, "(not generated here)")
        return
    # the shipped Translate/<CODE> folder is what gen_scripts writes now
    import gen_scripts as gen
    tmp = tempfile.mkdtemp(prefix="crv_lang_")
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            gen.language_translations(tmp, en, sources=[code])
        out = os.path.join(TRANSLATE, code)
        want = sorted(os.listdir(os.path.join(tmp, code)))
        have = sorted(os.listdir(out)) if os.path.isdir(out) else []
        check(want == have, "%s: Translate/%s holds %s (run gen_scripts): %s" % (code, code, want, have))
        for fn in want:
            a = LS.read_json(os.path.join(tmp, code, fn))
            try:
                b = LS.read_json(os.path.join(out, fn))
            except (OSError, LS.SourceError) as exc:
                check(False, "%s: Translate/%s/%s: %s" % (code, code, fn, exc))
                continue
            check(a == b, "%s: Translate/%s/%s is up to date (run gen_scripts)" % (code, code, fn))
            check(isinstance(b, dict) and all(isinstance(v, str) for v in b.values()),
                  "%s: %s is a flat key -> text map" % (code, fn))
        check("language.json" not in have, "%s: no language.json in the mod (it would replace the game's language)" % code)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    test_glyphs(code, src, game, counts, "generated files current")


def test_glyphs(code, src, game, counts, gen_note):
    if game:
        bad = LS.missing_glyphs(game, code, src)
        for fname, k, _chars, own in bad:
            check(not own, "%s %s: %s uses %r, which the game's %s font cannot draw and the game's own %s text never "
                  "uses" % (code, fname, k, own, code, code))
        gap = sorted(set("".join(chars for _f, _k, chars, _o in bad)))
        glyphs = ("every character has a glyph in its font" if not gap else
                  "%d characters missing from the game's %s fonts, all also used by the game's own %s text "
                  "(42.21's font gap): %s" % (len(gap), code, code, "".join(gap)))
    else:
        glyphs = "fonts not checked (no game here)"
    print("%s: %s keys (%d in all), markup kept, %s, %s"
          % (code, ", ".join("%s %d" % (f, n) for f, n in counts.items()), sum(counts.values()), gen_note, glyphs))


def test_english_glyphs(en, game):
    """The checker's font model on the English (EN must pass it, or the model is wrong)."""
    if not game:
        return
    bad = LS.missing_glyphs(game, "EN", en)
    check(not bad, "the English draws in the EN fonts: %s" % bad[:5])
    # and the model catches what it must: an em dash in CN (42.21's CN fonts have none, nor does vanilla CN use one)
    probe = {"IG_UI": {"K": "a — b"}, "Print_Text": {LS.MANUAL_PREFIX + "X": "中—"}}
    own = [o for _f, _k, _c, o in LS.missing_glyphs(game, "CN", probe)]
    check(own == ["—", "—"], "an em dash is caught in CN UI text and in a CN manual string: %s" % own)


def main():
    game = game_dir()
    en = en_tables()
    test_game_languages(game)
    test_checker_refuses()
    test_english_glyphs(en, game)
    codes = LS.codes()
    check(codes, "at least one translation source in scripts/translations")
    for code in codes:
        test_language(code, en, game)
    args = sys.argv[1:]
    for i, a in enumerate(args):                 # --sources DIR: other branches' files, read only
        if a == "--sources" and i + 1 < len(args):
            d = args[i + 1]
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".json"):
                    test_language(fn[:-5].upper(), en, game, path=os.path.join(d, fn))
    stray = sorted(d for d in os.listdir(TRANSLATE) if d != "EN" and d not in codes)
    check(not stray, "every Translate/<CODE> folder has its source (run gen_scripts): %s" % stray)
    if FAILS:
        print("TRANSLATION TESTS FAILED: %d" % len(FAILS))
        sys.exit(1)
    print("TRANSLATION TESTS OK (%s)" % ", ".join(codes))


if __name__ == "__main__":
    main()
