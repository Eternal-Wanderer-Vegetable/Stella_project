# CI 错误日志

Run ruff check . --output-format=github
Error: astrbot_compat/__init__.py:8:1: I001 Import block is un-sorted or un-formatted
  help: Organize imports
Error: astrbot_compat/__init__.py:24:11: RUF022 `__all__` is not sorted
  help: Apply an isort-style sorting to `__all__`
Error: astrbot_compat/base.py:6:1: I001 Import block is un-sorted or un-formatted
  help: Organize imports
Error: astrbot_compat/base.py:34:9: SIM105 Use `contextlib.suppress(AttributeError)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(AttributeError): ...`
Error: astrbot_compat/base.py:60:62: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/base.py:111:63: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/base.py:114:65: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/base.py:117:55: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/base.py:123:9: I001 Import block is un-sorted or un-formatted
  help: Organize imports
Error: astrbot_compat/base.py:224:11: RUF022 `__all__` is not sorted
  help: Apply an isort-style sorting to `__all__`
Error: astrbot_compat/components.py:35:68: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/components.py:159:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/config.py:24:39: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/config.py:105:13: PTH105 `os.replace()` should be replaced by `Path.replace()`
  help: Replace with `Path(...).replace(...)`
Error: astrbot_compat/context.py:9:21: F401 `pathlib.Path` imported but unused
  help: Remove unused import: `pathlib.Path`
Error: astrbot_compat/context.py:53:70: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:56:70: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:59:78: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:62:54: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:66:56: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:70:66: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:74:68: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:91:33: N817 CamelCase `MessageChain` imported as acronym `MC`
Error: astrbot_compat/context.py:97:13: SIM114 Combine `if` branches using logical `or` operator
  help: Combine `if` branches
Error: astrbot_compat/context.py:159:59: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/context.py:171:34: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/events.py:6:1: I001 Import block is un-sorted or un-formatted
  help: Organize imports
Error: astrbot_compat/events.py:13:80: F401 `.components.Face` imported but unused
  help: Remove unused import: `.components.Face`
Error: astrbot_compat/events.py:84:12: PIE810 Call `startswith` once with a `tuple`
  help: Merge into a single `startswith` call
Error: astrbot_compat/events.py:105:43: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/events.py:298:12: PIE810 Call `startswith` once with a `tuple`
  help: Merge into a single `startswith` call
Error: astrbot_compat/events.py:325:9: SIM114 Combine `if` branches using logical `or` operator
  help: Combine `if` branches
Error: astrbot_compat/events.py:349:72: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/events.py:357:13: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/events.py:365:13: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/events.py:393:63: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/events.py:476:12: RET504 Unnecessary assignment to `event` before `return` statement
  help: Remove unnecessary assignment
Error: astrbot_compat/exceptions.py:13:7: N818 Exception name `StellaCompatNotSupported` should be named with an Error suffix
Error: astrbot_compat/filters.py:6:1: I001 Import block is un-sorted or un-formatted
  help: Organize imports
Error: astrbot_compat/filters.py:11:1: UP035 Import from `collections.abc` instead: `Callable`
  help: Import from `collections.abc`
Error: astrbot_compat/filters.py:22:7: SLOT000 Subclasses of `str` should define `__slots__`
Error: astrbot_compat/filters.py:75:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:95:20: RUF005 Consider `[name, *sorted(self.alias)]` instead of concatenation
  help: Replace with `[name, *sorted(self.alias)]`
Error: astrbot_compat/filters.py:102:31: RUF005 Consider `[name, *sorted(self.alias)]` instead of concatenation
  help: Replace with `[name, *sorted(self.alias)]`
Error: astrbot_compat/filters.py:106:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:119:17: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/filters.py:140:20: RUF005 Consider `[name, *sorted(self.alias)]` instead of concatenation
  help: Replace with `[name, *sorted(self.alias)]`
Error: astrbot_compat/filters.py:146:31: RUF005 Consider `[name, *sorted(self.alias)]` instead of concatenation
  help: Replace with `[name, *sorted(self.alias)]`
Error: astrbot_compat/filters.py:152:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:162:9: SIM110 Use `return any(s == fn or s.startswith(fn + " ") for fn in self.full_names)` instead of `for` loop
  help: Replace with `return any(s == fn or s.startswith(fn + " ") for fn in self.full_names)`
Error: astrbot_compat/filters.py:178:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:196:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:212:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:225:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:232:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:248:61: RUF100 Unused `noqa` directive (non-enabled: `ARG002`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:278:5: SIM105 Use `contextlib.suppress(AttributeError)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(AttributeError): ...`
Error: astrbot_compat/filters.py:279:9: B010 Do not call `setattr` with a constant attribute value. It is not any safer than normal property access.
  help: Replace `setattr` with assignment
Error: astrbot_compat/filters.py:307:9: SIM114 Combine `if` branches using logical `or` operator
  help: Combine `if` branches
Error: astrbot_compat/filters.py:498:94: RUF100 Unused `noqa` directive (unused: `A001`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/filters.py:508:85: RUF100 Unused `noqa` directive (unused: `A001`)
  help: Remove unused `noqa` directive
Error: astrbot_compat/loader.py:17:18: PGH003 Use specific rule codes when ignoring type issues
Error: astrbot_compat/loader.py:19:18: PGH003 Use specific rule codes when ignoring type issues
Error: astrbot_compat/loader.py:22:52: PGH003 Use specific rule codes when ignoring type issues
Error: astrbot_compat/loader.py:24:26: PGH003 Use specific rule codes when ignoring type issues
Error: astrbot_compat/loader.py:259:9: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/loader.py:269:12: PIE810 Call `startswith` once with a `tuple`
  help: Merge into a single `startswith` call
Error: astrbot_compat/pipeline.py:37:9: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/pipeline.py:50:9: N806 Variable `GreedyStr` in function should be lowercase
Error: astrbot_compat/pipeline.py:50:27: PGH003 Use specific rule codes when ignoring type issues
Error: astrbot_compat/pipeline.py:56:9: B007 Loop control variable `idx` not used within loop body
  help: Rename unused `idx` to `_idx`
Error: astrbot_compat/pipeline.py:66:9: SIM114 Combine `if` branches using logical `or` operator
  help: Combine `if` branches
Error: astrbot_compat/pipeline.py:68:9: SIM114 Combine `if` branches using logical `or` operator
  help: Combine `if` branches
Error: astrbot_compat/pipeline.py:78:17: SIM108 Use ternary operator `val = default if has_default else ""` instead of `if`-`else`-block
  help: Replace `if`-`else`-block with `val = default if has_default else ""`
Error: astrbot_compat/pipeline.py:105:5: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/pipeline.py:115:5: SIM114 Combine `if` branches using logical `or` operator
  help: Combine `if` branches
Error: astrbot_compat/pipeline.py:199:9: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/pipeline.py:211:13: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/pipeline.py:248:17: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/pipeline.py:257:13: SIM105 Use `contextlib.suppress(Exception)` instead of `try`-`except`-`pass`
  help: Replace `try`-`except`-`pass` with `with contextlib.suppress(Exception): ...`
Error: astrbot_compat/registry.py:11:1: UP035 Import from `collections.abc` instead: `Callable`
  help: Import from `collections.abc`
Error: astrbot_compat/shim.py:181:5: I001 Import block is un-sorted or un-formatted
  help: Organize imports
Error: Process completed with exit code 1.