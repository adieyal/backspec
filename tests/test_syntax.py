"""Optional syntax support: symbols from a parser decide where files are cut and where an
observation sits. With no parser, or `--text-only`, backspec reads everything as text, as before.

Tests that need the real parser are skipped when the package is absent; the rest use a fake
`SyntaxPort` built on the standard library's `ast`, so they run either way."""
import ast
import os
import sys

import pytest
from test_pipeline import assess, assign, fake, observe, orient, repo, synthesise

from backspec import Config, extract, to_markdown
from backspec.host import composition
from backspec.host.adapters.fake import FakeLLM
from backspec.host.adapters.treesitter import TreeSitterSyntax
from backspec.host.cli import app
from backspec.modules.evidence.domain import Symbol, enclosing_symbol, split_file
from backspec.modules.evidence.facade import EvidenceFacade


class AstSyntax:
    """A SyntaxPort for Python files, from `ast`. Anything else, or a syntax error, is None."""

    def symbols(self, path, text):
        if not path.endswith(".py"):
            return None
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return None
        found = []

        def walk(node, prefix, parent):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.ClassDef)):
                    name = prefix + child.name
                    kind = "class" if isinstance(child, ast.ClassDef) else "method" if parent == "class" else "function"
                    found.append(Symbol(name, kind, child.lineno, child.end_lineno))
                    walk(child, name + ".", kind)
                else:
                    walk(child, prefix, parent)
        walk(tree, "", "")
        return found


class Broken:
    def symbols(self, path, text):
        raise RuntimeError("the parser fell over")


def use(monkeypatch, port):
    """Make `Config(syntax=True)` find `port`, as if its package were installed."""
    class Loader:
        @staticmethod
        def load():
            return port
    monkeypatch.setattr(composition, "TreeSitterSyntax", Loader)


def real():
    pytest.importorskip("tree_sitter_language_pack")
    if os.environ.get("BACKSPEC_NO_TREESITTER"):
        pytest.skip("BACKSPEC_NO_TREESITTER switches the adapter off")
    adapter = TreeSitterSyntax.load()
    assert adapter is not None
    return adapter


def names(symbols):
    return [(s.name, s.kind, s.first_line, s.last_line) for s in symbols]


# the real parser

def test_symbols_of_a_small_python_file():
    text = "import os\n\n\n@cache\ndef top():\n    def inner():\n        pass\n    return inner\n\n\nclass Shop:\n    def buy(self):\n        pass\n"
    assert names(real().symbols("shop.py", text)) == [
        ("top", "function", 4, 8), ("top.inner", "function", 6, 7),
        ("Shop", "class", 11, 13), ("Shop.buy", "method", 12, 13)]


def test_symbols_of_a_small_typescript_file_with_a_method_in_a_class():
    text = "export class Cart {\n  add(item: string): void {\n    this.items.push(item);\n  }\n}\n\nfunction total(): number {\n  return 0;\n}\n"
    assert names(real().symbols("cart.ts", text)) == [
        ("Cart", "class", 1, 5), ("Cart.add", "method", 2, 4), ("total", "function", 7, 9)]


@pytest.mark.parametrize("path, text, expected", [
    ("a.js", "const f = () => {\n  return 1;\n};\nclass B { m() { return 2; } }\n", ["f", "B", "B.m"]),
    ("a.tsx", "function View() {\n  return <div/>;\n}\n", ["View"]),
    ("a.go", "package m\nfunc (s Shop) Buy() {\n}\nfunc Top() {\n}\n", ["Shop.Buy", "Top"]),
    ("A.java", "class A {\n  void m() {\n  }\n}\n", ["A", "A.m"]),
    ("a.rb", "class A\n  def m\n  end\nend\n", ["A", "A.m"]),
    ("a.rs", "fn top() {\n}\nstruct S;\nimpl S {\n  fn m(&self) {\n  }\n}\n", ["top", "S", "S", "S.m"]),
    ("a.cs", "namespace N {\n  class C {\n    void M() {\n    }\n  }\n}\n", ["C", "C.M"]),
    ("a.php", "<?php\nclass C {\n  function m() {\n  }\n}\nfunction f() {\n}\n", ["C", "C.m", "f"]),
])
def test_the_other_languages_have_a_grammar(path, text, expected):
    assert [s.name for s in real().symbols(path, text)] == expected


