# test 3.10
=================================== FAILURES ===================================
___________________ test_standalone_bootstrap_skips_network ____________________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_standalone_bootstrap_skip0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fe2bccdafe0>

    def test_standalone_bootstrap_skips_network(tmp_path, monkeypatch):
        def fail(*_args, **_kwargs):
            raise AssertionError("Standalone must not acquire remote packages")
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
>       result = bootstrap.install_profile("standalone-python", tmp_path / "data")

tests/test_bootstrap.py:100: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'standalone-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________________ test_oneclick_failure_records_failed_progress _________________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw3/test_oneclick_failure_records_0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f1b3d7766b0>

    def test_oneclick_failure_records_failed_progress(tmp_path, monkeypatch):
        catalog, _files = _catalog(tmp_path)
    
        def fail(*_args, **_kwargs):
            raise bootstrap.acquire.AcquireError("download_failed", "offline")
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
        with pytest.raises(bootstrap.BootstrapError, match="下载失败"):
>           bootstrap.install_profile(
                "oneclick-python", tmp_path / "data", catalog_path=catalog
            )

tests/test_bootstrap.py:153: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________ test_oneclick_installs_declared_components_and_only_embedding _________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_oneclick_installs_declare0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fe2bcd3fd60>

    def test_oneclick_installs_declared_components_and_only_embedding(
        tmp_path, monkeypatch
    ):
        catalog, files = _catalog(tmp_path)
        source_map = {
            "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
            "https://example.invalid/napcat.zip": files["napcat"],
            "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
                "qwen3-embedding-0.6b"
            ],
        }
    
        def fake_download(source, destination, *, checksum, size=None, **_kwargs):
            source_path = source_map[source]
            assert _sha256(source_path) == checksum
            if size is not None:
                assert source_path.stat().st_size == size
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_path.read_bytes())
            return destination
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
        data_root = tmp_path / "data"
>       result = bootstrap.install_profile(
            "oneclick-python", data_root, catalog_path=catalog
        )

tests/test_bootstrap.py:128: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_oneclick_is_idempotent_without_redownloading _______________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw3/test_oneclick_is_idempotent_wi0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f1b3d9684f0>

    def test_oneclick_is_idempotent_without_redownloading(tmp_path, monkeypatch):
        catalog, files = _catalog(tmp_path)
        source_map = {
            "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
            "https://example.invalid/napcat.zip": files["napcat"],
            "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
                "qwen3-embedding-0.6b"
            ],
        }
        calls = 0
    
        def fake_download(source, destination, *, checksum, size=None, **_kwargs):
            nonlocal calls
            calls += 1
            source_path = source_map[source]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_path.read_bytes())
            return destination
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
        data_root = tmp_path / "data"
>       bootstrap.install_profile("oneclick-python", data_root, catalog_path=catalog)

tests/test_bootstrap.py:182: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________ test_profile_catalog_includes_only_declared_default_embedding _________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_profile_catalog_includes_0')

    def test_profile_catalog_includes_only_declared_default_embedding(tmp_path):
        (tmp_path / "start.bat").write_text("start", encoding="utf-8")
>       catalog = packages.build_catalog(
            tmp_path,
            platform="windows-amd64",
            profile_id="oneclick-python",
        )

tests/test_packages.py:237: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/packages.py:540: in build_catalog
    "packages": _catalog_records(root, platform, profile_id),
