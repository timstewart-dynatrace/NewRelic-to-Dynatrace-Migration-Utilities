"""
NRQL-to-DQL Compiler -- Lexer (tokenizer).
"""

from __future__ import annotations
import re
from typing import List

from .tokens import TokenType, Token, KEYWORDS, NON_KEYWORD_IDENTS


class LexError(Exception):
    """Lexer error with position info."""
    def __init__(self, msg: str, pos: int = -1):
        self.pos = pos
        super().__init__(msg)


class NRQLLexer:
    """Tokenize an NRQL string."""

    def __init__(self, source: str):
        self.src = source
        self.pos = 0

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while self.pos < len(self.src):
            c = self.src[self.pos]

            # Skip whitespace
            if c in ' \t\n\r':
                self.pos += 1
                continue

            # SQL line comments (-- to end of line)
            if c == '-' and self.pos + 1 < len(self.src) and self.src[self.pos + 1] == '-':
                # Skip to end of line
                while self.pos < len(self.src) and self.src[self.pos] != '\n':
                    self.pos += 1
                continue

            # Skip semicolons (statement terminators)
            if c == ';':
                self.pos += 1
                continue

            # String literal  (single-quoted)
            if c == "'":
                tokens.append(self._string())
                continue

            # Number (including leading decimal like .30)
            if c.isdigit() or (c == '.' and self.pos + 1 < len(self.src) and self.src[self.pos + 1].isdigit()):
                tokens.append(self._number())
                continue

            # Two-char operators
            two = self.src[self.pos:self.pos + 2]
            if two == '!=':
                tokens.append(Token(TokenType.NEQ, '!=', self.pos)); self.pos += 2; continue
            if two == '<=':
                tokens.append(Token(TokenType.LTE, '<=', self.pos)); self.pos += 2; continue
            if two == '>=':
                tokens.append(Token(TokenType.GTE, '>=', self.pos)); self.pos += 2; continue

            # Single-char operators & punctuation
            OP_MAP = {
                '=': TokenType.EQ, '<': TokenType.LT, '>': TokenType.GT,
                '+': TokenType.PLUS, '-': TokenType.MINUS, '*': TokenType.STAR,
                '/': TokenType.SLASH, '%': TokenType.PERCENT,
                '(': TokenType.LPAREN, ')': TokenType.RPAREN, ',': TokenType.COMMA,
            }
            if c in OP_MAP:
                tokens.append(Token(OP_MAP[c], c, self.pos)); self.pos += 1; continue

            # Backtick-quoted identifier
            if c == '`':
                tokens.append(self._backtick_ident())
                continue

            # Identifier or keyword
            if c.isalpha() or c == '_':
                tokens.append(self._identifier())
                continue

            # Double-quoted string literal (used for aliases like AS "95th")
            if c == '"':
                tokens.append(self._dquote_string())
                continue

            # Skip characters that appear in NR queries but aren't syntactically meaningful
            # Colon (:) can appear in function call contexts
            if c == ':':
                self.pos += 1
                continue

            # Template variables: {{varName}} -> treat as identifier
            if c == '{' and self.pos + 1 < len(self.src) and self.src[self.pos + 1] == '{':
                tpl_start = self.pos
                self.pos += 2  # skip {{
                m = re.match(r'[a-zA-Z_][a-zA-Z0-9_]*', self.src[self.pos:])
                var_name = m.group(0) if m else 'template_var'
                if m:
                    self.pos += len(m.group(0))
                # Skip closing }}
                while self.pos < len(self.src) and self.src[self.pos] == '}':
                    self.pos += 1
                tokens.append(Token(TokenType.STRING, var_name, tpl_start))
                continue

            # Brackets: field['key'] or field[0] -> skip entire bracket expression
            if c == '[':
                self.pos += 1  # skip [
                depth = 1
                while self.pos < len(self.src) and depth > 0:
                    if self.src[self.pos] == '[': depth += 1
                    elif self.src[self.pos] == ']': depth -= 1
                    self.pos += 1
                continue

            if c in '{}':
                self.pos += 1
                continue

            raise LexError(f"Unexpected character '{c}' at position {self.pos}", self.pos)

        tokens.append(Token(TokenType.EOF, None, self.pos))
        return tokens

    def _string(self) -> Token:
        start = self.pos
        self.pos += 1  # skip '
        buf = []
        while self.pos < len(self.src):
            c = self.src[self.pos]
            if c == "'":
                # Escaped '' ?
                if self.pos + 1 < len(self.src) and self.src[self.pos + 1] == "'":
                    buf.append("'")
                    self.pos += 2
                else:
                    self.pos += 1
                    return Token(TokenType.STRING, ''.join(buf), start)
            elif c == '\\' and self.pos + 1 < len(self.src):
                next_c = self.src[self.pos + 1]
                # Only process SQL-style escapes (\' and \\)
                # Preserve regex escapes (\w, \d, \s, \S, \b, etc.)
                if next_c in ("'", '\\'):
                    buf.append(next_c)
                else:
                    buf.append('\\')
                    buf.append(next_c)
                self.pos += 2
            else:
                buf.append(c)
                self.pos += 1
        raise LexError(f"Unterminated string at position {start}", start)

    def _dquote_string(self) -> Token:
        """Parse a double-quoted string literal: "value" -> STRING token."""
        start = self.pos
        self.pos += 1  # skip opening "
        buf = []
        while self.pos < len(self.src):
            c = self.src[self.pos]
            if c == '"':
                self.pos += 1  # skip closing "
                return Token(TokenType.STRING, ''.join(buf), start)
            elif c == '\\' and self.pos + 1 < len(self.src):
                next_c = self.src[self.pos + 1]
                if next_c in ('"', '\\'):
                    buf.append(next_c)
                else:
                    buf.append('\\')
                    buf.append(next_c)
                self.pos += 2
            else:
                buf.append(c)
                self.pos += 1
        raise LexError(f"Unterminated double-quoted string at position {start}", start)

    def _number(self) -> Token:
        start = self.pos
        # Match: 123, 12.34, .30, 10e8, 1.5e-3
        m = re.match(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', self.src[self.pos:])
        if not m:
            raise LexError(f"Invalid number at position {start}", start)
        s = m.group(0)
        self.pos += len(s)
        val = float(s) if ('.' in s or 'e' in s.lower()) else int(s)
        return Token(TokenType.NUMBER, val, start)

    def _identifier(self) -> Token:
        start = self.pos
        # Identifiers can contain letters, digits, underscores, dots, colons (for builtin:*)
        m = re.match(r'[a-zA-Z_][a-zA-Z0-9_.:]*', self.src[self.pos:])
        if not m:
            raise LexError(f"Invalid identifier at position {start}", start)
        raw = m.group(0)
        # Trim trailing dots/colons
        raw = raw.rstrip('.').rstrip(':')
        self.pos += len(raw)
        low = raw.lower()
        # 'max' as keyword only in certain contexts (LIMIT MAX, SINCE MAX)
        if low == 'max':
            return Token(TokenType.MAX_KW, raw, start)
        if low in KEYWORDS and low not in NON_KEYWORD_IDENTS:
            return Token(KEYWORDS[low], raw, start)
        return Token(TokenType.IDENTIFIER, raw, start)

    def _backtick_ident(self) -> Token:
        start = self.pos
        self.pos += 1  # skip `
        buf = []
        while self.pos < len(self.src) and self.src[self.pos] != '`':
            buf.append(self.src[self.pos])
            self.pos += 1
        if self.pos >= len(self.src):
            raise LexError(f"Unterminated backtick identifier at position {start}", start)
        self.pos += 1  # skip `
        return Token(TokenType.IDENTIFIER, ''.join(buf), start)
