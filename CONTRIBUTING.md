# Contributing

Thanks for helping with Tado X Matter Pro. The short version:

1. Fork, branch from `main`, `uv sync` (Python 3.14, [uv](https://docs.astral.sh/uv/)).
2. Heating behaviour goes in `custom_components/tado_x_matter_pro/engine/` (pure Python, no Home
   Assistant imports); the Home Assistant side only feeds it inputs and carries out its effects.
3. Add or update tests: `tests/python/engine/` for the engine, `tests/python/` against a real Home
   Assistant core for everything else.
4. Strings: `strings.json` + `translations/`, English is the source, German second; logbook and
   notification texts in `messages.py`.
5. Run `scripts/check.sh` before opening the pull request.
6. Add a line to `CHANGELOG.md` under the next version.

Lifecycle guarantees to keep: removing the integration deletes its storage; unloading and reloading
leave no duplicate registrations and write nothing to the thermostats; stored data and config entries
carry versions and migrate forward, data from a newer version is refused.
