# test 3.10
=================================== FAILURES ===================================
________________________ test_sweep_resolves_stale_rows ________________________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fe09a3fdcc0>
tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_sweep_resolves_stale_rows0')

    def test_sweep_resolves_stale_rows(monkeypatch, tmp_path):
        _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(learning, "EXPRESSION_LEARNING_ENABLED", True)
        # asked_at_mono=0 表示很久以前（monotonic 不会回退）
        effect_id = store.add_reply_effect(
            group_shared_space="sp1", group_id=1, user_id=100,
            trigger="proactive", reply_excerpt="有人在吗", asked_at_mono=0.0,
        )
        assert store.get_reply_effect(effect_id)["resolved"] is False
    
        swept = learning.sweep_pending_effects()
>       assert swept == 1
E       assert 0 == 1

tests/test_expression_learning.py:211: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.21-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_expression_learning.py::test_sweep_resolves_stale_rows - assert 0 == 1
================= 1 failed, 1802 passed, 12 skipped in 56.81s ==================

# test 3.11
=================================== FAILURES ===================================
________________________ test_sweep_resolves_stale_rows ________________________
[gw2] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f2086433190>
tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_sweep_resolves_stale_rows0')

    def test_sweep_resolves_stale_rows(monkeypatch, tmp_path):
        _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(learning, "EXPRESSION_LEARNING_ENABLED", True)
        # asked_at_mono=0 表示很久以前（monotonic 不会回退）
        effect_id = store.add_reply_effect(
            group_shared_space="sp1", group_id=1, user_id=100,
            trigger="proactive", reply_excerpt="有人在吗", asked_at_mono=0.0,
        )
        assert store.get_reply_effect(effect_id)["resolved"] is False
    
        swept = learning.sweep_pending_effects()
>       assert swept == 1
E       assert 0 == 1

tests/test_expression_learning.py:211: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.16-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_expression_learning.py::test_sweep_resolves_stale_rows - assert 0 == 1
================= 1 failed, 1802 passed, 12 skipped in 53.59s ==================

# test 3.12

=================================== FAILURES ===================================
________________________ test_sweep_resolves_stale_rows ________________________
[gw0] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fdefc34abd0>
tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_sweep_resolves_stale_rows0')

    def test_sweep_resolves_stale_rows(monkeypatch, tmp_path):
        _setup(monkeypatch, tmp_path)
        monkeypatch.setattr(learning, "EXPRESSION_LEARNING_ENABLED", True)
        # asked_at_mono=0 表示很久以前（monotonic 不会回退）
        effect_id = store.add_reply_effect(
            group_shared_space="sp1", group_id=1, user_id=100,
            trigger="proactive", reply_excerpt="有人在吗", asked_at_mono=0.0,
        )
        assert store.get_reply_effect(effect_id)["resolved"] is False
    
        swept = learning.sweep_pending_effects()
>       assert swept == 1
E       assert 0 == 1

tests/test_expression_learning.py:211: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.14-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_expression_learning.py::test_sweep_resolves_stale_rows - assert 0 == 1
================= 1 failed, 1802 passed, 12 skipped in 55.46s ==================
