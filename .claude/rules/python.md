# Python Standards

## Environment
- Python 3.9+
- Dependencies in requirements.txt
- Virtual env: `python -m venv .venv && pip install -r requirements.txt`

## Code Style
- snake_case functions/variables, PascalCase classes, UPPER_SNAKE_CASE constants
- Type hints on all public function signatures
- Docstrings for public methods
- structlog for logging (not print)
- Pydantic for configuration

## Imports Order
1. Standard library
2. Third-party (click, rich, structlog, requests, pydantic)
3. Local (compiler, clients, transformers, validators, config, utils)

## Error Handling
- Specific exceptions, not bare `except:`
- Log errors with context via structlog
- Return structured results (`{Entity}TransformResult`, `ConversionResult`) rather than raising

## Adding a New Transformer
1. Create `transformers/new_transformer.py`
2. Implement `transform()` returning `{Entity}TransformResult`
3. Add mapping rules to `transformers/mapping_rules.py`
4. Register in `transformers/__init__.py`
5. Add to `MigrationOrchestrator` in `migrate.py`
6. Add tests
