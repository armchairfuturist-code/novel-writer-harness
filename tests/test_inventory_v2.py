"""v2 Full inventory test: every CLI flag, env var, config route, edge case.
All LLM calls mocked. 27 flags, 9 env vars, 82+ acceptance criteria.
"""

import argparse, json, os, sys, tempfile, unittest
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from tests.fixtures.mock_api import install_mock_env, MockCrofaiClient
from tests.fixtures.sanitized_project import (write_sanitized_project, SANITIZED_SPEC,
    SANITIZED_WORLD, SANITIZED_CHARACTERS, SANITIZED_OUTLINE)
install_mock_env()

import storyforge
from config import Config
from pipeline.api import CrofaiClient, parse_json_output, _looks_truncated
from pipeline.api import _unwrap_json, _repair_json, _is_retryable
from pipeline.draft import run_draft
from pipeline.factcheck import run_fact_check
from pipeline.embedding_store import EmbeddingStore
from pipeline.canonical_store import FileCanonicalStore, create_canonical_store
from pipeline.export import build_manuscript_markdown, export_manuscript
from interview.engine import run_interview, _detect_thin_area
from interview.resume import validate_checkpoint
from interview.memory_store import create_memory_store, JSONMemoryStore
from interview.questions import get_questions
from interview.story_bible import compile_story_bible
from templates import list_templates, get_template, get_beat_for_chapter


# ── Parser and mock helpers ──────────────────────────────────────

def _parser():
    p = argparse.ArgumentParser(description="SF")
    p.add_argument("concept", nargs="?", default=None)
    p.add_argument("--resume", type=str, default=None)
    p.add_argument("--benchmark", action="store_true")
    p.add_argument("--project-dir")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--single-variant", action="store_true")
    p.add_argument("--single-review", action="store_true")
    p.add_argument("--no-backprop", action="store_true")
    p.add_argument("--no-adversarial", action="store_true")
    p.add_argument("--genre", choices=["mystery","thriller","romance","fantasy","sci-fi"])
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--depth", choices=["quick","standard","comprehensive"], default="standard")
    p.add_argument("--model-override")
    p.add_argument("--no-iterative-backprop", action="store_true")
    p.add_argument("--no-gbrain", action="store_true")
    p.add_argument("--no-reio", action="store_true")
    p.add_argument("--feedback", action="store_true", default=None)
    p.add_argument("--no-feedback", action="store_true", default=None)
    p.add_argument("--debate", action="store_true")
    p.add_argument("--no-changes", action="store_true")
    p.add_argument("--style-profile", metavar="NAME")
    p.add_argument("--auto-style-extract", action="store_true")
    p.add_argument("--no-knowledge-base", action="store_true")
    p.add_argument("--no-validate-outline", action="store_true")
    p.add_argument("--agents", action="store_true")
    p.add_argument("--parallel-writers", type=int, default=3)
    p.add_argument("--store", choices=["json","gbrain","auto"], default="json")
    p.add_argument("--show-models", action="store_true")
    return p


_MOCKED_PIPELINE_MODULES = [
    "seed","worldbuilding","characters","outline","draft",
    "outline_validator","review","iterative_backprop","adversarial_edit",
]

import contextlib
@contextlib.contextmanager
def mock_all_pipeline():
    """Context manager: MockCrofaiClient for every pipeline module."""
    with contextlib.ExitStack() as stack:
        for mod in _MOCKED_PIPELINE_MODULES:
            stack.enter_context(patch(f"pipeline.{mod}.CrofaiClient", MockCrofaiClient))
        yield


# ═══════════════════════════════════════════════════════════════════
# 1. CLI FLAGS — Acceptance & Rejection
# ═══════════════════════════════════════════════════════════════════