deploy/packages.py:505: in _catalog_records
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
__________________ test_profile_catalog_is_available_from_cli __________________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f62ad8801f0>
tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_profile_catalog_is_availa0')
capsys = <_pytest.capture.CaptureFixture object at 0x7f62ad880490>

    def test_profile_catalog_is_available_from_cli(monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(packages, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(deploy_main, "PROJECT_ROOT", tmp_path)
        (tmp_path / "start.bat").write_text("start", encoding="utf-8")
        assert (
>           deploy_main.main(
                [
                    "packages",
                    "catalog",
                    "--platform",
                    "windows-amd64",
                    "--profile",
                    "oneclick-python",
                ]
            )
            == 0
        )

tests/test_packages.py:254: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/__main__.py:793: in main
    return args.func(args)
deploy/__main__.py:408: in _cmd_packages
    path = packages.write_catalog(
deploy/packages.py:559: in write_catalog
    _atomic_write(path, build_catalog(root, platform=platform, profile_id=profile_id))
deploy/packages.py:540: in build_catalog
    "packages": _catalog_records(root, platform, profile_id),
deploy/packages.py:505: in _catalog_records
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_______ test_all_profiles_match_project_version_and_are_non_overlapping ________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

    def test_all_profiles_match_project_version_and_are_non_overlapping():
>       profiles = load_profiles()

tests/test_product_profiles.py:25: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
____ test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-rust] _____
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

profile_id = 'oneclick-rust'

    @pytest.mark.parametrize("profile_id", ["oneclick-python", "oneclick-rust"])
    def test_oneclick_has_only_qwen_embedding_as_default_model(profile_id):
>       profile = load_profiles()[profile_id]

tests/test_product_profiles.py:42: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___ test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-python] ____
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

profile_id = 'oneclick-python'

    @pytest.mark.parametrize("profile_id", ["oneclick-python", "oneclick-rust"])
    def test_oneclick_has_only_qwen_embedding_as_default_model(profile_id):
>       profile = load_profiles()[profile_id]

tests/test_product_profiles.py:42: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
__ test_standalone_has_no_downloaded_components_or_models[standalone-python] ___
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

profile_id = 'standalone-python'

    @pytest.mark.parametrize("profile_id", ["standalone-python", "standalone-rust"])
    def test_standalone_has_no_downloaded_components_or_models(profile_id):
>       profile = load_profiles()[profile_id]

tests/test_product_profiles.py:50: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___ test_standalone_has_no_downloaded_components_or_models[standalone-rust] ____
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

profile_id = 'standalone-rust'

    @pytest.mark.parametrize("profile_id", ["standalone-python", "standalone-rust"])
    def test_standalone_has_no_downloaded_components_or_models(profile_id):
>       profile = load_profiles()[profile_id]

tests/test_product_profiles.py:50: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_profile_rejects_missing_embedding_provenance _______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

    def test_profile_rejects_missing_embedding_provenance():
>       profile = copy.deepcopy(load_profiles()["oneclick-python"])

tests/test_product_profiles.py:57: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_release_builder_oneclick_is_single_executable ______________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_release_builder_oneclick_0')

    def test_release_builder_oneclick_is_single_executable(tmp_path):
        installer = tmp_path / "installer.exe"
        installer.write_bytes(b"installer")
        output = tmp_path / "oneclick"
>       result = build_oneclick(installer, output, "oneclick-python")

tests/test_product_profiles.py:113: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:145: in build_oneclick
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___________ test_release_builder_keeps_standalone_allowlist_separate ___________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_release_builder_keeps_sta0')

    def test_release_builder_keeps_standalone_allowlist_separate(tmp_path):
        source = tmp_path / "source"
        for relative in (
            "bot.py",
            "requirements.txt",
            "pyproject.toml",
            "LICENSE",
            "README.md",
            ".env.example",
            "start.bat",
            "doctor.bat",
            "stop.bat",
            "README-快速开始.txt",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        for directory in (
            "config",
            "core",
            "deploy",
            "extensions",
            "memory",
            "system_prompts",
            "runtime-manager",
        ):
            path = source / directory / "__init__.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (source / "runtime" / "python.exe").parent.mkdir(parents=True)
        (source / "runtime" / "python.exe").write_bytes(b"must not ship")
        (source / "models" / "chat.gguf").parent.mkdir(parents=True)
        (source / "models" / "chat.gguf").write_bytes(b"must not ship")
    
>       archive = build_standalone(
            source,
            tmp_path / "standalone",
            "standalone-python",
        )

tests/test_product_profiles.py:97: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:115: in build_standalone
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'standalone-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_________ test_installer_resources_are_allowlisted_and_profile_pinned __________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_installer_resources_are_a0')

    def test_installer_resources_are_allowlisted_and_profile_pinned(tmp_path):
        source = tmp_path / "source"
        for relative in (
            "bot.py",
            "requirements.txt",
            "pyproject.toml",
            "LICENSE",
            "README.md",
            ".env.example",
            "start.bat",
            "doctor.bat",
            "stop.bat",
            "README-快速开始.txt",
            "runtime-manager/schemas/runtime-manifest.schema.json",
            "runtime-manager/schemas/runtime-state.schema.json",
            "runtime-manager/schemas/package-catalog.schema.json",
            "runtime-manager/schemas/package-registry.schema.json",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        for directory in (
            "config",
            "core",
            "deploy",
            "extensions",
            "memory",
            "system_prompts",
            "runtime-manager",
        ):
            path = source / directory / "__init__.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (source / "tests").mkdir()
        (source / "tests" / "secret.txt").write_text("must not ship", encoding="utf-8")
    
        output = tmp_path / "resources"
>       stage_installer_resources(source, output, "oneclick-python")

tests/test_product_profiles.py:155: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:161: in stage_installer_resources
    profile = load_profile(profile_id)
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_____________ test_release_profiles_are_versioned_with_the_project _____________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

    def test_release_profiles_are_versioned_with_the_project():
        """A project version bump must not leave profiles naming the previous release."""
        from config.state import program_version
        from deploy.profiles import load_profiles
    
        version = program_version(PROJECT_ROOT)
>       profiles = load_profiles()

tests/test_release_layout.py:90: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.21-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_bootstrap.py::test_standalone_bootstrap_skips_network - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_failure_records_failed_progress - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_installs_declared_components_and_only_embedding - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_is_idempotent_without_redownloading - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_packages.py::test_profile_catalog_includes_only_declared_default_embedding - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_packages.py::test_profile_catalog_is_available_from_cli - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_all_profiles_match_project_version_and_are_non_overlapping - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-rust] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-python] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_standalone_has_no_downloaded_components_or_models[standalone-python] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_standalone_has_no_downloaded_components_or_models[standalone-rust] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_profile_rejects_missing_embedding_provenance - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_release_builder_oneclick_is_single_executable - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_release_builder_keeps_standalone_allowlist_separate - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_installer_resources_are_allowlisted_and_profile_pinned - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_release_layout.py::test_release_profiles_are_versioned_with_the_project - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
================= 16 failed, 1944 passed, 17 skipped in 54.77s =================
Error: Process completed with exit code 1.
# test 3.11
=================================== FAILURES ===================================
___________________ test_standalone_bootstrap_skips_network ____________________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_standalone_bootstrap_skip0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b088b6390>

    def test_standalone_bootstrap_skips_network(tmp_path, monkeypatch):
        def fail(*_args, **_kwargs):
            raise AssertionError("Standalone must not acquire remote packages")
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
>       result = bootstrap.install_profile("standalone-python", tmp_path / "data")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_bootstrap.py:100: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'standalone-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_oneclick_is_idempotent_without_redownloading _______________
[gw2] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_oneclick_is_idempotent_wi0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f0d3bebb910>

    def test_oneclick_is_idempotent_without_redownloading(tmp_path, monkeypatch):
        catalog, files = _catalog(tmp_path)
        source_map = {
            "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
            "https://example.invalid/napcat.zip": files["napcat"],
            "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
                "qwen3-embedding-0.6b"
            ],
        }
        calls = 0
    
        def fake_download(source, destination, *, checksum, size=None, **_kwargs):
            nonlocal calls
            calls += 1
            source_path = source_map[source]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_path.read_bytes())
            return destination
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
        data_root = tmp_path / "data"
