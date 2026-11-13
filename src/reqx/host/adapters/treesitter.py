"""Symbols from tree-sitter, through the optional `tree-sitter-language-pack` package.

Everything here is optional: `TreeSitterSyntax.load()` returns None when the package is absent
(or when REQX_NO_TREESITTER is set, which tests use to simulate that), and `symbols` returns None
for a file whose language has no grammar or that fails to parse. reqx then reads the file as text.
"""
from __future__ import annotations

import os
from pathlib import PurePosixPath

from reqx.modules.evidence.domain import Symbol

# One grammar per extension.
GRAMMARS = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx", ".go": "go", ".java": "java", ".rb": "ruby", ".rs": "rust",
    ".cs": "csharp", ".php": "php",
}

# Per grammar: node type -> kind of symbol it defines. A function inside a class is a method.
# Containers that only group (namespaces, modules) are not listed; their contents are still walked.
_JS = {"function_declaration": "function", "generator_function_declaration": "function",
       "method_definition": "method", "class_declaration": "class"}
_TS = {**_JS, "abstract_class_declaration": "class", "interface_declaration": "class",
       "enum_declaration": "other", "type_alias_declaration": "other"}
_CS = {"class_declaration": "class", "struct_declaration": "class", "interface_declaration": "class",
       "record_declaration": "class", "enum_declaration": "other",
       "method_declaration": "method", "constructor_declaration": "method"}
DEFINITIONS = {
    "python": {"function_definition": "function", "class_definition": "class"},
    "javascript": _JS, "typescript": _TS, "tsx": _TS,
    "go": {"function_declaration": "function", "method_declaration": "method", "type_spec": "other"},
    "java": {"class_declaration": "class", "interface_declaration": "class", "enum_declaration": "class",
             "record_declaration": "class", "method_declaration": "method", "constructor_declaration": "method"},
    "ruby": {"method": "function", "singleton_method": "method", "class": "class", "module": "class"},
    "rust": {"function_item": "function", "struct_item": "class", "enum_item": "class", "trait_item": "class",
             "impl_item": "class"},
    "csharp": _CS,
    "php": {"function_definition": "function", "method_declaration": "method", "class_declaration": "class",
            "interface_declaration": "class", "trait_declaration": "class"},
}
# Where a definition's name is, when it is not the `name` field.
NAME_FIELD = {"impl_item": "type"}
# `const f = () => {}` and the like define a function through a variable.
FUNCTION_VALUES = {"arrow_function", "function_expression", "function"}
# Nodes that wrap a definition and belong to it (decorators, `export`, `const`).
WRAPPERS = {"decorated_definition", "export_statement", "lexical_declaration", "variable_declaration"}


class TreeSitterSyntax:
    def __init__(self, get_parser):
        self._get_parser = get_parser
        self._parsers: dict[str, object] = {}

    @classmethod
    def load(cls) -> "TreeSitterSyntax | None":
        if os.environ.get("REQX_NO_TREESITTER"):
            return None
        try:
            from tree_sitter_language_pack import get_parser
        except Exception:
            return None
        return cls(get_parser)

    def symbols(self, path: str, text: str) -> list[Symbol] | None:
        grammar = GRAMMARS.get(PurePosixPath(path).suffix.lower())
        if grammar is None:
            return None
        try:
            parser = self._parsers.get(grammar)
            if parser is None:
                parser = self._parsers[grammar] = self._get_parser(grammar)
            tree = parser.parse(text.encode("utf-8"))
            return _walk(tree.root_node, DEFINITIONS[grammar])
        except Exception:
            return None


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")


def _go_receiver(node) -> str:
    """The type a Go method is declared on, so that it is named `Type.Method`."""
    receiver = node.child_by_field_name("receiver")
    stack = [receiver] if receiver is not None else []
    while stack:
        current = stack.pop()
        if current.type == "type_identifier":
            return _text(current)
        stack.extend(reversed(current.children))
    return ""


def _definition(node, table: dict[str, str]) -> tuple[str, str, object] | None:
    """(name, kind, node whose lines the symbol covers) if this node defines something."""
    if node.type in table:
        named = node.child_by_field_name(NAME_FIELD.get(node.type, "name"))
        if named is None:
            return None
        name = _text(named)
        if node.type == "method_declaration" and table.get("type_spec"):   # Go
            name = f"{_go_receiver(node)}.{name}" if _go_receiver(node) else name
        return name, table[node.type], node
    if node.type == "variable_declarator" and "function_declaration" in table:
        value, named = node.child_by_field_name("value"), node.child_by_field_name("name")
        if value is not None and named is not None and value.type in FUNCTION_VALUES and named.type == "identifier":
            return _text(named), "function", node
    return None


def _walk(root, table: dict[str, str]) -> list[Symbol]:
    found: list[Symbol] = []
    stack = [(root, "", "")]   # node, qualifier, kind of the symbol around it
    while stack:
        node, qualifier, around = stack.pop()
        defined = _definition(node, table)
        if defined:
            name, kind, _ = defined
            if kind == "function" and around == "class":
                kind = "method"
            top = node
            while top.parent is not None and top.parent.type in WRAPPERS:
                top = top.parent
            qualified = f"{qualifier}.{name}" if qualifier else name
            found.append(Symbol(qualified, kind, top.start_point[0] + 1, node.end_point[0] + 1))   # type: ignore[arg-type]
            qualifier, around = qualified, kind
        stack.extend((child, qualifier, around) for child in reversed(node.children))
    return sorted(found, key=lambda s: (s.first_line, -s.last_line, s.name))
