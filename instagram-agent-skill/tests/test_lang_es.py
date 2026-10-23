"""
Spanish support in the six text tools (hookscore, beats, caption, humanize, detect, swipe).

What these tests can show and what they cannot. They show that the Spanish code does what it
was written to do, that the six copies of the language detector agree, that the data files are
well formed, and that known failure modes stay fixed. They do NOT show that the Spanish scores
mean anything: the word lists were written by hand and the examples below were written by the
same hand, so passing here is not evidence of accuracy on real Spanish captions or reels.
The English side is covered by test_english_unchanged.py.
"""

import importlib.util
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import warnings

# swipe.py's original readers (hooks.json, the TSV) leave their files for the garbage collector to
# close. That is upstream code and harmless in a short-lived script; it is silenced here by file name
# so that a leak in the Spanish code (hooks.es.json, slop.es.json) would still show up.
warnings.filterwarnings("ignore", category=ResourceWarning, message=r"unclosed file .*(hooks\.json|\.tsv)")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.abspath(os.path.join(HERE, "..", "..", ".claude", "skills"))


def path(rel):
    return os.path.join(SKILLS, rel)


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, path(rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cli(rel, *args, stdin=None):
    run = subprocess.run([sys.executable, "-I", "-B", path(rel), *args], input=stdin,
                         capture_output=True, text=True, timeout=60)
    return run.returncode, run.stdout, run.stderr


hookscore = load("ig-reel/hookscore.py", "hookscore_t")
beats = load("ig-reel/beats.py", "beats_t")
caption = load("ig-caption/caption.py", "caption_t")
humanize = load("ig-human/humanize.py", "humanize_t")
detect = load("ig-human/detect.py", "detect_t")
swipe = load("ig-viral/swipe.py", "swipe_t")

MODULES = {"hookscore": hookscore, "beats": beats, "caption": caption,
           "humanize": humanize, "detect": detect, "swipe": swipe}

SPANISH_HOOKS = [
    "Deja de publicar a diario",
    "No necesitas un nicho",
    "Perdí 18.000 € por una cláusula que no leí",
    "Nadie te cuenta que tus primeros 30 reels fracasan",
    "¿Cómo consigo clientes sin tener seguidores?",
    "Hola chicos, hoy quiero hablar de estrategia",
    "El 33 % de los autónomos no sabe cuánto gana",
    "Mi primer cliente llegó por un café en Valencia",
    "Sígueme para más contenido",
    "Los buenos terminan primero.",
]
ENGLISH_HOOKS = [
    "Nobody tells you that your first 30 reels are supposed to flop.",
    "I lost $18,000 because of one missing contract.",
    "Stop scrolling if you want to grow on Instagram in 2026",
    "Don't do this",
    "Zero dollars. That is what my first client paid me.",
    "Quit your job #entrepreneur",
    "Hola, my name is Sam and I run an agency",
    "Steal this four line follow up it took me two years",
    "33% of freelancers never raise their prices.",
    "This used to take me five hours. Now it takes twenty minutes.",
]

SLOP_ES = ("En el mundo actual, la creación de contenido se ha convertido en un pilar fundamental para cualquier "
           "marca. Cabe destacar que un enfoque integral juega un papel crucial en el éxito. Además, es importante "
           "comprender que la innovación y la constancia son clave. Sumérgete en un ecosistema vibrante y desbloquea "
           "tu potencial. No se trata solo de publicar, sino de conectar. La estrategia correcta te permitirá llevar "
           "tu marca al siguiente nivel. En definitiva, la decisión es tuya.\n")
HUMAN_ES = ("Hace dos años abrí mi cuenta con 40 seguidores, casi todos primos. Publiqué cada día durante tres meses "
            "y no pasó nada. Lo curioso es que mi primer cliente no llegó por un reel, llegó porque Marta le enseñó "
            "mi perfil a su jefa en un café de Valencia. Cobré 300 euros. Con eso pagué el alquiler de abril y "
            "respiré. Después subí a 900, luego a 2.000, y ahí sí perdí clientes, pero me daba igual. Si me preguntas "
            "qué cambió, te diría que dejé de explicar y empecé a enseñar mis facturas.\n")


class LanguageDetectionAgrees(unittest.TestCase):
    def test_the_six_copies_are_the_same_source(self):
        sources = {name: inspect.getsource(mod.detect_lang) for name, mod in MODULES.items()}
        self.assertEqual(1, len(set(sources.values())), "detect_lang differs between modules")

    def test_the_six_copies_give_the_same_answer(self):
        samples = SPANISH_HOOKS + ENGLISH_HOOKS + ["", "12345", "CARRUSELES vs REELS", SLOP_ES, HUMAN_ES]
        for text in samples:
            answers = {name: mod.detect_lang(text) for name, mod in MODULES.items()}
            with self.subTest(text=text[:40]):
                self.assertEqual(1, len(set(answers.values())), answers)

    def test_short_spanish_hooks_are_spanish(self):
        for text in SPANISH_HOOKS:
            with self.subTest(text=text):
                self.assertEqual("es", hookscore.detect_lang(text))

    def test_english_hooks_stay_english(self):
        for text in ENGLISH_HOOKS:
            with self.subTest(text=text):
                self.assertEqual("en", hookscore.detect_lang(text))

    def test_no_evidence_falls_back_to_english(self):
        """Known limit, stated on purpose: a string with no stop word at all is read as English."""
        for text in ("", "12345", "CARRUSELES vs REELS"):
            with self.subTest(text=text):
                self.assertEqual("en", hookscore.detect_lang(text))


class HookscoreSpanish(unittest.TestCase):
    def score(self, text):
        _, overall, verdict, flags = hookscore.run(text, "es")
        return overall, verdict, flags

    def test_a_concrete_cost_hook_is_strong(self):
        overall, verdict, flags = self.score("Perdí 18.000 € por una cláusula que no leí")
        self.assertEqual("STRONG", verdict)
        self.assertEqual([], flags)

    def test_a_greeting_is_a_dealbreaker(self):
        overall, verdict, flags = self.score("Hola chicos, hoy quiero hablar de estrategia")
        self.assertEqual("WEAK", verdict)
        self.assertTrue(any("Greeting" in f for f in flags), flags)

    def test_a_video_preamble_is_a_dealbreaker(self):
        overall, verdict, flags = self.score("En este video te voy a enseñar cómo crecer en Instagram")
        self.assertEqual("WEAK", verdict)
        self.assertTrue(flags)

    def test_good_hooks_outrank_bad_ones(self):
        good = ["Perdí 18.000 € por una cláusula que no leí",
                "Nadie te cuenta que tus primeros 30 reels fracasan"]
        bad = ["Hola chicos, hoy quiero hablar de estrategia",
               "En este video te voy a enseñar cómo crecer en Instagram"]
        self.assertGreater(min(self.score(h)[0] for h in good), max(self.score(h)[0] for h in bad))

    def test_accents_do_not_change_the_score(self):
        self.assertEqual(self.score("Perdí 18.000 € por una cláusula que no leí")[0],
                         self.score("Perdi 18.000 € por una clausula que no lei")[0])

    def test_first_person_is_recognised_without_its_accent_only_where_that_is_safe(self):
        """Past-tense -er/-ir (perdi) and irregular forms (hice, fui) survive losing the accent. A past-tense
        -ar form (gané) does not: 'gane' is also a subjunctive, so it is read as third person. A known limit."""
        address = lambda t: hookscore.run(t, "es")[0]["ADDRESS"][1]
        for text in ("Perdi 18.000 € con un reel", "Hice 18.000 € con un reel", "Gané 5.000 € con un reel"):
            with self.subTest(text=text):
                self.assertIn("first person", address(text))
        self.assertIn("third person", address("Gane 5.000 € con un reel"))

    def test_cli_marks_spanish_and_only_spanish(self):
        code, out, err = cli("ig-reel/hookscore.py", "--hook", "Nadie te cuenta que tus primeros 30 reels fracasan",
                             "--json")
        self.assertEqual("es", json.loads(out)["lang"])
        self.assertIn("language:", err)
        code, out, err = cli("ig-reel/hookscore.py", "--hook", "Nobody tells you your first 30 reels flop", "--json")
        self.assertNotIn("lang", json.loads(out))
        self.assertEqual("", err)


class HookPanelOnTheSpanishSets(unittest.TestCase):
    """The numbers quoted in CONNECT.md, recomputed. If the panel changes, change them there too."""

    def score_file(self, name):
        with open(os.path.join(HERE, "es_hooks", name), encoding="utf-8") as fh:
            lines = [l.strip() for l in fh.read().splitlines() if l.strip()]
        return [hookscore.run(l, "es")[1] for l in lines]

    def measure(self, tag):
        good, bad = self.score_file(f"good_{tag}.txt"), self.score_file(f"bad_{tag}.txt")
        pairs = sum(1 for g in good for b in bad if g > b)
        return pairs, len(good) * len(bad), sum(1 for b in bad if b < 50)

    def test_set_b_the_one_it_was_tuned_on(self):
        self.assertEqual((144, 144, 12), self.measure("B"))

    def test_set_c_written_afterwards(self):
        self.assertEqual((137, 144, 11), self.measure("C"))


class BeatsSpanish(unittest.TestCase):
    def test_a_thousands_separator_does_not_split_a_number(self):
        self.assertEqual(["Perdí", "18000", "por", "una", "cláusula"],
                         beats.words("Perdí 18.000 € por una cláusula", "es"))

    def test_accented_words_stay_whole(self):
        self.assertEqual(["canción", "más", "rápida"], beats.words("canción más rápida", "es"))

    def test_a_spanish_script_gets_a_beat_sheet(self):
        script = ("Perdí 18.000 dólares por una cláusula que no leí.\n"
                  "Esta es la cláusula exacta que ahora pongo en todos los contratos.\n"
                  "Pago contra entrega, no contra aprobación.\n"
                  "Ese cambio vale 18.000 dólares para mí.\n")
        a = beats.analyse(script, wpm=165, target=20, lang="es")
        self.assertEqual(4, len(a["beats"]))
        self.assertTrue(a["total_seconds"] > 0)

    def test_cli_marks_spanish_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "guion.txt")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("Perdí 18.000 dólares por una cláusula que no leí.\nAhora la pongo en todos mis contratos.\n")
            code, out, err = cli("ig-reel/beats.py", p, "--json")
        self.assertEqual("es", json.loads(out)["lang"])