>       bootstrap.install_profile("oneclick-python", data_root, catalog_path=catalog)

tests/test_bootstrap.py:182: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________ test_oneclick_installs_declared_components_and_only_embedding _________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_oneclick_installs_declare0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b088415d0>

    def test_oneclick_installs_declared_components_and_only_embedding(
        tmp_path, monkeypatch
    ):
        catalog, files = _catalog(tmp_path)
        source_map = {
            "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
            "https://example.invalid/napcat.zip": files["napcat"],
            "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
                "qwen3-embedding-0.6b"
            ],
        }
    
        def fake_download(source, destination, *, checksum, size=None, **_kwargs):
            source_path = source_map[source]
            assert _sha256(source_path) == checksum
            if size is not None:
                assert source_path.stat().st_size == size
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_path.read_bytes())
            return destination
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
        data_root = tmp_path / "data"
>       result = bootstrap.install_profile(
            "oneclick-python", data_root, catalog_path=catalog
        )

tests/test_bootstrap.py:128: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________________ test_oneclick_failure_records_failed_progress _________________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_oneclick_failure_records_0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b088d5210>

    def test_oneclick_failure_records_failed_progress(tmp_path, monkeypatch):
        catalog, _files = _catalog(tmp_path)
    
        def fail(*_args, **_kwargs):
            raise bootstrap.acquire.AcquireError("download_failed", "offline")
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
        with pytest.raises(bootstrap.BootstrapError, match="下载失败"):
