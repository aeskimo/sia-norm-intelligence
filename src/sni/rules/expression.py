"""Sichere Ausdrucks-Sprache für Rule-Expressions (M3, REQ-300).

Die Sprache wird von einem rekursiv-absteigenden Parser ausgewertet –
niemals ``eval()`` oder ``exec()`` (kein Code wird ausgeführt):

    expr    := term (('+' | '-') term)*
    term    := factor (('*' | '/') factor)*
    factor  := ('+' | '-') factor | atom
    atom    := NUMBER | IDENTIFIER | '(' expr ')'

- NUMBER: Dezimalzahl (z. B. ``2``, ``3.5``), skalar (ohne Einheit)
- IDENTIFIER: ``[A-Za-z][A-Za-z0-9_]*`` – verweist auf einen Rule-Input
  (Slug der Concept-ID: Teil nach dem letzten "/", "-" durch "_" ersetzt)

Einheiten (M3, REQ-302): jeder Operand trägt eine Einheit
(``str`` oder ``None`` für Skalar).

- ``+``/``-``: Einheiten müssen übereinstimmen; ein skalares Operand ist
  zulässig (wird dimensionslos interpretiert, Einheit des anderen bleibt).
- ``*``/``/``: keine Einheitberechnung für abgeleitete Einheiten – zwei
  Operanden mit Einheit erzeugen einen Fehler (lieber verweigern als
  einen falschen Wert liefern). Skalar * Größe propagiert die Einheit.
- Division durch Null ist ein Fehler.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass


class ExpressionError(ValueError):
    """Syntax-, Semantik- oder Einheitenfehler in einem Ausdruck."""


@dataclass(frozen=True)
class ExpressionValue:
    """Auswertungsergebnis: Zahl plus Einheit (``None`` = skalar)."""

    value: float
    unit: str | None = None


@dataclass(frozen=True)
class _Num:
    value: float


@dataclass(frozen=True)
class _Ident:
    name: str


@dataclass(frozen=True)
class _Unary:
    operand: _Node


@dataclass(frozen=True)
class _BinOp:
    op: str
    left: _Node
    right: _Node


_Node = _Num | _Ident | _Unary | _BinOp


@dataclass(frozen=True)
class _Token:
    kind: str  # "number" | "ident" | "op"
    value: str


def evaluate_expression(
    expression: str, bindings: Mapping[str, ExpressionValue]
) -> ExpressionValue:
    """Werteten den Ausdruck aus; ``bindings`` liefert Werte für Identifikatoren."""
    node = _parse(expression)
    return _eval(node, bindings)


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch in "+-*/()":
            tokens.append(_Token("op", ch))
            i += 1
        elif ch.isdigit() or (ch == "." and i + 1 < len(text) and text[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < len(text) and (text[j].isdigit() or (text[j] == "." and not seen_dot)):
                if text[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(_Token("number", text[i:j]))
            i = j
        elif ch.isalpha():
            j = i
            while j < len(text) and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(_Token("ident", text[i:j]))
            i = j
        else:
            raise ExpressionError(f"unerwartetes Zeichen {ch!r} an Position {i}")
    return tokens


def _parse(text: str) -> _Node:
    tokens = _tokenize(text)
    if not tokens:
        raise ExpressionError("leerer Ausdruck")
    parser = _Parser(tokens)
    return parser.parse()


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    def parse(self) -> _Node:
        node = self._expr()
        if self._pos != len(self._tokens):
            raise ExpressionError(f"unerwartetes Token {self._peek().value!r}")
        return node

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _next(self) -> _Token:
        if self._pos >= len(self._tokens):
            raise ExpressionError("unerwartetes Ende des Ausdrucks")
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def _peek_op(self) -> str | None:
        if self._pos < len(self._tokens) and self._tokens[self._pos].kind == "op":
            return self._tokens[self._pos].value
        return None

    def _expr(self) -> _Node:
        node = self._term()
        while self._peek_op() in ("+", "-"):
            op = self._next().value
            node = _BinOp(op, node, self._term())
        return node

    def _term(self) -> _Node:
        node = self._factor()
        while self._peek_op() in ("*", "/"):
            op = self._next().value
            node = _BinOp(op, node, self._factor())
        return node

    def _factor(self) -> _Node:
        token = self._next()
        if token.kind == "op" and token.value in ("+", "-"):
            if token.value == "+":
                return self._factor()
            return _Unary(self._factor())
        return self._atom_from(token)

    def _atom_from(self, token: _Token) -> _Node:
        if token.kind == "number":
            return _Num(float(token.value))
        if token.kind == "ident":
            return _Ident(token.value)
        if token.kind == "op" and token.value == "(":
            node = self._expr()
            closing = self._next()
            if closing.kind != "op" or closing.value != ")":
                raise ExpressionError("fehlende schließende Klammer")
            return node
        raise ExpressionError(f"unerwartetes Token {token.value!r}")


def _eval(node: _Node, bindings: Mapping[str, ExpressionValue]) -> ExpressionValue:
    if isinstance(node, _Num):
        return ExpressionValue(node.value)
    if isinstance(node, _Ident):
        if node.name not in bindings:
            raise ExpressionError(f"unbekannter Identifier {node.name!r}")
        return bindings[node.name]
    if isinstance(node, _Unary):
        inner = _eval(node.operand, bindings)
        return ExpressionValue(-inner.value, inner.unit)
    assert isinstance(node, _BinOp)
    left = _eval(node.left, bindings)
    right = _eval(node.right, bindings)
    return _apply(node.op, left, right)


def _apply(op: str, left: ExpressionValue, right: ExpressionValue) -> ExpressionValue:
    if op in ("+", "-"):
        if left.unit is not None and right.unit is not None and left.unit != right.unit:
            raise ExpressionError(f"Einheitenkonflikt in {op}: {left.unit} vs {right.unit}")
        unit = left.unit if left.unit is not None else right.unit
        value = left.value + right.value if op == "+" else left.value - right.value
        return ExpressionValue(value, unit)
    if op in ("*", "/"):
        if op == "/" and right.value == 0:
            raise ExpressionError("Division durch Null")
        if left.unit is not None and right.unit is not None:
            raise ExpressionError(
                f"keine Einheitberechnung für abgeleitete Einheiten ({left.unit} {op} {right.unit})"
            )
        unit = left.unit if left.unit is not None else right.unit
        value = left.value * right.value if op == "*" else left.value / right.value
        return ExpressionValue(value, unit)
    raise AssertionError(f"interner Fehler: Operator {op!r}")  # pragma: no cover


def identifiers_in(expression: str) -> list[str]:
    """Alle Identifikatoren des Ausdrucks, in Reihenfolge, Duplikate entfernt."""
    found: list[str] = []

    def _walk(node: _Node) -> None:
        if isinstance(node, _Ident) and node.name not in found:
            found.append(node.name)
        for field in dataclasses.fields(node):
            sub = getattr(node, field.name)
            if isinstance(sub, _Node):
                _walk(sub)

    _walk(_parse(expression))
    return found