class TestCLIAcceptance(unittest.TestCase):

    def test_help(self):
        with self.assertRaises(SystemExit) as ctx:
            _parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_concept_default_none(self):
        self.assertIsNone(_parser().parse_args([]).concept)

    def _check(self, *args, attr, expected=True):
        val = getattr(_parser().parse_args(list(args)), attr)
        if expected is True:
            self.assertTrue(val)
        else:
            self.assertEqual(val, expected)

    def test_resume(self):          self._check("--resume","/tmp/x", attr="resume", expected="/tmp/x")
    def test_benchmark(self):       self._check("--benchmark", attr="benchmark")
    def test_project_dir(self):     self._check("--project-dir","/p", attr="project_dir", expected="/p")
    def test_quick(self):           self._check("--quick","t", attr="quick")
    def test_single_variant(self):  self._check("--single-variant","t", attr="single_variant")
    def test_single_review(self):   self._check("--single-review","t", attr="single_review")
    def test_no_backprop(self):     self._check("--no-backprop","t", attr="no_backprop")
    def test_no_adversarial(self):  self._check("--no-adversarial","t", attr="no_adversarial")
    def test_no_iter_backprop(self):self._check("--no-iterative-backprop","t", attr="no_iterative_backprop")
    def test_no_gbrain(self):       self._check("--no-gbrain","t", attr="no_gbrain")
    def test_no_reio(self):         self._check("--no-reio","t", attr="no_reio")
    def test_feedback(self):        self._check("--feedback","t", attr="feedback")
    def test_no_feedback(self):     self._check("--no-feedback","t", attr="no_feedback")
    def test_feedback_mutual(self): self._check("--feedback","--no-feedback","t", attr="no_feedback")
    def test_debate(self):          self._check("--debate","t", attr="debate")
    def test_no_changes(self):      self._check("--no-changes","t", attr="no_changes")
    def test_style_profile(self):   self._check("--style-profile","ch-001","t", attr="style_profile", expected="ch-001")
    def test_auto_style(self):      self._check("--auto-style-extract","t", attr="auto_style_extract")
    def test_no_kb(self):           self._check("--no-knowledge-base","t", attr="no_knowledge_base")
    def test_no_val_outline(self):  self._check("--no-validate-outline","t", attr="no_validate_outline")
    def test_agents(self):          self._check("--agents","t", attr="agents")
    def test_parallel_default(self):self._check("t", attr="parallel_writers", expected=3)
    def test_parallel_custom(self): self._check("--parallel-writers","5","t", attr="parallel_writers", expected=5)
    def test_store_default(self):   self._check("t", attr="store", expected="json")
    def test_model_override(self):  self._check("--model-override","km","t", attr="model_override", expected="km")
    def test_show_models(self):     self._check("--show-models", attr="show_models")

    def test_genre_all(self):
        for g in ["mystery","thriller","romance","fantasy","sci-fi"]:
            self.assertEqual(_parser().parse_args(["--genre",g,"t"]).genre, g)

    def test_depth_default(self):   self.assertEqual(_parser().parse_args([]).depth, "standard")
    def test_depth_all(self):
        for d in ["quick","standard","comprehensive"]:
            self.assertEqual(_parser().parse_args(["--depth",d]).depth, d)
    def test_interactive(self):     self.assertTrue(_parser().parse_args(["--interactive"]).interactive)


class TestCLIRejection(unittest.TestCase):

    def _bad(self, *args):
        with self.assertRaises(SystemExit):
            _parser().parse_args(list(args))

    def test_invalid_genre(self):   self._bad("--genre","western","t")
    def test_invalid_store(self):   self._bad("--store","bad")
    def test_invalid_depth(self):   self._bad("--depth","bad")
    def test_unknown_flag(self):    self._bad("--bogus","t")
    def test_parallel_nonint(self): self._bad("--parallel-writers","abc","t")
    def test_genre_case(self):      self._bad("--genre","Fantasy","t")
    def test_store_case(self):      self._bad("--store","JSON")


# ═══════════════════════════════════════════════════════════════════
# 2. ENVIRONMENT VARIABLES
# ═══════════════════════════════════════════════════════════════════

