# test 3.10
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_plugin_path_online_payload_is_also_minimal 
INTERNALERROR> def worker_internal_error(
INTERNALERROR>         self, node: WorkerController, formatted_error: str
INTERNALERROR>     ) -> None:
INTERNALERROR>         """
INTERNALERROR>         pytest_internalerror() was called on the worker.
INTERNALERROR>     
INTERNALERROR>         pytest_internalerror() arguments are an excinfo and an excrepr, which can't
INTERNALERROR>         be serialized, so we go with a poor man's solution of raising an exception
INTERNALERROR>         here ourselves using the formatted message.
INTERNALERROR>         """
INTERNALERROR>         self._active_nodes.remove(node)
INTERNALERROR>         try:
INTERNALERROR> >           assert False, formatted_error
INTERNALERROR> E           AssertionError: Traceback (most recent call last):
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/main.py", line 330, in wrap_session
INTERNALERROR> E                 session.exitstatus = doit(config, session) or 0
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/main.py", line 384, in _main
INTERNALERROR> E                 config.hook.pytest_runtestloop(session=session)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR> E                 return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR> E                 return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR> E                 raise exception
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/logging.py", line 816, in pytest_runtestloop
INTERNALERROR> E                 return (yield)  # Run all the tests.
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/terminal.py", line 708, in pytest_runtestloop
INTERNALERROR> E                 result = yield
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pytest_cov/plugin.py", line 348, in pytest_runtestloop
INTERNALERROR> E                 result = yield
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR> E                 res = hook_impl.function(*args)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/xdist/remote.py", line 206, in pytest_runtestloop
INTERNALERROR> E                 self.run_one_test()
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/xdist/remote.py", line 227, in run_one_test
INTERNALERROR> E                 self.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR> E                 return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR> E                 return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR> E                 raise exception
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/warnings.py", line 90, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/assertion/__init__.py", line 205, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper
INTERNALERROR> E                 return result.get_result()
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_result.py", line 103, in get_result
INTERNALERROR> E                 raise exc.with_traceback(tb)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper
INTERNALERROR> E                 res = yield
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/unittest.py", line 612, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/faulthandler.py", line 102, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR> E                 res = hook_impl.function(*args)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/runner.py", line 118, in pytest_runtest_protocol
INTERNALERROR> E                 runtestprotocol(item, nextitem=nextitem)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/runner.py", line 139, in runtestprotocol
INTERNALERROR> E                 reports.append(call_and_report(item, "call", log))
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/runner.py", line 254, in call_and_report
INTERNALERROR> E                 report: TestReport = ihook.pytest_runtest_makereport(item=item, call=call)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR> E                 return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR> E                 return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR> E                 raise exception
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/tmpdir.py", line 347, in pytest_runtest_makereport
INTERNALERROR> E                 rep = yield
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/skipping.py", line 280, in pytest_runtest_makereport
INTERNALERROR> E                 rep = yield
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR> E                 res = hook_impl.function(*args)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/runner.py", line 385, in pytest_runtest_makereport
INTERNALERROR> E                 return TestReport.from_item_and_call(item, call)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/reports.py", line 438, in from_item_and_call
INTERNALERROR> E                 longrepr = _format_failed_longrepr(item, call, excinfo)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/reports.py", line 263, in _format_failed_longrepr
INTERNALERROR> E                 longrepr = item.repr_failure(excinfo)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/python.py", line 1749, in repr_failure
INTERNALERROR> E                 return self._repr_failure_py(excinfo, style=style)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/nodes.py", line 444, in _repr_failure_py
INTERNALERROR> E                 abspath = Path(os.getcwd()) != self.config.invocation_params.dir
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/pathlib.py", line 962, in __new__
INTERNALERROR> E                 raise NotImplementedError("cannot instantiate %r on your system"
INTERNALERROR> E             NotImplementedError: cannot instantiate 'WindowsPath' on your system
INTERNALERROR> E           assert False
INTERNALERROR> 
INTERNALERROR> /opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/xdist/dsession.py:232: AssertionError

tests/test_openai_contract.py::test_plugin_path_tools_stay_within_the_minimal_set 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_plugin_path_tools_stay_within_the_minimal_set 
tests/test_openai_contract.py::test_extra_body_is_opt_in_only 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_extra_body_is_opt_in_only 
tests/test_openai_contract.py::test_no_json_mode_is_ever_requested 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_no_json_mode_is_ever_requested 
tests/test_openai_contract.py::test_learns_the_length_field_and_retries 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_learns_the_length_field_and_retries 
tests/test_openai_contract.py::test_learns_to_omit_temperature_and_retries 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_learns_to_omit_temperature_and_retries 
INTERNALERROR> Traceback (most recent call last):
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/main.py", line 330, in wrap_session
INTERNALERROR>     session.exitstatus = doit(config, session) or 0
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/main.py", line 384, in _main
INTERNALERROR>     config.hook.pytest_runtestloop(session=session)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR>     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR>     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR>     raise exception
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/logging.py", line 816, in pytest_runtestloop
INTERNALERROR>     return (yield)  # Run all the tests.
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/_pytest/terminal.py", line 708, in pytest_runtestloop
INTERNALERROR>     result = yield
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pytest_cov/plugin.py", line 348, in pytest_runtestloop
INTERNALERROR>     result = yield
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR>     res = hook_impl.function(*args)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/xdist/dsession.py", line 138, in pytest_runtestloop
INTERNALERROR>     self.loop_once()
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/xdist/dsession.py", line 163, in loop_once
INTERNALERROR>     call(**kwargs)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/site-packages/xdist/dsession.py", line 217, in worker_workerfinished
INTERNALERROR>     assert not crashitem, (crashitem, node)
INTERNALERROR> AssertionError: ('tests/test_napcat_package.py::test_pinned_msi_installs_without_attempting_login', <WorkerController gw1>)
INTERNALERROR> assert not 'tests/test_napcat_package.py::test_pinned_msi_installs_without_attempting_login'

====================== 1381 passed, 12 skipped in 29.65s =======================
Error: Process completed with exit code 3.
# test 3.11
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_extra_body_is_opt_in_only 
tests/test_openai_contract.py::test_no_json_mode_is_ever_requested 
INTERNALERROR> def worker_internal_error(
INTERNALERROR>         self, node: WorkerController, formatted_error: str
INTERNALERROR>     ) -> None:
INTERNALERROR>         """
INTERNALERROR>         pytest_internalerror() was called on the worker.
INTERNALERROR>     
INTERNALERROR>         pytest_internalerror() arguments are an excinfo and an excrepr, which can't
INTERNALERROR>         be serialized, so we go with a poor man's solution of raising an exception
INTERNALERROR>         here ourselves using the formatted message.
INTERNALERROR>         """
INTERNALERROR>         self._active_nodes.remove(node)
INTERNALERROR>         try:
INTERNALERROR> >           assert False, formatted_error
INTERNALERROR> E           AssertionError: Traceback (most recent call last):
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/main.py", line 330, in wrap_session
INTERNALERROR> E                 session.exitstatus = doit(config, session) or 0
INTERNALERROR> E                                      ^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/main.py", line 384, in _main
INTERNALERROR> E                 config.hook.pytest_runtestloop(session=session)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR> E                 return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR> E                 return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR> E                 raise exception
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/logging.py", line 816, in pytest_runtestloop
INTERNALERROR> E                 return (yield)  # Run all the tests.
INTERNALERROR> E                         ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/terminal.py", line 708, in pytest_runtestloop
INTERNALERROR> E                 result = yield
INTERNALERROR> E                          ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pytest_cov/plugin.py", line 348, in pytest_runtestloop
INTERNALERROR> E                 result = yield
INTERNALERROR> E                          ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR> E                 res = hook_impl.function(*args)
INTERNALERROR> E                       ^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/xdist/remote.py", line 206, in pytest_runtestloop
INTERNALERROR> E                 self.run_one_test()
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/xdist/remote.py", line 227, in run_one_test
INTERNALERROR> E                 self.config.hook.pytest_runtest_protocol(item=item, nextitem=nextitem)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR> E                 return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR> E                 return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR> E                 raise exception
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/warnings.py", line 90, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E                         ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/assertion/__init__.py", line 205, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E                         ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 53, in run_old_style_hookwrapper
INTERNALERROR> E                 return result.get_result()
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_result.py", line 103, in get_result
INTERNALERROR> E                 raise exc.with_traceback(tb)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 38, in run_old_style_hookwrapper
INTERNALERROR> E                 res = yield
INTERNALERROR> E                       ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/unittest.py", line 612, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E                         ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/faulthandler.py", line 102, in pytest_runtest_protocol
INTERNALERROR> E                 return (yield)
INTERNALERROR> E                         ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR> E                 res = hook_impl.function(*args)
INTERNALERROR> E                       ^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/runner.py", line 118, in pytest_runtest_protocol
INTERNALERROR> E                 runtestprotocol(item, nextitem=nextitem)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/runner.py", line 139, in runtestprotocol
INTERNALERROR> E                 reports.append(call_and_report(item, "call", log))
INTERNALERROR> E                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/runner.py", line 254, in call_and_report
INTERNALERROR> E                 report: TestReport = ihook.pytest_runtest_makereport(item=item, call=call)
INTERNALERROR> E                                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR> E                 return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR> E                 return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR> E                 raise exception
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/tmpdir.py", line 347, in pytest_runtest_makereport
INTERNALERROR> E                 rep = yield
INTERNALERROR> E                       ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR> E                 teardown.throw(exception)
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/skipping.py", line 280, in pytest_runtest_makereport
INTERNALERROR> E                 rep = yield
INTERNALERROR> E                       ^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR> E                 res = hook_impl.function(*args)
INTERNALERROR> E                       ^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/runner.py", line 385, in pytest_runtest_makereport
INTERNALERROR> E                 return TestReport.from_item_and_call(item, call)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/reports.py", line 438, in from_item_and_call
INTERNALERROR> E                 longrepr = _format_failed_longrepr(item, call, excinfo)
INTERNALERROR> E                            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/reports.py", line 263, in _format_failed_longrepr
INTERNALERROR> E                 longrepr = item.repr_failure(excinfo)
INTERNALERROR> E                            ^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/python.py", line 1749, in repr_failure
INTERNALERROR> E                 return self._repr_failure_py(excinfo, style=style)
INTERNALERROR> E                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/nodes.py", line 444, in _repr_failure_py
INTERNALERROR> E                 abspath = Path(os.getcwd()) != self.config.invocation_params.dir
INTERNALERROR> E                           ^^^^^^^^^^^^^^^^^
INTERNALERROR> E               File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/pathlib.py", line 873, in __new__
INTERNALERROR> E                 raise NotImplementedError("cannot instantiate %r on your system"
INTERNALERROR> E             NotImplementedError: cannot instantiate 'WindowsPath' on your system
INTERNALERROR> E           assert False
INTERNALERROR> 
INTERNALERROR> /opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/xdist/dsession.py:232: AssertionError
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_no_json_mode_is_ever_requested 
tests/test_openai_contract.py::test_learns_the_length_field_and_retries 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_learns_the_length_field_and_retries 
tests/test_openai_contract.py::test_learns_to_omit_temperature_and_retries 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_learns_to_omit_temperature_and_retries 
tests/test_openai_contract.py::test_the_lesson_is_remembered_for_later_requests 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_the_lesson_is_remembered_for_later_requests 
tests/test_openai_contract.py::test_the_lesson_is_shared_across_both_code_paths 
[gw3] [ 70%] PASSED tests/test_openai_contract.py::test_the_lesson_is_shared_across_both_code_paths 
tests/test_openai_contract.py::test_different_slots_learn_independently 
INTERNALERROR> Traceback (most recent call last):
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/main.py", line 330, in wrap_session
INTERNALERROR>     session.exitstatus = doit(config, session) or 0
INTERNALERROR>                          ^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/main.py", line 384, in _main
INTERNALERROR>     config.hook.pytest_runtestloop(session=session)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_hooks.py", line 512, in __call__
INTERNALERROR>     return self._hookexec(self.name, self._hookimpls.copy(), kwargs, firstresult)
INTERNALERROR>            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_manager.py", line 120, in _hookexec
INTERNALERROR>     return self._inner_hookexec(hook_name, methods, kwargs, firstresult)
INTERNALERROR>            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 167, in _multicall
INTERNALERROR>     raise exception
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/logging.py", line 816, in pytest_runtestloop
INTERNALERROR>     return (yield)  # Run all the tests.
INTERNALERROR>             ^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/_pytest/terminal.py", line 708, in pytest_runtestloop
INTERNALERROR>     result = yield
INTERNALERROR>              ^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 139, in _multicall
INTERNALERROR>     teardown.throw(exception)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pytest_cov/plugin.py", line 348, in pytest_runtestloop
INTERNALERROR>     result = yield
INTERNALERROR>              ^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/pluggy/_callers.py", line 121, in _multicall
INTERNALERROR>     res = hook_impl.function(*args)
INTERNALERROR>           ^^^^^^^^^^^^^^^^^^^^^^^^^
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/xdist/dsession.py", line 138, in pytest_runtestloop
INTERNALERROR>     self.loop_once()
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/xdist/dsession.py", line 163, in loop_once
INTERNALERROR>     call(**kwargs)
INTERNALERROR>   File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/site-packages/xdist/dsession.py", line 217, in worker_workerfinished
INTERNALERROR>     assert not crashitem, (crashitem, node)
INTERNALERROR> AssertionError: ('tests/test_napcat_package.py::test_pinned_msi_installs_without_attempting_login', <WorkerController gw1>)
INTERNALERROR> assert not 'tests/test_napcat_package.py::test_pinned_msi_installs_without_attempting_login'

====================== 1383 passed, 12 skipped in 27.97s =======================
Error: Process completed with exit code 3.
# test 3.12
=================================== FAILURES ===================================
______________ test_pinned_msi_installs_without_attempting_login _______________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f2e849e20f0>
tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_pinned_msi_installs_witho0')

    def test_pinned_msi_installs_without_attempting_login(monkeypatch, tmp_path):
        archive = _archive(tmp_path, name="napcat.msi")
        manifest = _manifest(archive)
        calls = []
    
        monkeypatch.setattr(napcat.os, "name", "nt")
        monkeypatch.setattr(
            napcat.subprocess,
            "run",
            lambda command, **kwargs: calls.append((command, kwargs)),
        )
    
>       result = napcat.install_msi(archive, manifest, tmp_path / "data")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

/home/runner/work/Stella_project/Stella_project/tests/test_napcat_package.py:123: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/runner/work/Stella_project/Stella_project/deploy/napcat.py:197: in install_msi
    archive = Path(archive).expanduser().resolve()
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/pathlib.py:1244: in resolve
    p = self.with_segments(s)
        ^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/pathlib.py:385: in with_segments
    return type(self)(*pathsegments)
           ^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

cls = <class 'pathlib.WindowsPath'>
args = ('\\tmp\\pytest-of-runner\\pytest-0\\popen-gw1\\test_pinned_msi_installs_witho0\\napcat.msi',)
kwargs = {}

    def __new__(cls, *args, **kwargs):
>       raise NotImplementedError(
            f"cannot instantiate {cls.__name__!r} on your system")
E       NotImplementedError: cannot instantiate 'WindowsPath' on your system

/opt/hostedtoolcache/Python/3.12.14/x64/lib/python3.12/pathlib.py:1434: NotImplementedError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.14-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_napcat_package.py::test_pinned_msi_installs_without_attempting_login - NotImplementedError: cannot instantiate 'WindowsPath' on your system
================= 1 failed, 1957 passed, 17 skipped in 54.75s ==================
Error: Process completed with exit code 1.