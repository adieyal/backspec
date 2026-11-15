"""Following calls into files that are not selected: only what the selected code reaches is read,
what is not followed is recorded, and citations there keep their real line numbers."""
import ast
import re

import pytest

from backspec import Config, extract
from backspec.host import composition
from backspec.host.adapters.fake import FakeLLM
from backspec.modules.discovery.facade import SourceFile
from backspec.modules.evidence.domain import Symbol
from backspec.modules.evidence.use_cases import observe
from backspec.modules.reach.domain import Call, Definition, reach
from backspec.modules.reach.use_cases import plan


class AstSyntax:
    """Definitions and calls from Python's own parser, standing in for tree-sitter."""
    def symbols(self, path, text):
        found = []

        def walk(nodes, qualifier, in_class):
            for n in nodes:
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                    name = f"{qualifier}.{n.name}" if qualifier else n.name
                    kind = "class" if isinstance(n, ast.ClassDef) else "method" if in_class else "function"
                    first = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])])
                    found.append(Symbol(name, kind, first, n.end_lineno))
                    walk(n.body, name, isinstance(n, ast.ClassDef))
        walk(ast.parse(text).body, "", False)
        return found

    def calls(self, path, text):
        out, callees = [], set()
        for n in ast.walk(ast.parse(text)):
            if isinstance(n, ast.Call):
                callees.add(id(n.func))
                if isinstance(n.func, ast.Name):
                    out.append(Call(n.func.id, n.lineno))
                elif isinstance(n.func, ast.Attribute):
                    out.append(Call(n.func.attr, n.lineno))
        for n in ast.walk(ast.parse(text)):
            if isinstance(n, ast.Attribute) and id(n) not in callees:
                out.append(Call(n.attr, n.lineno, called=False))
        return out

    def properties(self, path, text):
        return {min(d.lineno for d in n.decorator_list) for n in ast.walk(ast.parse(text))
                if isinstance(n, ast.FunctionDef) and any(
                    (isinstance(d, ast.Name) and d.id == "property") or (isinstance(d, ast.Attribute) and d.attr == "setter")
                    for d in n.decorator_list)}


VIEW = "\n".join([
    "def close_run(request, run):",        # 1
    "    run.finish(request.user)",        # 2
    "    run.save()",                      # 3
    "    run.signature = request.POST['s']",  # 4
])

MODELS = "\n".join([
    "class Run:",                          # 1
    "    def finish(self, user):",         # 2
    "        self.check_owner(user)",      # 3
    "        self.status = 'done'",        # 4
    "",                                    # 5
    "    def check_owner(self, user):",    # 6
    "        if user != self.owner:",      # 7
    "            raise Forbidden()",       # 8
    "        self.audit()",                # 9
    "",                                    # 10
    "    def audit(self):",                # 11
    "        log_audit(self)",             # 12
    "        return True",                 # 13
    "",                                    # 14
    "    def save(self):",                 # 15
    "        persist(self)",               # 16
    "        return self",                 # 17
    "",                                    # 18
    "    def unrelated(self):",            # 19
    "        x = 1",                       # 20
    "        return x",                    # 21
    "",                                    # 22
    "    @property",                       # 23
    "    def signature(self):",            # 24
    "        return self.meta['sig']",     # 25
    "",                                    # 26
    "    @signature.setter",               # 27
    "    def signature(self, value):",     # 28
    "        self.meta['sig'] = value",    # 29
])


def files():
    return [SourceFile("views.py", VIEW, "sha256:v")], [SourceFile("models.py", MODELS, "sha256:m")]


def test_calls_are_followed_only_as_deep_as_the_depth_allows():
    seeds, followed = files()
    one = plan(seeds, followed, AstSyntax(), ["models.py"], depth=1)
    two = plan(seeds, followed, AstSyntax(), ["models.py"], depth=2)
    three = plan(seeds, followed, AstSyntax(), ["models.py"], depth=3)
    names = lambda report: sorted({r.symbol for r in report.reached})
    assert names(one) == ["Run.finish", "Run.signature"]
    assert names(two) == ["Run.check_owner", "Run.finish", "Run.signature"]
    assert names(three) == ["Run.audit", "Run.check_owner", "Run.finish", "Run.signature"]
    reached = {r.symbol: r for r in two.reached}
    assert reached["Run.check_owner"].depth == 2 and reached["Run.check_owner"].called_from == ["models.py:Run.finish"]
    assert reached["Run.finish"].called_from == ["views.py:close_run"]
    assert "Run.unrelated" not in names(three)


