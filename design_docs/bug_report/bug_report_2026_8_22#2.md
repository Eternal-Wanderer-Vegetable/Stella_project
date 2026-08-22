# test 3.10
==================================== ERRORS ====================================
______________ ERROR at setup of test_lifecycle_hooks_are_called _______________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw3/test_lifecycle_hooks_are_calle0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f35c4d7da80>

    @pytest.fixture
    def installed_plugin(tmp_path, monkeypatch):
        from config import settings
    
        plugins_dir = settings.PROJECT_ROOT / "data" / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        plugin_dir = plugins_dir / PLUGIN_DIR_NAME
        shutil.rmtree(plugin_dir, ignore_errors=True)
>       plugin_dir.mkdir()

tests/astrbot_compat/test_loader.py:72: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = PosixPath('/home/runner/work/Stella_project/Stella_project/data/plugins/stella_compat_selftest')
mode = 511, parents = False, exist_ok = False

    def mkdir(self, mode=0o777, parents=False, exist_ok=False):
        """
        Create a new directory at this given path.
        """
        try:
>           self._accessor.mkdir(self, mode)
E           FileExistsError: [Errno 17] File exists: '/home/runner/work/Stella_project/Stella_project/data/plugins/stella_compat_selftest'

/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/pathlib.py:1175: FileExistsError
=================================== FAILURES ===================================
____________________ test_loaded_plugin_responds_to_command ____________________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

installed_plugin = PosixPath('/home/runner/work/Stella_project/Stella_project/data/plugins/stella_compat_selftest')
make_event = <function make_event.<locals>._make at 0x7f3d4da71b40>
fake_bot = <conftest.FakeBot object at 0x7f3d4dade5f0>

    def test_loaded_plugin_responds_to_command(installed_plugin, make_event, fake_bot):
        from astrbot_compat.pipeline import dispatch
    
        loader.load_all_plugins()
>       assert asyncio.run(dispatch(make_event("/selftest 3"), fake_bot)) is True
E       AssertionError: assert False is True
E        +  where False = <function run at 0x7f3d61b13880>(<coroutine object dispatch at 0x7f3d4da8ec00>)
E        +    where <function run at 0x7f3d61b13880> = asyncio.run
E        +    and   <coroutine object dispatch at 0x7f3d4da8ec00> = <function dispatch at 0x7f3d60639870>(<conftest.FakeEvent object at 0x7f3d4dade410>, <conftest.FakeBot object at 0x7f3d4dade5f0>)
E        +      where <conftest.FakeEvent object at 0x7f3d4dade410> = <function make_event.<locals>._make at 0x7f3d4da71b40>('/selftest 3')

tests/astrbot_compat/test_loader.py:134: AssertionError
_______________________ test_load_all_plugins_end_to_end _______________________
[gw0] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

installed_plugin = PosixPath('/home/runner/work/Stella_project/Stella_project/data/plugins/stella_compat_selftest')

    def test_load_all_plugins_end_to_end(installed_plugin):
        loaded = loader.load_all_plugins()
        names = [md.name for md in loaded]
>       assert "selftest" in names
E       AssertionError: assert 'selftest' in []

tests/astrbot_compat/test_loader.py:99: AssertionError
------------------------------ Captured log call -------------------------------
ERROR    astrbot_compat.loader:loader.py:215 [astrbot_compat] 插件 stella_compat_selftest import 失败: No module named 'data.plugins.stella_compat_selftest.main'
Traceback (most recent call last):
  File "/home/runner/work/Stella_project/Stella_project/astrbot_compat/loader.py", line 212, in load_plugin
    mod = importlib.import_module(module_name)
  File "/opt/hostedtoolcache/Python/3.10.21/x64/lib/python3.10/importlib/__init__.py", line 126, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
  File "<frozen importlib._bootstrap>", line 1050, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1027, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1004, in _find_and_load_unlocked
ModuleNotFoundError: No module named 'data.plugins.stella_compat_selftest.main'
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.21-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/astrbot_compat/test_loader.py::test_loaded_plugin_responds_to_command - AssertionError: assert False is True
 +  where False = <function run at 0x7f3d61b13880>(<coroutine object dispatch at 0x7f3d4da8ec00>)
 +    where <function run at 0x7f3d61b13880> = asyncio.run
 +    and   <coroutine object dispatch at 0x7f3d4da8ec00> = <function dispatch at 0x7f3d60639870>(<conftest.FakeEvent object at 0x7f3d4dade410>, <conftest.FakeBot object at 0x7f3d4dade5f0>)
 +      where <conftest.FakeEvent object at 0x7f3d4dade410> = <function make_event.<locals>._make at 0x7f3d4da71b40>('/selftest 3')
FAILED tests/astrbot_compat/test_loader.py::test_load_all_plugins_end_to_end - AssertionError: assert 'selftest' in []
ERROR tests/astrbot_compat/test_loader.py::test_lifecycle_hooks_are_called - FileExistsError: [Errno 17] File exists: '/home/runner/work/Stella_project/Stella_project/data/plugins/stella_compat_selftest'
=================== 2 failed, 581 passed, 1 error in 41.76s ====================

# test 3.11

=================================== FAILURES ===================================
_______________________ test_lifecycle_hooks_are_called ________________________
[gw2] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

installed_plugin = PosixPath('/home/runner/work/Stella_project/Stella_project/data/plugins/stella_compat_selftest')

    def test_lifecycle_hooks_are_called(installed_plugin):
        loader.load_all_plugins()
>       mod = sys.modules[f"data.plugins.{PLUGIN_DIR_NAME}.main"]
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'data.plugins.stella_compat_selftest.main'

tests/astrbot_compat/test_loader.py:123: KeyError
------------------------------ Captured log call -------------------------------
ERROR    astrbot_compat.loader:loader.py:215 [astrbot_compat] 插件 stella_compat_selftest import 失败: No module named 'data.plugins.stella_compat_selftest'
Traceback (most recent call last):
  File "/home/runner/work/Stella_project/Stella_project/astrbot_compat/loader.py", line 212, in load_plugin
    mod = importlib.import_module(module_name)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/opt/hostedtoolcache/Python/3.11.16/x64/lib/python3.11/importlib/__init__.py", line 126, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1204, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1176, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1126, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 241, in _call_with_frames_removed
  File "<frozen importlib._bootstrap>", line 1204, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1176, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1140, in _find_and_load_unlocked
ModuleNotFoundError: No module named 'data.plugins.stella_compat_selftest'
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.16-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/astrbot_compat/test_loader.py::test_lifecycle_hooks_are_called - KeyError: 'data.plugins.stella_compat_selftest.main'
======================== 1 failed, 583 passed in 40.73s ========================

# test 3.12

=================================== FAILURES ===================================
_______________________ test_lifecycle_hooks_are_called ________________________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

installed_plugin = PosixPath('/home/runner/work/Stella_project/Stella_project/data/plugins/stella_compat_selftest')

    def test_lifecycle_hooks_are_called(installed_plugin):
        loader.load_all_plugins()
>       mod = sys.modules[f"data.plugins.{PLUGIN_DIR_NAME}.main"]
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'data.plugins.stella_compat_selftest.main'

tests/astrbot_compat/test_loader.py:123: KeyError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.14-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/astrbot_compat/test_loader.py::test_lifecycle_hooks_are_called - KeyError: 'data.plugins.stella_compat_selftest.main'
======================== 1 failed, 583 passed in 41.70s ========================