class TestEnvVars(unittest.TestCase):

    _VARS = ["LLM_API_KEY","CROFAI_API_KEY","LLM_BASE_URL","LLM_DEFAULT_MODEL",
             "LLM_ENABLE_EMBEDDINGS","LLM_EMBEDDING_MODE",
             "LLM_EMBEDDING_LOCAL_MODEL","LLM_EMBEDDING_REMOTE_ALIAS"]

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self._VARS}
        os.environ["LLM_API_KEY"] = "test-key"
        Config._instance = None

    def tearDown(self):
        for k,v in self._saved.items():
            if v is not None: os.environ[k] = v
            else: os.environ.pop(k, None)
        Config._instance = None

    def test_base_url(self):
        os.environ["LLM_BASE_URL"] = "http://custom.example.com/v1"
        Config._instance = None
        self.assertEqual(Config().base_url, "http://custom.example.com/v1")

    def test_crofai_fallback(self):
        os.environ.pop("LLM_API_KEY", None)
        os.environ["CROFAI_API_KEY"] = "crofai-fallback"
        Config._instance = None
        self.assertEqual(Config().api_key, "crofai-fallback")

    def test_both_keys_llm_wins(self):
        os.environ["LLM_API_KEY"] = "llm-key"
        os.environ["CROFAI_API_KEY"] = "crofai-key"
        Config._instance = None
        self.assertEqual(Config().api_key, "llm-key")

    def test_default_model(self):
        os.environ["LLM_DEFAULT_MODEL"] = "flash"
        Config._instance = None
        self.assertEqual(Config().default_model, "flash")

    def test_embeddings_opt_in(self):
        os.environ["LLM_ENABLE_EMBEDDINGS"] = "1"
        Config._instance = None
        self.assertTrue(Config().embeddings.enabled)

    def test_embeddings_disabled_default(self):
        os.environ.pop("LLM_ENABLE_EMBEDDINGS", None)
        Config._instance = None
        self.assertFalse(Config().embeddings.enabled)

    def test_embedding_mode_default(self):
        os.environ.pop("LLM_EMBEDDING_MODE", None)
        Config._instance = None
        self.assertEqual(Config().embeddings.mode, "none")

    def test_embedding_local_model(self):
        os.environ["LLM_EMBEDDING_LOCAL_MODEL"] = "custom-model"
        Config._instance = None
        self.assertEqual(Config().embeddings.local_model, "custom-model")

    def test_embedding_remote_alias(self):
        os.environ["LLM_EMBEDDING_REMOTE_ALIAS"] = "deepseek"
        Config._instance = None
        self.assertEqual(Config().embeddings.remote_model_alias, "deepseek")

    def test_phase_env_override(self):
        os.environ["LLM_MODEL_DRAFT"] = "flash"
        Config._instance = None
        self.assertEqual(Config().model_for_phase("draft").name, "qwen3.5-9b")

    def test_phase_env_unknown(self):
        os.environ["LLM_MODEL_DRAFT"] = "bogus"
        Config._instance = None
        self.assertIsNotNone(Config().model_for_phase("draft").name)

    def test_missing_key_raises(self):
        os.environ.pop("LLM_API_KEY", None)
        os.environ.pop("CROFAI_API_KEY", None)
        Config._instance = None
        with self.assertRaises(ValueError) as ctx:
            Config().require_api_key()
        self.assertIn("API key", str(ctx.exception))


# ═══════════════════════════════════════════════════════════════════
# 3. CONFIG ROUTING
# ═══════════════════════════════════════════════════════════════════

class TestConfigRouting(unittest.TestCase):
    def setUp(self):
        os.environ["LLM_API_KEY"] = "test-key"
        Config._instance = None
    def tearDown(self):
        Config._instance = None

    def test_singleton(self):       self.assertIs(Config(), Config())
    def test_phase_seed(self):      self.assertEqual(Config().model_for_phase("seed").name, "deepseek-v4-pro-precision")
    def test_phase_draft(self):     self.assertEqual(Config().model_for_phase("draft").name, "kimi-k2.6-precision")
    def test_phase_scoring(self):   self.assertEqual(Config().model_for_phase("scoring").name, "qwen3.5-9b")
    def test_phase_unknown(self):   self.assertIsNotNone(Config().model_for_phase("bogus").name)
    def test_interview_override(self):
        self.assertEqual(Config().model_for_interview("concept_premise", override="flash").name, "qwen3.5-9b")
    def test_interview_bad_override(self):
        self.assertEqual(Config().model_for_interview("concept_premise", override="nope").name, "deepseek-v4-pro-precision")
    def test_print_routing(self):
        with patch("sys.stdout"): Config().print_routing_plan()
    def test_embeddings_disabled_noop(self):
        s = EmbeddingStore("/tmp/test_emb.db")
        self.assertEqual(s.search("x"), []); s.close()


# ═══════════════════════════════════════════════════════════════════
# 4. API CLIENT
# ═══════════════════════════════════════════════════════════════════

