# test 3.10
=================================== FAILURES ===================================
__________________ test_execute_start_captures_legacy_output ___________________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f366e7c17b0>

    def test_execute_start_captures_legacy_output(monkeypatch):
        monkeypatch.setattr(process, "start_detached", lambda: (print("started"), 0)[1])
        monkeypatch.setattr(runtime, "snapshot", lambda: {"components": {"stella": {"state": "starting"}}})
        result = runtime.execute_operation("start")
>       assert result["ok"] is True
E       assert False is True

tests/test_runtime_contract.py:160: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.21-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_runtime_contract.py::test_execute_start_captures_legacy_output - assert False is True
============ 1 failed, 1936 passed, 17 skipped in 60.16s (0:01:00) =============
# test 3.11
=================================== FAILURES ===================================
__________________ test_execute_start_captures_legacy_output ___________________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f5ad45953d0>

    def test_execute_start_captures_legacy_output(monkeypatch):
        monkeypatch.setattr(process, "start_detached", lambda: (print("started"), 0)[1])
        monkeypatch.setattr(runtime, "snapshot", lambda: {"components": {"stella": {"state": "starting"}}})
        result = runtime.execute_operation("start")
>       assert result["ok"] is True
E       assert False is True

tests/test_runtime_contract.py:160: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.16-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_runtime_contract.py::test_execute_start_captures_legacy_output - assert False is True
================= 1 failed, 1936 passed, 17 skipped in 57.01s ==================
Error: Process completed with exit code 1.
# test 3.12
=================================== FAILURES ===================================
__________________ test_execute_start_captures_legacy_output ___________________
[gw3] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f8ffd9d9af0>

    def test_execute_start_captures_legacy_output(monkeypatch):
        monkeypatch.setattr(process, "start_detached", lambda: (print("started"), 0)[1])
        monkeypatch.setattr(runtime, "snapshot", lambda: {"components": {"stella": {"state": "starting"}}})
        result = runtime.execute_operation("start")
>       assert result["ok"] is True
E       assert False is True

tests/test_runtime_contract.py:160: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.14-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_runtime_contract.py::test_execute_start_captures_legacy_output - assert False is True
============ 1 failed, 1936 passed, 17 skipped in 60.70s (0:01:00) =============
Error: Process completed with exit code 1.