def test_a_file_with_a_syntax_error_still_yields_the_symbols_that_parse():
    found = real().symbols("bad.py", "def fine():\n    return 1\n\ndef broken(:\n    x =\n")
    assert found is not None and found[0].name == "fine" and (found[0].first_line, found[0].last_line) == (1, 2)


def test_an_unknown_extension_has_no_symbols():
    assert real().symbols("notes.txt", "def f():\n    pass\n") is None
    assert real().symbols("Makefile", "all:\n") is None


# the package is optional

def test_without_the_package_there_is_no_adapter(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)   # makes the import fail
    assert TreeSitterSyntax.load() is None


def test_the_environment_variable_also_switches_the_adapter_off(monkeypatch):
    monkeypatch.setenv("BACKSPEC_NO_TREESITTER", "1")
    assert TreeSitterSyntax.load() is None


# cutting a file

def long_file(functions=40, body=5):
    lines, symbols = [], []
    for n in range(functions):
        first = len(lines) + 1
        lines += [f"def f{n}(x):"] + [f"    x += {i}" for i in range(body)] + ["    return x"]
        symbols.append(Symbol(f"f{n}", "function", first, len(lines)))
        lines += ["", ""]
    return lines, symbols


def test_a_large_file_is_cut_between_functions_never_inside_one():
    lines, symbols = long_file()
    chunks = split_file("big.py", lines, 100, symbols)
    assert len(chunks) > 1
    assert [line for c in chunks for line in c.lines] == lines   # nothing lost, nothing repeated
    assert all(len(c.lines) <= 100 for c in chunks)
    for chunk, following in zip(chunks, chunks[1:]):
        assert following.first == chunk.last + 1
        assert not any(s.first_line <= chunk.last < s.last_line for s in symbols), "cut inside a function"
    for chunk in chunks:
        assert lines[chunk.first - 1] == chunk.lines[0]   # a line keeps its real number


def test_the_text_rule_alone_would_have_cut_inside_a_function():
    lines, symbols = long_file(functions=6, body=30)   # 33 lines each: a cut at 100 is inside the fourth
    plain = split_file("big.py", lines, 100)
    assert any(s.first_line <= c.last < s.last_line for c in plain[:-1] for s in symbols) or plain[0].last != 99
    smart = split_file("big.py", lines, 100, symbols)
    assert not any(s.first_line <= c.last < s.last_line for c in smart[:-1] for s in symbols)


def test_a_comment_above_a_function_goes_with_it():
    lines = ["def a():", "    pass", "", "# about b", "def b():", "    pass"]
    symbols = [Symbol("a", "function", 1, 2), Symbol("b", "function", 5, 6)]
    chunks = split_file("x.py", lines, 5, symbols)
    assert [c.first for c in chunks] == [1, 4]


def test_one_function_larger_than_the_limit_is_cut_by_the_text_rule():
    lines = ["def huge():"] + [f"    x = {i}" for i in range(250)] + ["", "def after():", "    pass"]
    symbols = [Symbol("huge", "function", 1, 251), Symbol("after", "function", 253, 254)]
    chunks = split_file("huge.py", lines, 100, symbols)
    assert all(len(c.lines) <= 100 for c in chunks) and len(chunks) >= 3
    assert [line for c in chunks for line in c.lines] == lines
    assert chunks[0].first == 1 and all(b.first == a.last + 1 for a, b in zip(chunks, chunks[1:]))


def test_with_the_real_parser_the_same_holds_for_a_python_file():
    lines, _ = long_file(functions=30)
    found = real().symbols("big.py", "\n".join(lines))
    chunks = split_file("big.py", lines, 120, found)
    assert [line for c in chunks for line in c.lines] == lines
    assert not any(s.first_line <= c.last < s.last_line for c in chunks[:-1] for s in found)


# the enclosing symbol

CLASS = [Symbol("Shop", "class", 1, 10), Symbol("Shop.buy", "method", 2, 4), Symbol("Shop.sell", "method", 6, 9),
         Symbol("helper", "function", 12, 14)]


def test_an_observation_gets_its_innermost_enclosing_symbol():
    assert enclosing_symbol(CLASS, 3, 3) == "Shop.buy"
    assert enclosing_symbol(CLASS, 12, 14) == "helper"