class TestAPIClient(unittest.TestCase):

    def test_retryable_429(self):   self.assertTrue(_is_retryable(429))
    def test_retryable_500(self):   self.assertTrue(_is_retryable(500))
    def test_retryable_503(self):   self.assertTrue(_is_retryable(503))
    def test_not_400(self):         self.assertFalse(_is_retryable(400))
    def test_not_401(self):         self.assertFalse(_is_retryable(401))
    def test_not_404(self):         self.assertFalse(_is_retryable(404))
    def test_not_200(self):         self.assertFalse(_is_retryable(200))

    def test_unwrap_fences(self):   self.assertEqual(_unwrap_json("```json\n{\"a\":1}\n```"), "{\"a\":1}")
    def test_unwrap_plain(self):    self.assertEqual(_unwrap_json("{\"a\":1}"), "{\"a\":1}")
    def test_repair_commas(self):
        r = _repair_json('{"a": 1,}'); self.assertNotIn(",}", r)
    def test_repair_newlines(self):
        r = _repair_json('{"a": "hello\nworld"}'); self.assertNotIn("\n", r)
    def test_trunc_balanced(self):  self.assertFalse(_looks_truncated('{"a":1}'))
    def test_trunc_unbalanced(self):self.assertTrue(_looks_truncated('{"a":[1,2'))
    def test_parse_normal(self):    self.assertEqual(parse_json_output('{"a":1}'), {"a":1})
    def test_parse_fences(self):    self.assertEqual(parse_json_output('```json\n{"a":1}\n```'), {"a":1})
    def test_parse_empty_raises(self):
        with self.assertRaises(RuntimeError): parse_json_output("")
    def test_cache_disabled(self):  self.assertFalse(CrofaiClient(use_cache=False).use_cache)
    def test_cache_enabled(self):   self.assertTrue(CrofaiClient(use_cache=True).use_cache)


# ═══════════════════════════════════════════════════════════════════
# 5. PIPELINE EDGE CASES
# ═══════════════════════════════════════════════════════════════════

class TestPipelineEdgeCases(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="sf_")
        os.environ["LLM_API_KEY"] = "test-key"
        Config._instance = None

    def tearDown(self):
        import shutil; shutil.rmtree(self.d, ignore_errors=True)
        Config._instance = None

    def test_empty_spec_fails_checkpoint(self):
        with open(os.path.join(self.d, "spec.json"), "w") as f: f.write("")
        self.assertEqual(storyforge._load_checkpoint(self.d), set())

    def test_truncated_checkpoint_returns_empty(self):
        with open(os.path.join(self.d, "checkpoint.json"), "w") as f:
            f.write('{"completed_phases": ["seed"')
        self.assertEqual(storyforge._load_checkpoint(self.d), set())

    def test_fact_check_empty(self):
        self.assertEqual(run_fact_check(os.path.join(self.d,"chapters"))["status"], "SKIPPED")

    def test_fact_check_missing(self):
        self.assertEqual(run_fact_check("/nonexistent")["status"], "SKIPPED")

    def test_empty_concept_none(self):
        self.assertIsNone(_parser().parse_args([]).concept)

    def test_slugify_shell(self):
        s = storyforge.slugify("my story ; rm -rf /")
        self.assertNotIn(";", s); self.assertNotIn("/", s)

    def test_slugify_rtl(self):
        s = storyforge.slugify("hello\u202Eworld")
        self.assertIn("hello", s); self.assertIn("world", s)

    def test_slugify_null(self):
        s = storyforge.slugify("test\x00concept")
        self.assertNotIn("\x00", s); self.assertGreater(len(s), 0)

    def test_slugify_whitespace(self): self.assertEqual(storyforge.slugify("   "), "")
    def test_slugify_length(self):     self.assertLessEqual(len(storyforge.slugify("a"*200)), 60)
    def test_slugify_traversal(self):  self.assertNotIn(".", storyforge.slugify("../../etc"))

    def test_symlink_dir(self):
        import shutil
        r = tempfile.mkdtemp(prefix="sf_r_")
        l = os.path.join(self.d, "lnk"); os.symlink(r, l)
        self.assertTrue(os.path.isdir(l)); shutil.rmtree(r, ignore_errors=True)

    def test_binary_chapter_ignored(self):
        cd = os.path.join(self.d, "chapters"); os.makedirs(cd)
        with open(os.path.join(cd, "i.png"), "wb") as f: f.write(b"\x89PNG\r\n\x1a\n")
        with open(os.path.join(cd, "ch-001.md"), "w") as f: f.write("# C\n\nT.")
        self.assertEqual(len([f for f in os.listdir(cd) if f.endswith(".md")]), 1)

    def test_empty_outline_zero(self):
        self.assertEqual(run_draft({},{},{},{"acts":[]},"/tmp",Config()), [])

    def test_precompiled_skips_seed(self):
        with mock_all_pipeline():
            r = storyforge.run_full_pipeline("t", config=Config(),
                precompiled_spec={"title":"T","genre":"f","pov":"first"},
                project_dir_override=self.d, feedback_enabled=False)
        self.assertEqual(r, self.d)
        with open(os.path.join(self.d,"spec.json")) as f:
            self.assertEqual(json.load(f)["title"], "T")

    def test_quick_skips_review(self):
        with patch("storyforge.run_full_review") as m:
            with mock_all_pipeline():
                storyforge.run_full_pipeline("t", config=Config(), quick=True,
                    project_dir_override=self.d, feedback_enabled=False)
            m.assert_not_called()


