"""
NRQL-to-DQL Compiler
====================

Architecture:
    NRQL string -> Lexer -> Token[] -> Parser -> AST -> DQLEmitter -> DQL string

This replaces regex-based conversion with a proper compiler pipeline.
Structural bugs like duplicate aggregations, unnamed positional params,
leaked subqueries, and wrong alias syntax are impossible by construction.

Usage:
    compiler = NRQLCompiler()
    result = compiler.compile("SELECT count(*) FROM Transaction WHERE appName = 'my-app' TIMESERIES")
    print(result.dql)

Integration:
    # In NRQLtoDQLConverter.convert():
    result = self._compiler.compile(nrql)
    if result.success:
        return result  # AST path
    else:
        return self._regex_convert(nrql)  # Fallback
"""

from .compiler import CompileResult, NRQLCompiler

__all__ = ['NRQLCompiler', 'CompileResult']