>           bootstrap.install_profile(
                "oneclick-python", tmp_path / "data", catalog_path=catalog
            )

tests/test_bootstrap.py:153: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________ test_profile_catalog_includes_only_declared_default_embedding _________
[gw1] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_profile_catalog_includes_0')

    def test_profile_catalog_includes_only_declared_default_embedding(tmp_path):
        (tmp_path / "start.bat").write_text("start", encoding="utf-8")
>       catalog = packages.build_catalog(
            tmp_path,
            platform="windows-amd64",
            profile_id="oneclick-python",
        )

tests/test_packages.py:237: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/packages.py:540: in build_catalog
    "packages": _catalog_records(root, platform, profile_id),
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/packages.py:505: in _catalog_records
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
__________________ test_profile_catalog_is_available_from_cli __________________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f3b1f1159d0>
tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_profile_catalog_is_availa0')
capsys = <_pytest.capture.CaptureFixture object at 0x7f3b08747e90>

    def test_profile_catalog_is_available_from_cli(monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(packages, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(deploy_main, "PROJECT_ROOT", tmp_path)
        (tmp_path / "start.bat").write_text("start", encoding="utf-8")
        assert (
>           deploy_main.main(
                [
                    "packages",
                    "catalog",
                    "--platform",
                    "windows-amd64",
                    "--profile",
                    "oneclick-python",
                ]
            )
            == 0
        )

tests/test_packages.py:254: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/__main__.py:793: in main
    return args.func(args)
           ^^^^^^^^^^^^^^^
deploy/__main__.py:408: in _cmd_packages
    path = packages.write_catalog(
deploy/packages.py:559: in write_catalog
    _atomic_write(path, build_catalog(root, platform=platform, profile_id=profile_id))
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/packages.py:540: in build_catalog
    "packages": _catalog_records(root, platform, profile_id),
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/packages.py:505: in _catalog_records
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_______ test_all_profiles_match_project_version_and_are_non_overlapping ________
[gw1] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

    def test_all_profiles_match_project_version_and_are_non_overlapping():
>       profiles = load_profiles()
                   ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:25: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___ test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-python] ____
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

profile_id = 'oneclick-python'

    @pytest.mark.parametrize("profile_id", ["oneclick-python", "oneclick-rust"])
    def test_oneclick_has_only_qwen_embedding_as_default_model(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:42: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
__ test_standalone_has_no_downloaded_components_or_models[standalone-python] ___
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

profile_id = 'standalone-python'

    @pytest.mark.parametrize("profile_id", ["standalone-python", "standalone-rust"])
    def test_standalone_has_no_downloaded_components_or_models(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:50: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
____ test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-rust] _____
[gw1] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

profile_id = 'oneclick-rust'

    @pytest.mark.parametrize("profile_id", ["oneclick-python", "oneclick-rust"])
    def test_oneclick_has_only_qwen_embedding_as_default_model(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:42: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_profile_rejects_missing_embedding_provenance _______________
[gw2] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

    def test_profile_rejects_missing_embedding_provenance():
>       profile = copy.deepcopy(load_profiles()["oneclick-python"])
                                ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:57: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___ test_standalone_has_no_downloaded_components_or_models[standalone-rust] ____
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

profile_id = 'standalone-rust'

    @pytest.mark.parametrize("profile_id", ["standalone-python", "standalone-rust"])
    def test_standalone_has_no_downloaded_components_or_models(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:50: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_________ test_installer_resources_are_allowlisted_and_profile_pinned __________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_installer_resources_are_a0')

    def test_installer_resources_are_allowlisted_and_profile_pinned(tmp_path):
        source = tmp_path / "source"
        for relative in (
            "bot.py",
            "requirements.txt",
            "pyproject.toml",
            "LICENSE",
            "README.md",
            ".env.example",
            "start.bat",
            "doctor.bat",
            "stop.bat",
            "README-快速开始.txt",
            "runtime-manager/schemas/runtime-manifest.schema.json",
            "runtime-manager/schemas/runtime-state.schema.json",
            "runtime-manager/schemas/package-catalog.schema.json",
            "runtime-manager/schemas/package-registry.schema.json",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        for directory in (
            "config",
            "core",
            "deploy",
            "extensions",
            "memory",
            "system_prompts",
            "runtime-manager",
        ):
            path = source / directory / "__init__.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (source / "tests").mkdir()
        (source / "tests" / "secret.txt").write_text("must not ship", encoding="utf-8")
    
        output = tmp_path / "resources"
>       stage_installer_resources(source, output, "oneclick-python")

tests/test_product_profiles.py:155: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:161: in stage_installer_resources
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___________ test_release_builder_keeps_standalone_allowlist_separate ___________
[gw1] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_release_builder_keeps_sta0')

    def test_release_builder_keeps_standalone_allowlist_separate(tmp_path):
        source = tmp_path / "source"
        for relative in (
            "bot.py",
            "requirements.txt",
            "pyproject.toml",
            "LICENSE",
            "README.md",
            ".env.example",
            "start.bat",
            "doctor.bat",
            "stop.bat",
            "README-快速开始.txt",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        for directory in (
            "config",
            "core",
            "deploy",
            "extensions",
            "memory",
            "system_prompts",
            "runtime-manager",
        ):
            path = source / directory / "__init__.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (source / "runtime" / "python.exe").parent.mkdir(parents=True)
        (source / "runtime" / "python.exe").write_bytes(b"must not ship")
        (source / "models" / "chat.gguf").parent.mkdir(parents=True)
        (source / "models" / "chat.gguf").write_bytes(b"must not ship")
    
>       archive = build_standalone(
            source,
            tmp_path / "standalone",
            "standalone-python",
        )

tests/test_product_profiles.py:97: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:115: in build_standalone
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'standalone-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_release_builder_oneclick_is_single_executable ______________
[gw2] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_release_builder_oneclick_0')

    def test_release_builder_oneclick_is_single_executable(tmp_path):
        installer = tmp_path / "installer.exe"
        installer.write_bytes(b"installer")
        output = tmp_path / "oneclick"
>       result = build_oneclick(installer, output, "oneclick-python")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_product_profiles.py:113: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:145: in build_oneclick
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_____________ test_release_profiles_are_versioned_with_the_project _____________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

    def test_release_profiles_are_versioned_with_the_project():
        """A project version bump must not leave profiles naming the previous release."""
        from config.state import program_version
        from deploy.profiles import load_profiles
    
        version = program_version(PROJECT_ROOT)
>       profiles = load_profiles()
                   ^^^^^^^^^^^^^^^

tests/test_release_layout.py:90: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:148: in <dictcomp>
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.16-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_bootstrap.py::test_standalone_bootstrap_skips_network - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_is_idempotent_without_redownloading - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_installs_declared_components_and_only_embedding - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_failure_records_failed_progress - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_packages.py::test_profile_catalog_includes_only_declared_default_embedding - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_packages.py::test_profile_catalog_is_available_from_cli - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_all_profiles_match_project_version_and_are_non_overlapping - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-python] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_standalone_has_no_downloaded_components_or_models[standalone-python] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-rust] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_profile_rejects_missing_embedding_provenance - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_standalone_has_no_downloaded_components_or_models[standalone-rust] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_installer_resources_are_allowlisted_and_profile_pinned - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_release_builder_keeps_standalone_allowlist_separate - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_release_builder_oneclick_is_single_executable - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_release_layout.py::test_release_profiles_are_versioned_with_the_project - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
================= 16 failed, 1944 passed, 17 skipped in 57.58s =================
Error: Process completed with exit code 1.
1s
# test 3.12
=================================== FAILURES ===================================
___________________ test_standalone_bootstrap_skips_network ____________________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_standalone_bootstrap_skip0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7ff29eea6570>

    def test_standalone_bootstrap_skips_network(tmp_path, monkeypatch):
        def fail(*_args, **_kwargs):
            raise AssertionError("Standalone must not acquire remote packages")
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
>       result = bootstrap.install_profile("standalone-python", tmp_path / "data")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_bootstrap.py:100: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'standalone-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________ test_oneclick_installs_declared_components_and_only_embedding _________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_oneclick_installs_declare0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7ff29eea99a0>

    def test_oneclick_installs_declared_components_and_only_embedding(
        tmp_path, monkeypatch
    ):
        catalog, files = _catalog(tmp_path)
        source_map = {
            "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
            "https://example.invalid/napcat.zip": files["napcat"],
            "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
                "qwen3-embedding-0.6b"
            ],
        }
    
        def fake_download(source, destination, *, checksum, size=None, **_kwargs):
            source_path = source_map[source]
            assert _sha256(source_path) == checksum
            if size is not None:
                assert source_path.stat().st_size == size
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_path.read_bytes())
            return destination
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
        data_root = tmp_path / "data"
>       result = bootstrap.install_profile(
            "oneclick-python", data_root, catalog_path=catalog
        )

tests/test_bootstrap.py:128: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_oneclick_is_idempotent_without_redownloading _______________
[gw3] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw3/test_oneclick_is_idempotent_wi0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7fa795bc3740>

    def test_oneclick_is_idempotent_without_redownloading(tmp_path, monkeypatch):
        catalog, files = _catalog(tmp_path)
        source_map = {
            "https://example.invalid/llama-cpu.zip": files["llama-cpu"],
            "https://example.invalid/napcat.zip": files["napcat"],
            "https://example.invalid/Qwen3-Embedding-0.6B-Q8_0.gguf": files[
                "qwen3-embedding-0.6b"
            ],
        }
        calls = 0
    
        def fake_download(source, destination, *, checksum, size=None, **_kwargs):
            nonlocal calls
            calls += 1
            source_path = source_map[source]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source_path.read_bytes())
            return destination
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fake_download)
        data_root = tmp_path / "data"
>       bootstrap.install_profile("oneclick-python", data_root, catalog_path=catalog)

tests/test_bootstrap.py:182: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________________ test_oneclick_failure_records_failed_progress _________________
[gw0] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_oneclick_failure_records_0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f359ce64d10>

    def test_oneclick_failure_records_failed_progress(tmp_path, monkeypatch):
        catalog, _files = _catalog(tmp_path)
    
        def fail(*_args, **_kwargs):
            raise bootstrap.acquire.AcquireError("download_failed", "offline")
    
        monkeypatch.setattr(bootstrap.acquire, "download_verified", fail)
        with pytest.raises(bootstrap.BootstrapError, match="下载失败"):
>           bootstrap.install_profile(
                "oneclick-python", tmp_path / "data", catalog_path=catalog
            )

tests/test_bootstrap.py:153: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/bootstrap.py:257: in install_profile
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
________ test_profile_catalog_includes_only_declared_default_embedding _________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_profile_catalog_includes_0')

    def test_profile_catalog_includes_only_declared_default_embedding(tmp_path):
        (tmp_path / "start.bat").write_text("start", encoding="utf-8")
>       catalog = packages.build_catalog(
            tmp_path,
            platform="windows-amd64",
            profile_id="oneclick-python",
        )

tests/test_packages.py:237: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/packages.py:540: in build_catalog
    "packages": _catalog_records(root, platform, profile_id),
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/packages.py:505: in _catalog_records
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
__________________ test_profile_catalog_is_available_from_cli __________________
[gw2] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x7f1035c59dc0>
tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_profile_catalog_is_availa0')
capsys = <_pytest.capture.CaptureFixture object at 0x7f1035c85400>

    def test_profile_catalog_is_available_from_cli(monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(packages, "PROJECT_ROOT", tmp_path)
        monkeypatch.setattr(deploy_main, "PROJECT_ROOT", tmp_path)
        (tmp_path / "start.bat").write_text("start", encoding="utf-8")
        assert (
>           deploy_main.main(
                [
                    "packages",
                    "catalog",
                    "--platform",
                    "windows-amd64",
                    "--profile",
                    "oneclick-python",
                ]
            )
            == 0
        )

tests/test_packages.py:254: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/__main__.py:793: in main
    return args.func(args)
           ^^^^^^^^^^^^^^^
deploy/__main__.py:408: in _cmd_packages
    path = packages.write_catalog(
deploy/packages.py:559: in write_catalog
    _atomic_write(path, build_catalog(root, platform=platform, profile_id=profile_id))
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/packages.py:540: in build_catalog
    "packages": _catalog_records(root, platform, profile_id),
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/packages.py:505: in _catalog_records
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
____ test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-rust] _____
[gw2] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

profile_id = 'oneclick-rust'

    @pytest.mark.parametrize("profile_id", ["oneclick-python", "oneclick-rust"])
    def test_oneclick_has_only_qwen_embedding_as_default_model(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:42: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___ test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-python] ____
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

profile_id = 'oneclick-python'

    @pytest.mark.parametrize("profile_id", ["oneclick-python", "oneclick-rust"])
    def test_oneclick_has_only_qwen_embedding_as_default_model(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:42: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_______ test_all_profiles_match_project_version_and_are_non_overlapping ________
[gw0] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

    def test_all_profiles_match_project_version_and_are_non_overlapping():
>       profiles = load_profiles()
                   ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:25: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
__ test_standalone_has_no_downloaded_components_or_models[standalone-python] ___
[gw2] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

profile_id = 'standalone-python'

    @pytest.mark.parametrize("profile_id", ["standalone-python", "standalone-rust"])
    def test_standalone_has_no_downloaded_components_or_models(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:50: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_profile_rejects_missing_embedding_provenance _______________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

    def test_profile_rejects_missing_embedding_provenance():
>       profile = copy.deepcopy(load_profiles()["oneclick-python"])
                                ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:57: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___ test_standalone_has_no_downloaded_components_or_models[standalone-rust] ____
[gw0] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

profile_id = 'standalone-rust'

    @pytest.mark.parametrize("profile_id", ["standalone-python", "standalone-rust"])
    def test_standalone_has_no_downloaded_components_or_models(profile_id):
>       profile = load_profiles()[profile_id]
                  ^^^^^^^^^^^^^^^

tests/test_product_profiles.py:50: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_________ test_installer_resources_are_allowlisted_and_profile_pinned __________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw1/test_installer_resources_are_a0')

    def test_installer_resources_are_allowlisted_and_profile_pinned(tmp_path):
        source = tmp_path / "source"
        for relative in (
            "bot.py",
            "requirements.txt",
            "pyproject.toml",
            "LICENSE",
            "README.md",
            ".env.example",
            "start.bat",
            "doctor.bat",
            "stop.bat",
            "README-快速开始.txt",
            "runtime-manager/schemas/runtime-manifest.schema.json",
            "runtime-manager/schemas/runtime-state.schema.json",
            "runtime-manager/schemas/package-catalog.schema.json",
            "runtime-manager/schemas/package-registry.schema.json",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        for directory in (
            "config",
            "core",
            "deploy",
            "extensions",
            "memory",
            "system_prompts",
            "runtime-manager",
        ):
            path = source / directory / "__init__.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (source / "tests").mkdir()
        (source / "tests" / "secret.txt").write_text("must not ship", encoding="utf-8")
    
        output = tmp_path / "resources"
>       stage_installer_resources(source, output, "oneclick-python")

tests/test_product_profiles.py:155: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:161: in stage_installer_resources
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
______________ test_release_builder_oneclick_is_single_executable ______________
[gw2] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_release_builder_oneclick_0')

    def test_release_builder_oneclick_is_single_executable(tmp_path):
        installer = tmp_path / "installer.exe"
        installer.write_bytes(b"installer")
        output = tmp_path / "oneclick"
>       result = build_oneclick(installer, output, "oneclick-python")
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_product_profiles.py:113: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:145: in build_oneclick
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
___________ test_release_builder_keeps_standalone_allowlist_separate ___________
[gw0] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw0/test_release_builder_keeps_sta0')

    def test_release_builder_keeps_standalone_allowlist_separate(tmp_path):
        source = tmp_path / "source"
        for relative in (
            "bot.py",
            "requirements.txt",
            "pyproject.toml",
            "LICENSE",
            "README.md",
            ".env.example",
            "start.bat",
            "doctor.bat",
            "stop.bat",
            "README-快速开始.txt",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative, encoding="utf-8")
        for directory in (
            "config",
            "core",
            "deploy",
            "extensions",
            "memory",
            "system_prompts",
            "runtime-manager",
        ):
            path = source / directory / "__init__.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        (source / "runtime" / "python.exe").parent.mkdir(parents=True)
        (source / "runtime" / "python.exe").write_bytes(b"must not ship")
        (source / "models" / "chat.gguf").parent.mkdir(parents=True)
        (source / "models" / "chat.gguf").write_bytes(b"must not ship")
    
>       archive = build_standalone(
            source,
            tmp_path / "standalone",
            "standalone-python",
        )

tests/test_product_profiles.py:97: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
scripts/build_release_package.py:115: in build_standalone
    profile = load_profile(profile_id)
              ^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'standalone-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
_____________ test_release_profiles_are_versioned_with_the_project _____________
[gw1] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

    def test_release_profiles_are_versioned_with_the_project():
        """A project version bump must not leave profiles naming the previous release."""
        from config.state import program_version
        from deploy.profiles import load_profiles
    
        version = program_version(PROJECT_ROOT)
>       profiles = load_profiles()
                   ^^^^^^^^^^^^^^^

tests/test_release_layout.py:90: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
deploy/profiles.py:148: in load_profiles
    return {profile_id: load_profile(profile_id, root) for profile_id in PROFILE_IDS}
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
deploy/profiles.py:144: in load_profile
    return validate_profile(_load_json(path))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

payload = {'id': 'oneclick-python', 'version': '4.0.3', 'platform': 'windows-amd64', 'core_flavor': 'python', ...}

    def validate_profile(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileError("产品 profile 必须是对象")
        required = {
            "id",
            "version",
            "platform",
            "core_flavor",
            "distribution",
            "included_components",
            "default_models",
            "optional_components",
            "artifact",
        }
        missing = sorted(required - payload.keys())
        if missing:
            raise ProfileError(f"产品 profile 缺少字段：{', '.join(missing)}")
        profile_id = str(payload["id"]).strip()
        if profile_id not in PROFILE_IDS:
            raise ProfileError(f"未知产品 profile：{profile_id}")
        project_version = _current_project_version()
        if str(payload["version"]).strip() != project_version:
>           raise ProfileError(
                f"产品 profile 版本必须与项目版本 {project_version} 一致"
            )
E           deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致

deploy/profiles.py:83: ProfileError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.14-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_bootstrap.py::test_standalone_bootstrap_skips_network - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_installs_declared_components_and_only_embedding - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_is_idempotent_without_redownloading - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_bootstrap.py::test_oneclick_failure_records_failed_progress - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_packages.py::test_profile_catalog_includes_only_declared_default_embedding - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_packages.py::test_profile_catalog_is_available_from_cli - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-rust] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_oneclick_has_only_qwen_embedding_as_default_model[oneclick-python] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_all_profiles_match_project_version_and_are_non_overlapping - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_standalone_has_no_downloaded_components_or_models[standalone-python] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_profile_rejects_missing_embedding_provenance - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_standalone_has_no_downloaded_components_or_models[standalone-rust] - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_installer_resources_are_allowlisted_and_profile_pinned - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_release_builder_oneclick_is_single_executable - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_product_profiles.py::test_release_builder_keeps_standalone_allowlist_separate - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
FAILED tests/test_release_layout.py::test_release_profiles_are_versioned_with_the_project - deploy.profiles.ProfileError: 产品 profile 版本必须与项目版本 4.0.4 一致
================= 16 failed, 1944 passed, 17 skipped in 54.48s =================
Error: Process completed with exit code 1.