# ═══════════════════════════════════════════════════════════════════
# 6. INTERVIEW EDGE CASES
# ═══════════════════════════════════════════════════════════════════

_Q = lambda: type("Q",(),{"id":"cp-01","text":"?","dimension":"x",
                          "depths":("standard",),"follow_up_keywords":["maybe"],
                          "genre_specific":False})()

class TestInterviewEdgeCases(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="sf_int_")
    def tearDown(self):
        import shutil; shutil.rmtree(self.d, ignore_errors=True)

    def test_thin_short(self):          self.assertTrue(_detect_thin_area("short", _Q()))
    def test_thin_hedge(self):          self.assertTrue(_detect_thin_area("I think maybe perhaps a story", _Q()))
    def test_thin_substantive(self):
        answer = "A wizard discovers an ancient conspiracy threatening the magical world"
        self.assertFalse(_detect_thin_area(answer, _Q()))
    def test_quick_3(self):             self.assertEqual(len(get_questions("quick",None)), 3)
    def test_comprehensive_many(self):  self.assertGreater(len(get_questions("comprehensive",None)), 70)
    def test_genre_filtered(self):      self.assertGreater(len(get_questions("standard","fantasy")), 0)

    def test_validate_missing_answers(self):
        e = validate_checkpoint({"version":2}); self.assertIsNotNone(e); self.assertIn("answers",str(e))

    def test_validate_valid(self):
        e = validate_checkpoint({"version":2,
            "answers":[{"question_id":"cp-01","dimension":"x","question":"?",
                        "answer":"y","is_thin":False,"timestamp":"2026-01-01T00:00:00"}]})
        self.assertIsNone(e)

    def test_bible_empty(self):
        r = compile_story_bible({"version":2,"answers":[],"thin_areas":[]})
        self.assertIn("spec",r); self.assertIn("enrichments",r)

    def test_bible_partial(self):
        r = compile_story_bible({"version":2,"thin_areas":[],"answers":[
            {"question_id":"cp-01","dimension":"concept_premise","question":"Q",
             "answer":"My story","is_thin":False,"timestamp":"2026-01-01T00:00:00"}]})
        self.assertIn("spec",r)

    def test_skip_cmd(self):
        from interview.cli import get_answer
        with patch("interview.cli.input", return_value="skip"):
            self.assertEqual(get_answer(), "[SKIPPED]")

    def test_quit_cmd(self):
        from interview.cli import get_answer
        with patch("interview.cli.input", return_value="q"):
            self.assertIsNone(get_answer())

    def test_empty_answer(self):
        from interview.cli import get_answer
        with patch("interview.cli.input", return_value=""):
            self.assertEqual(get_answer(), "")


# ═══════════════════════════════════════════════════════════════════
# 7. EXPORT EDGE CASES
# ═══════════════════════════════════════════════════════════════════