class CaptionSpanish(unittest.TestCase):
    def asks(self, text):
        return caption.analyse(text, lang="es")["asks"]

    def test_the_calls_to_action_it_knows(self):
        cases = [
            ("Comenta CONTRATO y te lo envío", ["comment a keyword"]),
            ("Escríbeme un DM con la palabra PLAN", ["DM me"]),
            ("Te lo mando por DM", ["DM me"]),
            ("Mira el enlace en la bio para verlo", ["link in bio"]),
            ("Todo está en el link en mi bio", ["link in bio"]),
            ("El link de la bio tiene la plantilla", ["link in bio"]),
            ("Desliza para ver el antes y el después", ["swipe or tap"]),
            ("¿Qué opinas? Cuéntame abajo", ["answer a question"]),
            ("Sígueme para más", ["follow"]),
            ("Guarda este post y compártelo con tu equipo", ["save this", "share this"]),
        ]
        for text, want in cases:
            with self.subTest(text=text):
                self.assertEqual(want, self.asks(text))

    def test_ordinary_sentences_are_not_asks(self):
        for text in ("Me toca pagar el café", "Sigue leyendo", "Lo hice solo y funcionó"):
            with self.subTest(text=text):
                self.assertEqual([], self.asks(text))

    def test_hashtags_with_accents_and_enye_are_one_tag(self):
        a = caption.analyse("Una línea.\n\n#diseño #contratos #año #café", lang="es")
        self.assertEqual(["#diseño", "#contratos", "#año", "#café"], a["hashtags"])

    def test_spanish_filler_tags_are_generic(self):
        a = caption.analyse("Una línea.\n\n#parati #tendencia #megusta", lang="es")
        hashtags = [c for c in a["checks"] if c["check"] == "HASHTAGS"][0]
        self.assertEqual("WARN", hashtags["status"])

    def test_search_terms_ignore_accents_but_not_the_enye(self):
        a = caption.analyse("Una página sobre diseño de contratos",
                            keywords=["pagina", "diseno", "diseño", "CONTRATOS"], lang="es")
        detail = [c for c in a["checks"] if c["check"] == "SEARCH TERMS"][0]["detail"]
        self.assertIn("3/4 present", detail)
        self.assertIn("Missing: diseno", detail)

    def test_cli_marks_spanish_in_json(self):
        code, out, err = cli("ig-caption/caption.py", "-", "--json",
                             stdin="Perdí 18.000 € por una cláusula que no leí.\n\nComenta CONTRATO y te la mando.\n")
        self.assertEqual("es", json.loads(out)["lang"])