def test_a_generic_name_is_never_followed_and_is_recorded():
    seeds, followed = files()
    report = plan(seeds, followed, AstSyntax(), ["models.py"], depth=3)
    assert "Run.save" not in {r.symbol for r in report.reached}
    assert [(s.name, s.reason, s.called_from) for s in report.skipped] == [("save", "generic", ["views.py:close_run"])]


def test_a_name_defined_too_often_is_skipped_and_one_defined_twice_is_followed_with_its_ambiguity_recorded():
    defs = [Definition("m.py", f"C{i}.refund", "method", 10 * i, 10 * i + 3) for i in range(1, 5)]
    defs += [Definition("m.py", "A.approve", "method", 100, 103), Definition("m.py", "B.approve", "method", 110, 113)]
    seed = [(Call("refund", 1), "v.py:view"), (Call("approve", 2), "v.py:view")]
    reached, skipped, ambiguous = reach(seed, defs, {}, depth=2, max_definitions=3)
    assert [(s.name, s.reason, s.definitions) for s in skipped] == [("refund", "ambiguous", 4)]
    assert sorted(r.symbol for r in reached) == ["A.approve", "B.approve"]
    assert [(a.name, a.definitions) for a in ambiguous] == [("approve", ["m.py:A.approve", "m.py:B.approve"])]


def test_an_attribute_used_without_a_call_reaches_only_a_property():
    seeds, followed = files()
    report = plan(seeds, followed, AstSyntax(), ["models.py"], depth=1)
    signature = [r for r in report.reached if r.symbol == "Run.signature"]
    assert [r.lines for r in signature] == [(23, 25), (27, 29)]   # the getter and the setter, decorators included
    assert report.ambiguous == []   # a property and its setter are one name, not an ambiguity
    assert "Run.status" not in {r.symbol for r in report.reached}


def test_without_a_parser_nothing_is_followed_and_that_is_recorded():
    seeds, followed = files()
    report = plan(seeds, followed, None, ["models.py"])
    assert report.unavailable and report.reached == [] and report.files[0].reason == report.unavailable


def test_only_the_reached_parts_of_a_followed_file_are_shown_to_the_model():
    seeds, followed = files()
    prompts = []

    def answer(prompt):
        prompts.append(prompt)
        return {"observations": [], "none": []}
    report = plan(seeds, followed, AstSyntax(), ["models.py"], depth=2)
    result = observe([*seeds, *followed], FakeLLM({"observe": answer, "second_look": answer}),
                     syntax=AstSyntax(), parts=report.ranges())
    shown = "\n".join(prompts)
    assert "=== FILE: models.py (lines 2-4) ===" in shown and "=== FILE: models.py (lines 6-9) ===" in shown
    assert "raise Forbidden()" in shown and "self.check_owner(user)" in shown
    for hidden in ("def unrelated", "persist(self)", "log_audit(self)"):
        assert hidden not in shown
    assert result.read_in_part == {"models.py": sum(b - a + 1 for a, b in report.ranges()["models.py"])}
    # the second look is only at reached functions, never at the rest of the followed file
    assert "models.py" not in result.unobserved or "Run.unrelated" not in result.unobserved["models.py"]


def test_an_observation_outside_the_shown_parts_is_rejected_with_its_reason():
    seeds, followed = files()

    def answer(prompt):
        return {"observations": [{"path": "models.py", "lines": [20, 20], "quote": "x = 1", "kind": "rule",
                                  "statement": "Something the model was not shown."}]}
    result = observe([*seeds, *followed], FakeLLM({"observe": answer, "second_look": lambda p: {"observations": []}}),
                     syntax=AstSyntax(), parts={"models.py": [(2, 9)]})
    assert [r.reason for r in result.rejected] == ["outside the parts of the file that were shown"]
    assert not [o for o in result.observations if o.path == "models.py"]