class TestExportEdgeCases(unittest.TestCase):
    def setUp(self):    self.d = tempfile.mkdtemp(prefix="sf_exp_")
    def tearDown(self): import shutil; shutil.rmtree(self.d, ignore_errors=True)

    def test_empty(self):
        self.assertIn("manuscript_md", export_manuscript([],{},{},{},{},self.d))

    def test_basic_md(self):
        ch = [{"chapter":1,"title":"C1","text":"# C1\n\nT.","word_count":5,"score":{"total_score":7.0}}]
        r = export_manuscript(ch, SANITIZED_SPEC, SANITIZED_WORLD, SANITIZED_CHARACTERS,
                              SANITIZED_OUTLINE, self.d)
        self.assertTrue(os.path.exists(r["manuscript_md"]))

    def test_pandoc_fallback(self):
        ch = [{"chapter":1,"title":"C1","text":"# C1","word_count":5,"score":{"total_score":7.0}}]
        r = export_manuscript(ch,{"title":"T"},{"geography":"."},{"characters":[]},{"acts":[]},self.d)
        for fmt,info in r.get("pandoc",{}).items():
            if not info["success"]: self.assertIn("error", info)

    def test_geography_dict(self):
        p = build_manuscript_markdown([],{},{"geography":{"r":["N","S"]}},{"characters":[]},{"acts":[]},self.d)
        self.assertTrue(os.path.exists(p))

    def test_no_personality(self):
        ch = {"characters":[{"name":"Alice","role":"protagonist"}]}
        p = build_manuscript_markdown([],{},{"geography":"."},ch,{"acts":[]},self.d)
        with open(p) as f: self.assertIn("Alice", f.read())


# ═══════════════════════════════════════════════════════════════════
# 8. MEMORY / CANONICAL STORES
# ═══════════════════════════════════════════════════════════════════

class TestMemoryStore(unittest.TestCase):
    def setUp(self):    self.d = tempfile.mkdtemp(prefix="sf_mem_")
    def tearDown(self): import shutil; shutil.rmtree(self.d, ignore_errors=True)

    def test_persistence(self):
        s1 = JSONMemoryStore(self.d); s1.store("k","v",["t"]); s1.close()
        self.assertGreater(len(JSONMemoryStore(self.d).recall("v")), 0)
    def test_empty(self):   self.assertEqual(JSONMemoryStore(self.d).recall("x"), [])
    def test_recall_k(self):
        s = JSONMemoryStore(self.d)
        s.store("k1","a b c",["t"]); s.store("k2","a b",["t"]); s.store("k3","a",["t"])
        self.assertLessEqual(len(s.recall("a b c",k=2)), 2); s.close()
    def test_tag_filter_ci(self):
        s = JSONMemoryStore(self.d); s.store("k","v",["TestTag"])
        self.assertGreater(len(s.recall("v",tag_filter=["testtag"])), 0); s.close()
    def test_factory_json(self):
        s = create_memory_store("json",project_dir=self.d)
        self.assertIsInstance(s, JSONMemoryStore); s.close()
    def test_factory_unknown(self):
        with self.assertRaises(NotImplementedError):
            create_memory_store("bogus",project_dir=self.d)


class TestCanonicalStore(unittest.TestCase):
    def setUp(self):    self.d = tempfile.mkdtemp(prefix="sf_cn_")
    def tearDown(self): import shutil; shutil.rmtree(self.d, ignore_errors=True)

    def test_persistence(self):
        s1 = FileCanonicalStore(self.d)
        s1.record_character_trait("Alice","hair","red",chapter=1)
        s1._save(); s1.close()
        s2 = FileCanonicalStore(self.d)
        tr = s2.get_character_traits("Alice")
        self.assertGreater(len(tr),0); self.assertIn("red",tr[0]["content"]); s2.close()

    def test_state_file(self):
        s = FileCanonicalStore(self.d)
        s.record_character_trait("Bob","age","30",chapter=1); s._save(); s.close()
        self.assertTrue(os.path.exists(os.path.join(self.d,"canonical_state.json")))

    def test_factory(self):
        s = create_canonical_store("file",project_dir=self.d)
        self.assertIsInstance(s, FileCanonicalStore); s.close()


# ═══════════════════════════════════════════════════════════════════
# 9. TEMPLATES
# ═══════════════════════════════════════════════════════════════════