def test_a_range_over_two_methods_gets_the_class_and_over_two_functions_gets_none():
    assert enclosing_symbol(CLASS, 3, 7) == "Shop"
    assert enclosing_symbol(CLASS, 9, 13) is None
    assert enclosing_symbol(CLASS, 11, 11) is None and enclosing_symbol(None, 1, 1) is None


# through the pipeline

def test_the_symbol_is_set_in_code_and_copied_to_the_requirement_evidence(tmp_path, monkeypatch):
    use(monkeypatch, AstSyntax())
    result = extract(repo(tmp_path), Config(provider=fake(), use_cache=False))
    assert {o.path: o.symbol for o in result.observations} == {"src/policy.py": "can_adjust", "src/service.py": "adjust"}
    assert {e.path: e.symbol for e in result.requirements[0].evidence} == {
        "src/policy.py": "can_adjust", "src/service.py": "adjust"}
    text = to_markdown(result)
    assert "`src/policy.py:1-2` (can_adjust)" in text and "`src/service.py:2-3` (adjust)" in text


def test_the_symbol_is_not_part_of_the_observation_id(tmp_path, monkeypatch):
    root = repo(tmp_path)
    plain = extract(root, Config(provider=fake(), use_cache=False, syntax=False))
    use(monkeypatch, AstSyntax())
    with_syntax = extract(root, Config(provider=fake(), use_cache=False))
    assert [o.id for o in plain.observations] == [o.id for o in with_syntax.observations]
    assert all(o.symbol is None for o in plain.observations)


def test_no_symbol_is_shown_when_there_is_none(tmp_path):
    result = extract(repo(tmp_path), Config(provider=fake(), use_cache=False, syntax=False))
    assert "(can_adjust)" not in to_markdown(result)


def test_how_each_file_was_analysed_is_recorded(tmp_path, monkeypatch):
    use(monkeypatch, AstSyntax())
    root = repo(tmp_path)
    (root / "notes.txt").write_text("hello\n")
    result = extract(root, Config(provider=fake(), use_cache=False))
    modes = {f.path: f.analysis for f in result.coverage.files}
    assert modes["src/policy.py"] == modes["src/service.py"] == "syntax"
    assert modes["notes.txt"] == "text"   # an unknown extension is read as text
    assert (result.run.syntax_files, result.run.text_files) == (3, 1)   # util.py is Python too


def test_a_parser_that_raises_means_the_file_is_read_as_text(tmp_path, monkeypatch):
    use(monkeypatch, Broken())
    result = extract(repo(tmp_path), Config(provider=fake(), use_cache=False))
    assert {f.analysis for f in result.coverage.files} == {"text"}
    assert result.run.syntax_files == 0 and all(o.symbol is None for o in result.observations)


def test_a_file_that_does_not_parse_is_analysed_as_text(tmp_path, monkeypatch):
    use(monkeypatch, AstSyntax())
    root = repo(tmp_path)
    (root / "src" / "service.py").write_text("def adjust(:\n    raise NegativeStock()\n")
    result = extract(root, Config(provider=fake(), use_cache=False))
    modes = {f.path: f.analysis for f in result.coverage.files}
    assert modes["src/service.py"] == "text" and modes["src/policy.py"] == "syntax"


def test_text_only_and_a_missing_package_behave_as_before(tmp_path, monkeypatch):
    root = repo(tmp_path)
    text_only = extract(root, Config(provider=fake(), use_cache=False, syntax=False))
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    missing = extract(root, Config(provider=fake(), use_cache=False))
    for result in (text_only, missing):
        assert {f.analysis for f in result.coverage.files} == {"text"}
        assert (result.run.syntax_files, result.run.text_files) == (0, 3)
        assert all(o.symbol is None for o in result.observations)
        assert all(e.symbol is None for r in result.requirements for e in r.evidence)
    assert text_only.to_json() == missing.to_json()


def test_text_only_wins_even_when_the_parser_is_there(tmp_path, monkeypatch):
    use(monkeypatch, AstSyntax())
    result = extract(repo(tmp_path), Config(provider=fake(), use_cache=False, syntax=False))
    assert result.run.syntax_files == 0 and all(o.symbol is None for o in result.observations)


