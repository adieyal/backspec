"""A function the first reading recorded nothing in is shown to a model again; what is still
empty afterwards is recorded by name."""
import ast

from backspec.host.adapters.fake import FakeLLM
from backspec.modules.discovery.facade import SourceFile
from backspec.modules.evidence.domain import Symbol, unobserved
from backspec.modules.evidence.use_cases import observe

TEXT = "\n".join([
    "def pay(order):",                       # 1
    "    if order.total > LIMIT:",           # 2
    "        raise OverLimit()",             # 3
    "    charge(order)",                     # 4
    "",                                      # 5
    "def delete_issue(request):",            # 6
    "    item = request.item",               # 7
    "    if item is None:",                  # 8
    "        raise Http404('Item not found')",  # 9
    "    facade.remove_own_issue(item)",     # 10
    "",
    "def tiny(): pass",                      # 12
])


class Syntax:
    def symbols(self, path, text):
        return [Symbol(n.name, "function", n.lineno, n.end_lineno) for n in ast.parse(text).body
                if isinstance(n, ast.FunctionDef)]


def first(prompt):
    return {"observations": [{"path": "views.py", "lines": [2, 3], "quote": "if order.total > LIMIT:",
                              "kind": "validation", "statement": "An order over the limit is refused."}]}


def test_a_function_with_no_observation_is_looked_at_again_and_what_it_shows_is_kept():
    def second(prompt):
        assert "def delete_issue(request):" in prompt and "def pay(order):" not in prompt
        return {"observations": [{"path": "views.py", "lines": [8, 9], "quote": "raise Http404('Item not found')",
                                  "kind": "error_path", "statement": "Removing an issue from a missing item gives 404."}]}
    result = observe([SourceFile("views.py", TEXT, "sha256:x")], FakeLLM({"observe": first, "second_look": second}),
                     syntax=Syntax())
    assert {o.statement for o in result.observations} == {"An order over the limit is refused.",
                                                          "Removing an issue from a missing item gives 404."}
    assert result.unobserved == {}


def test_a_function_still_empty_after_the_second_look_is_recorded_by_name():
    llm = FakeLLM({"observe": first, "second_look": lambda prompt: {"observations": [], "none": []}})
    result = observe([SourceFile("views.py", TEXT, "sha256:x")], llm, syntax=Syntax())
    assert result.unobserved == {"views.py": ["delete_issue"]}


def test_a_failed_second_look_leaves_the_functions_recorded_not_the_file_failed():
    result = observe([SourceFile("views.py", TEXT, "sha256:x")], FakeLLM({"observe": first}), syntax=Syntax())
    assert result.unobserved == {"views.py": ["delete_issue"]} and result.failed == {}


def test_without_symbols_there_is_no_second_look():
    llm = FakeLLM({"observe": first})
    observe([SourceFile("views.py", TEXT, "sha256:x")], llm)
    assert [r.stage for r in llm.requests] == ["observe"]


def test_only_outermost_functions_of_some_size_count_as_unobserved():
    symbols = [Symbol("outer", "function", 1, 10), Symbol("outer.inner", "function", 3, 6),
               Symbol("Shop", "class", 12, 30), Symbol("Shop.buy", "method", 13, 20), Symbol("one_liner", "function", 31, 31)]
    assert [s.name for s in unobserved(symbols, [])] == ["outer", "Shop.buy"]
    assert [s.name for s in unobserved(symbols, [(4, 4)])] == ["Shop.buy"]