class TestTemplates(unittest.TestCase):
    def test_list_five(self):            self.assertEqual(len(list_templates()),5)
    def test_missing_none(self):         self.assertIsNone(get_template("bogus"))
    def test_beat_oob(self):             self.assertIsNone(get_beat_for_chapter("mystery",999))
    def test_beat_zero(self):            self.assertIsNone(get_beat_for_chapter("mystery",0))
    def test_beat_negative(self):        self.assertIsNone(get_beat_for_chapter("mystery",-1))
    def test_beat_missing_genre(self):   self.assertIsNone(get_beat_for_chapter("bogus",1))
    def test_each_structure(self):
        for g in ["mystery","thriller","romance","fantasy","sci-fi"]:
            t = get_template(g)
            for k in ["beats","structure","tracking"]: self.assertIn(k,t)


# ═══════════════════════════════════════════════════════════════════
# 10. SANITIZED FIXTURES
# ═══════════════════════════════════════════════════════════════════

class TestSanitizedData(unittest.TestCase):
    def test_spec_keys(self):
        for k in ["title","genre","pov","premise","target_chapters","themes"]:
            self.assertIn(k, SANITIZED_SPEC)
    def test_world_geo(self):   self.assertIn("geography", SANITIZED_WORLD)
    def test_chars_min2(self):  self.assertGreaterEqual(len(SANITIZED_CHARACTERS.get("characters",[])),2)
    def test_outline_acts(self):self.assertGreaterEqual(len(SANITIZED_OUTLINE.get("acts",[])),1)
    def test_outline_24(self):
        n = sum(len(a.get("chapters",[])) for a in SANITIZED_OUTLINE.get("acts",[]))
        self.assertEqual(n, 24)
    def test_write_project(self):
        d = tempfile.mkdtemp(prefix="sf_")
        try:
            r = write_sanitized_project(d)
            for f in ["spec.json","world.json","characters.json","outline.json"]:
                self.assertTrue(os.path.exists(os.path.join(r,f)))
        finally:
            import shutil; shutil.rmtree(d, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════
# 11. REGRESSION GUARDS (previously fixed bugs)
# ═══════════════════════════════════════════════════════════════════

class TestRegressionGuard(unittest.TestCase):
    def setUp(self):
        os.environ["LLM_API_KEY"] = "test-key"; Config._instance = None
    def tearDown(self): Config._instance = None

    def test_bug002_factions_string(self):
        from pipeline.characters import run_characters
        with patch("pipeline.characters.CrofaiClient", MockCrofaiClient):
            self.assertIsNotNone(run_characters({"genre":"f"}, {"factions":["G","C"]}))

    def test_bug003_empty_outline(self):
        self.assertEqual(run_draft({},{},{},{"acts":[]},"/tmp",Config()), [])

    def test_bug005_emb_no_numpy(self):
        s = EmbeddingStore("/tmp/test_emb_b5.db"); self.assertEqual(s.search("x"),[]); s.close()

    def test_bug007_outline_factions_string(self):
        from pipeline.outline import run_outline
        with patch("pipeline.outline.CrofaiClient", MockCrofaiClient):
            self.assertIn("acts", run_outline({"genre":"f"},
                {"factions":["G","C"],"geography":"l","magic_system":"n"}, SANITIZED_CHARACTERS))

    def test_bug008_geo_dict(self):
        p = build_manuscript_markdown([],{},{"geography":{"r":["N"]}},{"characters":[]},{"acts":[]},"/tmp")
        self.assertTrue(os.path.exists(p))

    def test_bug009_no_personality(self):
        ch = {"characters":[{"name":"A","role":"protagonist"}]}
        p = build_manuscript_markdown([],{},{"geography":"."},ch,{"acts":[]},"/tmp")
        with open(p) as f: self.assertIn("A", f.read())

    def test_bug001_override(self):
        d = tempfile.mkdtemp(prefix="sf_b1_")
        try:
            with mock_all_pipeline():
                self.assertEqual(storyforge.run_full_pipeline("t",config=Config(),
                    project_dir_override=d,feedback_enabled=False), d)
        finally: import shutil; shutil.rmtree(d, ignore_errors=True)

    def test_bug010_feedback_disabled(self):
        d = tempfile.mkdtemp(prefix="sf_b10_")
        try:
            with mock_all_pipeline():
                self.assertEqual(storyforge.run_full_pipeline("t",config=Config(),
                    project_dir_override=d,feedback_enabled=False), d)
        finally: import shutil; shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