def test_the_text_only_flag_reaches_the_config(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    seen = []
    monkeypatch.setattr("backspec.host.cli.extract", lambda path, config, progress=None: seen.append(config.syntax) or (_ for _ in ()).throw(FileNotFoundError("stop")))
    monkeypatch.setattr("backspec.host.cli.ERRORS", (FileNotFoundError,))
    CliRunner().invoke(app, ["extract", str(tmp_path), "--text-only"])
    CliRunner().invoke(app, ["extract", str(tmp_path)])
    assert seen == [False, True]


def test_the_fingerprint_differs_between_the_two_modes():
    llm = fake()
    assert EvidenceFacade(llm).fingerprint() != EvidenceFacade(llm, syntax=AstSyntax()).fingerprint()
    assert EvidenceFacade(llm).fingerprint() == EvidenceFacade(llm, syntax=None).fingerprint()


def test_observations_made_the_other_way_are_not_reused(tmp_path, monkeypatch):
    root = repo(tmp_path)
    first = extract(root, Config(provider=fake(), use_cache=False, syntax=False))
    saved = tmp_path / "previous.json"
    saved.write_text(first.to_json())
    use(monkeypatch, AstSyntax())
    llm = fake()
    second = extract(root, Config(provider=llm, use_cache=False, previous=saved))
    assert "observe" in [r.stage for r in llm.requests] and second.run.reused_files == 0
    assert all(o.symbol for o in second.observations)


MOVING = "def a():\n    x = 1\n\ndef b():\n    y = 2\n"


def moving_llm():
    def see(prompt):
        return {"observations": [{"path": "m.py", "lines": [5, 5], "quote": "y = 2", "kind": "rule",
                                  "statement": "y is two."}], "none": []}
    return FakeLLM({"observe": see, "orient": orient, "assign": assign, "synthesise": synthesise, "assess": assess})


def test_a_carried_observations_symbol_is_recomputed_when_code_moves(tmp_path, monkeypatch):
    use(monkeypatch, AstSyntax())
    (tmp_path / "m.py").write_text(MOVING)
    first = extract(tmp_path, Config(provider=moving_llm(), use_cache=False))
    assert [(o.lines, o.symbol) for o in first.observations] == [((5, 5), "b")]
    saved = tmp_path / "previous.json"
    saved.write_text(first.to_json())
    (tmp_path / "m.py").write_text(MOVING.replace("def b():\n", ""))   # `y = 2` now sits in a()
    second = extract(tmp_path, Config(provider=moving_llm(), use_cache=False, previous=saved))
    assert second.run.partly_read_files == 1
    assert [(o.id, o.lines, o.symbol) for o in second.observations] == [(first.observations[0].id, (4, 4), "a")]
    assert second.requirements[0].evidence[0].symbol == "a"


def test_a_reused_requirement_gets_its_evidence_symbol_refreshed(tmp_path, monkeypatch):
    use(monkeypatch, AstSyntax())
    (tmp_path / "m.py").write_text(MOVING)
    first = extract(tmp_path, Config(provider=moving_llm(), use_cache=False))
    saved = tmp_path / "previous.json"
    saved.write_text(first.to_json())
    (tmp_path / "m.py").write_text(MOVING.replace("def b():\n", ""))
    second = extract(tmp_path, Config(provider=moving_llm(), use_cache=False, previous=saved))
    assert second.run.reused_capabilities == ["stock"]   # same observation id, so the requirement is kept
    assert [e.symbol for e in second.requirements[0].evidence] == ["a"]


def test_a_large_file_reaches_the_model_cut_between_functions():
    import re
    from backspec.modules.discovery.facade import SourceFile
    from backspec.modules.evidence.use_cases import observe as observe_files
    lines, symbols = long_file(functions=60)
    llm = FakeLLM({"observe": lambda prompt: {"observations": [], "none": []}})
    text = "\n".join(lines)
    observe_files([SourceFile("big.py", text, "sha256:x")], llm, batch_lines=100, syntax=AstSyntax())
    shown = [r.prompt for r in llm.requests]
    assert len(shown) > 1
    seen = []
    for prompt in shown:
        numbers = [int(n) for n in re.findall(r"^\s*(\d+)\| ", prompt, re.M)]
        assert numbers == list(range(numbers[0], numbers[-1] + 1))   # real, consecutive line numbers
        assert not any(s.first_line <= numbers[-1] < s.last_line for s in symbols), "a batch ends inside a function"
        seen += numbers
    assert sorted(seen) == list(range(1, len(lines) + 1))