class SlopLexiconSpanish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(path("ig-human/slop.es.json"), encoding="utf-8") as fh:
            cls.lex = json.load(fh)

    def entries(self):
        return self.lex["words"] + self.lex["phrases"]

    def test_every_entry_is_well_formed(self):
        for e in self.entries():
            with self.subTest(find=e["find"]):
                self.assertIsInstance(e["find"], str)
                self.assertTrue(e["find"].strip())
                self.assertTrue(e["replace"] is None or isinstance(e["replace"], str))
                self.assertIn(e["family"], {"verbs", "nouns", "adjectives", "connectives", "openers", "closers"})
                for form in e.get("forms", []):
                    self.assertIsInstance(form, str)

    def test_every_structure_compiles_and_has_what_the_tools_read(self):
        for s in self.lex["structures"]:
            with self.subTest(id=s["id"]):
                re.compile(s["regex"], re.MULTILINE)
                self.assertTrue({"id", "name", "regex", "fix"} <= set(s))

    def test_structure_ids_are_unique(self):
        ids = [s["id"] for s in self.lex["structures"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_entry_is_listed_twice(self):
        finds = [humanize.strip_accents(e["find"]) for e in self.entries()]
        self.assertEqual(len(finds), len(set(finds)))

    def test_only_invariable_things_are_swapped_blind(self):
        """A swap is only safe where the grammar cannot change. Everything else must be report-only."""
        invariable_adjectives = {"crucial", "cruciales", "sin fisuras"}
        for e in self.entries():
            if e["replace"] is None or e["replace"] == "":
                continue
            with self.subTest(find=e["find"]):
                self.assertTrue(e["family"] in {"connectives", "openers", "closers"}
                                or e["find"] in invariable_adjectives, e["find"])

    def test_the_bare_a_fin_de_is_not_a_form(self):
        """It would turn "a fin de cuentas" into "para cuentas"."""
        for e in self.entries():
            for form in [e["find"], *e.get("forms", [])]:
                with self.subTest(form=form):
                    self.assertNotEqual("a fin de", humanize.strip_accents(form))

    def test_the_language_independent_sections_are_not_repeated(self):
        self.assertNotIn("invisible", self.lex)
        self.assertNotIn("typographic", self.lex)


class HumanizeSpanish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = humanize.load_lexicon_es()

    def clean(self, text):
        out, report = humanize.humanize_es(text, self.lex)
        return out.rstrip("\n"), report

    CASES = [
        ("Sin más preámbulos, aquí tienes el plan.", "Aquí tienes el plan."),
        ("Seamos sinceros: nadie lee los contratos.", "Nadie lee los contratos."),
        ("Es, sin lugar a dudas, el mejor plan que tengo.", "Es el mejor plan que tengo."),
        ("Primero haz esto. Dicho esto, ahora haz lo otro. Y listo.", "Primero haz esto. Ahora haz lo otro. Y listo."),
        ("Hoy lanzamos la guía. ¡Sígueme para más contenido! 🚀", "Hoy lanzamos la guía. 🚀"),
        ("Te lo cuento. 🚀 Guarda esto para después.", "Te lo cuento. 🚀"),
        ("EN EL VERTIGINOSO MUNDO DE LA MODA, TODO CAMBIA.", "EN LA MODA, TODO CAMBIA."),
        ("en el mundo actual, la gente compra más.", "hoy, la gente compra más."),
        ("Pagan con el fin de que lo veas, a fin de cuentas.", "Pagan para que lo veas, a fin de cuentas."),
        ("Lo hice y funcionó, etc., y nadie dijo nada.", "Lo hice y funcionó, etc., y nadie dijo nada."),
        ("Todo cambió. ¿Quién se apunta?", "Todo cambió."),
        ("Por ende, asimismo, es crucial.", "Por eso, también, es importante."),
        ("No obstante, nadie contestó.", "Aun así, nadie contestó."),
        ("Sin mas preambulos, empezamos.", "Empezamos."),
        ("Es cruciales y CRUCIAL.", "Es importantes y IMPORTANTE."),
    ]

    def test_known_cases(self):
        for text, want in self.CASES:
            with self.subTest(text=text):
                self.assertEqual(want, self.clean(text)[0])

    def test_cleaning_twice_changes_nothing_more(self):
        for text, _ in self.CASES + [(SLOP_ES.strip(), ""), (HUMAN_ES.strip(), "")]:
            once = self.clean(text)[0]
            with self.subTest(text=text[:40]):
                self.assertEqual(once, self.clean(once)[0])

    def test_human_text_is_left_alone(self):
        out, report = self.clean(HUMAN_ES.strip())
        self.assertEqual(HUMAN_ES.strip(), out)
        self.assertEqual([], report["lexical"])
        self.assertEqual([], report["reported"])

    def test_verbs_and_adjectives_are_reported_never_rewritten(self):
        text = "Una estrategia robusta e innovadora. Sumérgete en un ecosistema vibrante."
        out, report = self.clean(text)
        self.assertEqual(text, out)
        found = {h["find"] for h in report["reported"]}
        self.assertTrue({"robusto", "innovador", "sumergirse en", "ecosistema", "vibrante"} <= found, found)

    def test_a_dash_that_opens_a_line_is_dialogue_and_stays(self):
        out, _ = self.clean("—Hola, dijo él.\n—No obstante, nadie contestó.")
        self.assertEqual("—Hola, dijo él.\n—Aun así, nadie contestó.", out)

    def test_other_dashes_become_commas(self):
        out, _ = self.clean("Es un plan —el mejor— y funciona.")
        self.assertEqual("Es un plan, el mejor, y funciona.", out)

    def test_invisible_characters_are_stripped(self):
        out, report = self.clean("Hola​ a todos​.")
        self.assertEqual("Hola a todos.", out)
        self.assertEqual(2, sum(h["count"] for h in report["invisible"]))

    def test_urls_are_untouched(self):
        text = "Mira https://ejemplo.com/a—b y escríbeme a yo@ejemplo.com"
        self.assertEqual(text, self.clean(text)[0])

    def test_structures_are_flagged(self):
        _, report = self.clean("No es solo contenido, es conexión. No solo vendo, sino también enseño.")
        ids = {h["name"] for h in report["structures"]}
        self.assertTrue(any("No es solo" in n for n in ids), ids)
        self.assertTrue(any("No solo" in n for n in ids), ids)

    def test_cli_marks_spanish_in_json_and_english_is_unmarked(self):
        code, out, err = cli("ig-human/humanize.py", "-", "--json", stdin="Sin más preámbulos, aquí tienes el plan.")
        self.assertEqual("es", json.loads(out)["lang"])
        self.assertIn("language: Spanish", err)
        code, out, err = cli("ig-human/humanize.py", "-", "--json", stdin="Without further ado, here is the plan.")
        self.assertNotIn("lang", json.loads(out))

    def test_lang_flag_forces_the_language(self):
        code, out, err = cli("ig-human/humanize.py", "-", "--lang", "en", stdin="Sin más preámbulos, aquí tienes el plan.")
        self.assertEqual("Sin más preámbulos, aquí tienes el plan.\n", out)


class DetectSpanish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lex = detect.load_lexicon_es()

    def test_machine_text_flags_and_human_text_passes(self):
        _, slop, slop_verdict = detect.run_es(SLOP_ES, self.lex)
        _, human, human_verdict = detect.run_es(HUMAN_ES, self.lex)
        self.assertEqual("FLAGGED", slop_verdict)
        self.assertEqual("PASS", human_verdict)
        self.assertGreater(human, slop + 40)

    def test_plain_spaces_are_not_hard_spaces(self):
        """A copy of the English line once lost its special characters and counted every space."""
        results, _, _ = detect.run_es(HUMAN_ES, self.lex)
        self.assertIn("0 hard space", results["FINGERPRINT"][1])

    def test_real_hard_spaces_are_counted(self):
        results, _, _ = detect.run_es("Hola a todos ahora mismo.", self.lex)
        self.assertIn("3 hard space", results["FINGERPRINT"][1])

    def test_a_dash_that_opens_a_line_is_not_a_tell(self):
        results, _, _ = detect.run_es("—Hola, dijo él.\n—Nadie contestó.\n", self.lex)
        self.assertIn("0 em dash", results["FINGERPRINT"][1])
        results, _, _ = detect.run_es("Es un plan —el mejor— y funciona.\n", self.lex)
        self.assertIn("2 em dash", results["FINGERPRINT"][1])

    def test_voice_has_no_contraction_term(self):
        results, _, _ = detect.run_es(HUMAN_ES, self.lex)
        self.assertNotIn("contraction", results["VOICE"][1])

    def test_months_count_as_concrete_in_spanish(self):
        text = ("Empecé en marzo y publiqué hasta junio sin parar. En septiembre cambié todo el enfoque y me fue "
                "mejor que nunca con el nuevo plan que preparé durante el verano para mi propio negocio local.")
        results, _, _ = detect.run_es(text, self.lex)
        self.assertNotIn("0 concrete markers", results["SPECIFICITY"][1])

    def test_cli_marks_spanish_and_says_it_is_a_first_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "borrador.txt")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(HUMAN_ES)
            code, out, err = cli("ig-human/detect.py", p, "--json")
        self.assertEqual("es", json.loads(out)["lang"])
        self.assertIn("first version", err)


class HooksFileSpanish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(path("ig-reel/hooks.json"), encoding="utf-8") as fh:
            cls.en = json.load(fh)
        with open(path("ig-reel/hooks.es.json"), encoding="utf-8") as fh:
            cls.es = json.load(fh)

    def test_same_ids_same_order_as_english(self):
        self.assertEqual([h["id"] for h in self.en["hooks"]], [h["id"] for h in self.es["hooks"]])
        self.assertEqual(self.en["classify_order"], self.es["classify_order"])
        self.assertEqual(len(self.en["rules"]), len(self.es["rules"]))

    def test_every_formula_keeps_the_english_fields(self):
        for h in self.es["hooks"]:
            with self.subTest(id=h["id"]):
                self.assertTrue(set(self.en["hooks"][0]) <= set(h))
                self.assertTrue(h["name_en"])
                self.assertEqual(self.en["hooks"][h["id"] - 1]["name"], h["name_en"])

    def test_every_pattern_compiles(self):
        for h in self.es["hooks"]:
            with self.subTest(id=h["id"]):
                re.compile(h["match"], re.IGNORECASE)

    def test_each_example_is_classified_as_itself(self):
        """Weak on purpose: the examples and the patterns were written together."""
        formulas = swipe.load_formulas_es(path("ig-reel/hooks.es.json"))
        for h in self.es["hooks"]:
            with self.subTest(id=h["id"]):
                self.assertEqual(h["id"], swipe.classify_es(h["example"], formulas)[0])

    def test_patterns_work_without_accents(self):
        formulas = swipe.load_formulas_es(path("ig-reel/hooks.es.json"))
        self.assertEqual(3, swipe.classify_es("Nadie te cuenta que tus primeros 30 reels estan hechos para fracasar",
                                              formulas)[0])
        self.assertEqual(1, swipe.classify_es("Perdi 18.000 por una clausula que no lei", formulas)[0])


class SwipeSpanish(unittest.TestCase):
    TSV = ("cuenta\tseguidores\tmediana\tvistas\tgancho\n"
           "@a\t50000\t11000\t412.000\tNadie te cuenta que tus primeros 30 reels están hechos para fracasar\n"
           "@b\t4000\t3000\t180000\tRoba esta secuencia de seguimiento, me llevó dos años\n"
           "@c\t9000\t2500\t30000\tPerdí 18.000 € por una cláusula que no leí\n"
           "@d\t1500\t800\t900\tDeja de publicar a diario\n"
           "@e\t30000\t5000\t90000\tI lost $18,000 because of one missing contract\n")

    def rows(self, tsv=None):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "capturados.tsv")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(tsv or self.TSV)
            return swipe.read_rows(p)

    def test_spanish_headers_and_thousands_separators(self):
        rows = self.rows()
        self.assertEqual(5, len(rows))
        first = rows[0]
        self.assertEqual((412000, 50000, 11000), (first["views"], first["followers"], first["median"]))

    def analysed(self):
        formulas = swipe.load_formulas(path("ig-reel/hooks.json"))
        formulas_es = swipe.load_formulas_es(path("ig-reel/hooks.es.json"))
        return {r["account"]: r for r in swipe.analyse(self.rows(), formulas, formulas_es)["reels"]}

    def test_each_hook_is_named_with_its_own_languages_formulas(self):
        by = self.analysed()
        self.assertEqual((3, "Nobody Tells You", "es"), (by["@a"]["formula_id"], by["@a"]["formula"], by["@a"]["lang"]))
        self.assertEqual(9, by["@b"]["formula_id"])
        self.assertEqual(1, by["@c"]["formula_id"])
        self.assertEqual(2, by["@d"]["formula_id"])
        self.assertEqual(1, by["@e"]["formula_id"])

    def test_the_english_formula_name_is_kept_and_the_spanish_one_added(self):
        by = self.analysed()
        self.assertEqual("Nadie te lo cuenta", by["@a"]["formula_es"])
        self.assertNotIn("formula_es", by["@e"])

    def test_english_rows_carry_no_language_key(self):
        self.assertNotIn("lang", self.analysed()["@e"])

    def test_accented_words_are_counted_whole(self):
        by = self.analysed()
        self.assertEqual(5, by["@d"]["words"])
        self.assertEqual(8, by["@c"]["words"])      # "18.000" is one number, and the euro sign is not a word

    def test_forcing_english_skips_the_spanish_path(self):
        formulas = swipe.load_formulas(path("ig-reel/hooks.json"))
        a = swipe.analyse(self.rows(), formulas, None, "en")
        self.assertTrue(all("lang" not in r for r in a["reels"]))

    def test_cli_mixed_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "capturados.tsv")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(self.TSV)
            code, out, err = cli("ig-viral/swipe.py", p, "--json")
        self.assertEqual(0, code)
        reels = json.loads(out)["reels"]
        self.assertEqual({"es": 4, "en": 1}, {k: sum(1 for r in reels if r.get("lang", "en") == k) for k in ("es", "en")})
        self.assertIn("4 Spanish hook(s) of 5", err)


if __name__ == "__main__":
    unittest.main()