def _fake(tmp_path):
    def observe_(prompt):
        out = []
        if "=== FILE: models.py" in prompt:
            out.append({"path": "models.py", "lines": [7, 8], "quote": "raise Forbidden()", "kind": "permission",
                        "statement": "Only the owner may finish a run."})
        if "=== FILE: views.py" in prompt:
            out.append({"path": "views.py", "lines": [2, 2], "quote": "run.finish(request.user)", "kind": "state_change",
                        "statement": "Closing a run finishes it as the requesting user."})
        return {"observations": out}

    def assign(prompt):
        return {"assignments": {i: "runs" for i in re.findall(r"^(OBS-\w+) \|", prompt, re.M)}}

    def synthesise(prompt):
        ids = re.findall(r"^(OBS-\w+) \|", prompt, re.M)
        return {"requirements": [{"statement": "Only a run's owner can close it.", "level": "user",
                                  "evidence": [{"observation": i, "role": "establishes"} for i in ids]}]}

    def assess(prompt):
        assert "raise Forbidden()" in prompt   # the support check sees the followed file's lines
        return {"verdicts": [{"id": i, "support": "direct", "note": "shown"} for i in re.findall(r"^##### (REQ-\w+)", prompt, re.M)]}
    return FakeLLM({"observe": observe_, "second_look": lambda p: {"observations": []},
                    "orient": lambda p: {"capabilities": [{"id": "runs", "name": "Runs", "summary": "Closing runs."}]},
                    "assign": assign, "synthesise": synthesise, "assess": assess})


def test_a_citation_in_a_followed_file_verifies_with_its_real_line_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(composition.TreeSitterSyntax, "load", classmethod(lambda cls: AstSyntax()))
    (tmp_path / "views.py").write_text(VIEW)
    (tmp_path / "models.py").write_text(MODELS)
    result = extract(tmp_path, Config(provider=_fake(tmp_path), use_cache=False, include=["/views.py"],
                                      follow=["/models.py"], triage=False))
    cited = [e for r in result.requirements for e in r.evidence if e.path == "models.py"]
    assert [(e.lines, e.quote, e.symbol) for e in cited] == [((7, 8), "raise Forbidden()", "Run.check_owner")]
    assert MODELS.split("\n")[7].strip() == "raise Forbidden()"   # line 8 really holds it
    entry = next(f for f in result.coverage.files if f.path == "models.py")
    assert (entry.read, entry.state, entry.reached) == ("in_part", "extracted", 4)   # finish, check_owner, and the signature getter and setter
    assert entry.lines_read < entry.lines
    assert result.run.followed_files == 1
    assert result.follow and [s.name for s in result.follow.skipped] == ["save"]
    assert not [f for f in result.diagnostics.lint if f.severity == "error"]


def test_a_followed_file_read_in_part_is_never_reused_as_if_read_in_full(tmp_path, monkeypatch):
    monkeypatch.setattr(composition.TreeSitterSyntax, "load", classmethod(lambda cls: AstSyntax()))
    (tmp_path / "views.py").write_text(VIEW)
    (tmp_path / "models.py").write_text(MODELS)
    first = extract(tmp_path, Config(provider=_fake(tmp_path), use_cache=False, include=["/views.py"],
                                     follow=["/models.py"], triage=False))
    from backspec.modules.report.facade import earlier_evidence
    assert "models.py" not in earlier_evidence(first, first.run.observe_fingerprint)


def test_tree_sitter_finds_calls_attributes_and_properties():
    pytest.importorskip("tree_sitter_language_pack")
    from backspec.host.adapters.treesitter import TreeSitterSyntax
    syntax = TreeSitterSyntax.load()
    if syntax is None:
        pytest.skip("tree-sitter disabled")
    calls = syntax.calls("views.py", VIEW)
    assert ("finish", 2, True) in [(c.name, c.line, c.called) for c in calls]
    assert ("signature", 4, False) in [(c.name, c.line, c.called) for c in calls]
    assert ("finish", 2, False) not in [(c.name, c.line, c.called) for c in calls]   # a callee is not also an attribute
    assert syntax.properties("models.py", MODELS) == {23, 27}
    report = plan(*files(), syntax, ["models.py"], depth=2)
    assert sorted({r.symbol for r in report.reached}) == ["Run.check_owner", "Run.finish", "Run.signature"]


def test_the_coverage_summary_and_the_html_report_say_the_followed_file_was_read_in_part(tmp_path, monkeypatch):
    from backspec.modules.report.facade import coverage_report, coverage_text, render
    monkeypatch.setattr(composition.TreeSitterSyntax, "load", classmethod(lambda cls: AstSyntax()))
    (tmp_path / "views.py").write_text(VIEW)
    (tmp_path / "models.py").write_text(MODELS)
    result = extract(tmp_path, Config(provider=_fake(tmp_path), use_cache=False, include=["/views.py"],
                                      follow=["/models.py"], triage=False))
    text = coverage_text(coverage_report(result))
    assert "read in part" in text and "models.py  (" in text and "calls not followed (1" in text and "save" in text
    html = render(result, "html").text
    assert "Read in part, following calls" in html and '"read": "in_part"' in html.replace('"read":"in_part"', '"read": "in_part"')
