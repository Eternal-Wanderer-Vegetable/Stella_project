# test 3.10
=================================== FAILURES ===================================
____________ test_oneclick_rust_downloads_wheel_before_tauri_build _____________
[gw1] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

    def test_oneclick_rust_downloads_wheel_before_tauri_build():
        """The slow installer build must consume an explicitly downloaded wheel.
    
        同时钉住 Offline 变体的管线结构：payload job 先行产出随包负载，installer
        matrix 带 payload 维度，收集步骤把 6 类资产全部落到 products/。
        """
        text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        installer = text[
            text.index("  build-installer:") : text.index("  build-rust-wheel:")
        ]
>       assert (
            "needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]"
            in installer
        )
E       assert 'needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]' in '  build-installer:\n    needs: [resolve-release, publish-candidate, build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]\n    strategy:\n      fail-fast: false\n      matrix:\n        profile: [oneclick-python, oneclick-rust]\n        payload: [online, offline]\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@v4\n\n      # 显式 setup-python（WP06）：不依赖 runner 的默认 Python——runner 镜像\n      # 升级换掉默认版本时，staging 脚本会在用户机器之外先炸一次。\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \'3.12\'\n\n      # dashboard 产物必须在「准备 OneClick 内嵌程序资源」之前到位：\n      # staging 的 webui/dist 兜底读 desktop/dashboard-dist，晚于 staging 就\n      # 会打出面板整页缺失的安装包（v5.0.0 离线包实测，2026-09-25）。\n      - name: 下载 WebUI 前端产物（壳内资源 + Bot payload 各一份）\n        uses: actions/download-artifact@v7\n        with:\n          name: stella-dashboard-dist\n          path: desktop/dashboard-dist\n\n      - name: 拷入 Bot payload 的 webui/dist\n        shell: pwsh\n        run: |\n          New-Item -ItemType Directory -Force -Path webui/dist | Out-Null\n          Copy-Item desktop/dashboard-dist/* webui/dist/ -Recurse -Force\n\n      - name: 透传统一解析的发布版本\n.../nsis/*setup.exe\' -File)\n          if ($exes.Count -ne 1) { throw "必须恰好一个安装器，实际为 $($exes.Count)" }\n          if ([string]::IsNullOrWhiteSpace($env:CERT_THUMBPRINT)) {\n            if (\'${{ github.event_name }}\' -eq \'push\') {\n              throw "正式发布（tag push）必须配置 STELLA_CERT_THUMBPRINT；未签名产物不得发布"\n            }\n            Write-Host "::warning::未配置 STELLA_CERT_THUMBPRINT，产物保持未签名（仅非正式构建允许）"\n            exit 0\n          }\n          $ts = if ([string]::IsNullOrWhiteSpace($env:CERT_TIMESTAMP_URL)) { \'http://timestamp.digicert.com\' } else { $env:CERT_TIMESTAMP_URL }\n          signtool sign /fd SHA256 /td SHA256 /tr $ts /sha1 $env:CERT_THUMBPRINT $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "签名失败（退出码 $LASTEXITCODE）" }\n          signtool verify /pa /all $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "验签失败（退出码 $LASTEXITCODE）" }\n          Write-Host "已签名并验签：$($exes[0].Name)"\n\n      - name: 上传安装器\n        uses: actions/upload-artifact@v7\n        with:\n          name: stella-desktop-${{ matrix.profile }}-${{ matrix.payload }}\n          path: desktop/src-tauri/target/release/bundle/nsis/*setup.exe\n          if-no-files-found: error\n\n'

tests/test_release_layout.py:123: AssertionError
_________________ test_recover_stale_treats_pid_reuse_as_stale _________________
[gw3] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw3/test_recover_stale_treats_pid_0')

    def test_recover_stale_treats_pid_reuse_as_stale(tmp_path):
        """进程活着但创建身份与记录不符 = PID 被复用 → 陈旧，可恢复。"""
        import os
    
        lock_path = _write_lock_with_owner(tmp_path, os.getpid(), "win-creation-42")
>       assert UpgradeLock(tmp_path).recover_stale() is True
E       AssertionError: assert False is True
E        +  where False = recover_stale()
E        +    where recover_stale = <deploy.upgrade.UpgradeLock object at 0x7f41bced27d0>.recover_stale
E        +      where <deploy.upgrade.UpgradeLock object at 0x7f41bced27d0> = UpgradeLock(PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw3/test_recover_stale_treats_pid_0'))

tests/test_upgrade.py:137: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.21-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_release_layout.py::test_oneclick_rust_downloads_wheel_before_tauri_build - assert 'needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]' in '  build-installer:\n    needs: [resolve-release, publish-candidate, build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]\n    strategy:\n      fail-fast: false\n      matrix:\n        profile: [oneclick-python, oneclick-rust]\n        payload: [online, offline]\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@v4\n\n      # 显式 setup-python（WP06）：不依赖 runner 的默认 Python——runner 镜像\n      # 升级换掉默认版本时，staging 脚本会在用户机器之外先炸一次。\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \'3.12\'\n\n      # dashboard 产物必须在「准备 OneClick 内嵌程序资源」之前到位：\n      # staging 的 webui/dist 兜底读 desktop/dashboard-dist，晚于 staging 就\n      # 会打出面板整页缺失的安装包（v5.0.0 离线包实测，2026-09-25）。\n      - name: 下载 WebUI 前端产物（壳内资源 + Bot payload 各一份）\n        uses: actions/download-artifact@v7\n        with:\n          name: stella-dashboard-dist\n          path: desktop/dashboard-dist\n\n      - name: 拷入 Bot payload 的 webui/dist\n        shell: pwsh\n        run: |\n          New-Item -ItemType Directory -Force -Path webui/dist | Out-Null\n          Copy-Item desktop/dashboard-dist/* webui/dist/ -Recurse -Force\n\n      - name: 透传统一解析的发布版本\n.../nsis/*setup.exe\' -File)\n          if ($exes.Count -ne 1) { throw "必须恰好一个安装器，实际为 $($exes.Count)" }\n          if ([string]::IsNullOrWhiteSpace($env:CERT_THUMBPRINT)) {\n            if (\'${{ github.event_name }}\' -eq \'push\') {\n              throw "正式发布（tag push）必须配置 STELLA_CERT_THUMBPRINT；未签名产物不得发布"\n            }\n            Write-Host "::warning::未配置 STELLA_CERT_THUMBPRINT，产物保持未签名（仅非正式构建允许）"\n            exit 0\n          }\n          $ts = if ([string]::IsNullOrWhiteSpace($env:CERT_TIMESTAMP_URL)) { \'http://timestamp.digicert.com\' } else { $env:CERT_TIMESTAMP_URL }\n          signtool sign /fd SHA256 /td SHA256 /tr $ts /sha1 $env:CERT_THUMBPRINT $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "签名失败（退出码 $LASTEXITCODE）" }\n          signtool verify /pa /all $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "验签失败（退出码 $LASTEXITCODE）" }\n          Write-Host "已签名并验签：$($exes[0].Name)"\n\n      - name: 上传安装器\n        uses: actions/upload-artifact@v7\n        with:\n          name: stella-desktop-${{ matrix.profile }}-${{ matrix.payload }}\n          path: desktop/src-tauri/target/release/bundle/nsis/*setup.exe\n          if-no-files-found: error\n\n'
FAILED tests/test_upgrade.py::test_recover_stale_treats_pid_reuse_as_stale - AssertionError: assert False is True
 +  where False = recover_stale()
 +    where recover_stale = <deploy.upgrade.UpgradeLock object at 0x7f41bced27d0>.recover_stale
 +      where <deploy.upgrade.UpgradeLock object at 0x7f41bced27d0> = UpgradeLock(PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw3/test_recover_stale_treats_pid_0'))
============ 2 failed, 2862 passed, 21 skipped in 75.96s (0:01:15) =============
Error: Process completed with exit code 1.
# test 3.11
=================================== FAILURES ===================================
____________ test_oneclick_rust_downloads_wheel_before_tauri_build _____________
[gw0] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

    def test_oneclick_rust_downloads_wheel_before_tauri_build():
        """The slow installer build must consume an explicitly downloaded wheel.
    
        同时钉住 Offline 变体的管线结构：payload job 先行产出随包负载，installer
        matrix 带 payload 维度，收集步骤把 6 类资产全部落到 products/。
        """
        text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        installer = text[
            text.index("  build-installer:") : text.index("  build-rust-wheel:")
        ]
>       assert (
            "needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]"
            in installer
        )
E       assert 'needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]' in '  build-installer:\n    needs: [resolve-release, publish-candidate, build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]\n    strategy:\n      fail-fast: false\n      matrix:\n        profile: [oneclick-python, oneclick-rust]\n        payload: [online, offline]\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@v4\n\n      # 显式 setup-python（WP06）：不依赖 runner 的默认 Python——runner 镜像\n      # 升级换掉默认版本时，staging 脚本会在用户机器之外先炸一次。\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \'3.12\'\n\n      # dashboard 产物必须在「准备 OneClick 内嵌程序资源」之前到位：\n      # staging 的 webui/dist 兜底读 desktop/dashboard-dist，晚于 staging 就\n      # 会打出面板整页缺失的安装包（v5.0.0 离线包实测，2026-09-25）。\n      - name: 下载 WebUI 前端产物（壳内资源 + Bot payload 各一份）\n        uses: actions/download-artifact@v7\n        with:\n          name: stella-dashboard-dist\n          path: desktop/dashboard-dist\n\n      - name: 拷入 Bot payload 的 webui/dist\n        shell: pwsh\n        run: |\n          New-Item -ItemType Directory -Force -Path webui/dist | Out-Null\n          Copy-Item desktop/dashboard-dist/* webui/dist/ -Recurse -Force\n\n      - name: 透传统一解析的发布版本\n.../nsis/*setup.exe\' -File)\n          if ($exes.Count -ne 1) { throw "必须恰好一个安装器，实际为 $($exes.Count)" }\n          if ([string]::IsNullOrWhiteSpace($env:CERT_THUMBPRINT)) {\n            if (\'${{ github.event_name }}\' -eq \'push\') {\n              throw "正式发布（tag push）必须配置 STELLA_CERT_THUMBPRINT；未签名产物不得发布"\n            }\n            Write-Host "::warning::未配置 STELLA_CERT_THUMBPRINT，产物保持未签名（仅非正式构建允许）"\n            exit 0\n          }\n          $ts = if ([string]::IsNullOrWhiteSpace($env:CERT_TIMESTAMP_URL)) { \'http://timestamp.digicert.com\' } else { $env:CERT_TIMESTAMP_URL }\n          signtool sign /fd SHA256 /td SHA256 /tr $ts /sha1 $env:CERT_THUMBPRINT $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "签名失败（退出码 $LASTEXITCODE）" }\n          signtool verify /pa /all $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "验签失败（退出码 $LASTEXITCODE）" }\n          Write-Host "已签名并验签：$($exes[0].Name)"\n\n      - name: 上传安装器\n        uses: actions/upload-artifact@v7\n        with:\n          name: stella-desktop-${{ matrix.profile }}-${{ matrix.payload }}\n          path: desktop/src-tauri/target/release/bundle/nsis/*setup.exe\n          if-no-files-found: error\n\n'

tests/test_release_layout.py:123: AssertionError
_________________ test_recover_stale_treats_pid_reuse_as_stale _________________
[gw2] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_recover_stale_treats_pid_0')

    def test_recover_stale_treats_pid_reuse_as_stale(tmp_path):
        """进程活着但创建身份与记录不符 = PID 被复用 → 陈旧，可恢复。"""
        import os
    
        lock_path = _write_lock_with_owner(tmp_path, os.getpid(), "win-creation-42")
>       assert UpgradeLock(tmp_path).recover_stale() is True
E       AssertionError: assert False is True
E        +  where False = recover_stale()
E        +    where recover_stale = <deploy.upgrade.UpgradeLock object at 0x7fc2fbb06d50>.recover_stale
E        +      where <deploy.upgrade.UpgradeLock object at 0x7fc2fbb06d50> = UpgradeLock(PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_recover_stale_treats_pid_0'))

tests/test_upgrade.py:137: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.16-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_release_layout.py::test_oneclick_rust_downloads_wheel_before_tauri_build - assert 'needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]' in '  build-installer:\n    needs: [resolve-release, publish-candidate, build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]\n    strategy:\n      fail-fast: false\n      matrix:\n        profile: [oneclick-python, oneclick-rust]\n        payload: [online, offline]\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@v4\n\n      # 显式 setup-python（WP06）：不依赖 runner 的默认 Python——runner 镜像\n      # 升级换掉默认版本时，staging 脚本会在用户机器之外先炸一次。\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \'3.12\'\n\n      # dashboard 产物必须在「准备 OneClick 内嵌程序资源」之前到位：\n      # staging 的 webui/dist 兜底读 desktop/dashboard-dist，晚于 staging 就\n      # 会打出面板整页缺失的安装包（v5.0.0 离线包实测，2026-09-25）。\n      - name: 下载 WebUI 前端产物（壳内资源 + Bot payload 各一份）\n        uses: actions/download-artifact@v7\n        with:\n          name: stella-dashboard-dist\n          path: desktop/dashboard-dist\n\n      - name: 拷入 Bot payload 的 webui/dist\n        shell: pwsh\n        run: |\n          New-Item -ItemType Directory -Force -Path webui/dist | Out-Null\n          Copy-Item desktop/dashboard-dist/* webui/dist/ -Recurse -Force\n\n      - name: 透传统一解析的发布版本\n.../nsis/*setup.exe\' -File)\n          if ($exes.Count -ne 1) { throw "必须恰好一个安装器，实际为 $($exes.Count)" }\n          if ([string]::IsNullOrWhiteSpace($env:CERT_THUMBPRINT)) {\n            if (\'${{ github.event_name }}\' -eq \'push\') {\n              throw "正式发布（tag push）必须配置 STELLA_CERT_THUMBPRINT；未签名产物不得发布"\n            }\n            Write-Host "::warning::未配置 STELLA_CERT_THUMBPRINT，产物保持未签名（仅非正式构建允许）"\n            exit 0\n          }\n          $ts = if ([string]::IsNullOrWhiteSpace($env:CERT_TIMESTAMP_URL)) { \'http://timestamp.digicert.com\' } else { $env:CERT_TIMESTAMP_URL }\n          signtool sign /fd SHA256 /td SHA256 /tr $ts /sha1 $env:CERT_THUMBPRINT $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "签名失败（退出码 $LASTEXITCODE）" }\n          signtool verify /pa /all $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "验签失败（退出码 $LASTEXITCODE）" }\n          Write-Host "已签名并验签：$($exes[0].Name)"\n\n      - name: 上传安装器\n        uses: actions/upload-artifact@v7\n        with:\n          name: stella-desktop-${{ matrix.profile }}-${{ matrix.payload }}\n          path: desktop/src-tauri/target/release/bundle/nsis/*setup.exe\n          if-no-files-found: error\n\n'
FAILED tests/test_upgrade.py::test_recover_stale_treats_pid_reuse_as_stale - AssertionError: assert False is True
 +  where False = recover_stale()
 +    where recover_stale = <deploy.upgrade.UpgradeLock object at 0x7fc2fbb06d50>.recover_stale
 +      where <deploy.upgrade.UpgradeLock object at 0x7fc2fbb06d50> = UpgradeLock(PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_recover_stale_treats_pid_0'))
============ 2 failed, 2862 passed, 21 skipped in 77.15s (0:01:17) =============
Error: Process completed with exit code 1.
# test 3.12
=================================== FAILURES ===================================
____________ test_oneclick_rust_downloads_wheel_before_tauri_build _____________
[gw2] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

    def test_oneclick_rust_downloads_wheel_before_tauri_build():
        """The slow installer build must consume an explicitly downloaded wheel.
    
        同时钉住 Offline 变体的管线结构：payload job 先行产出随包负载，installer
        matrix 带 payload 维度，收集步骤把 6 类资产全部落到 products/。
        """
        text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        installer = text[
            text.index("  build-installer:") : text.index("  build-rust-wheel:")
        ]
>       assert (
            "needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]"
            in installer
        )
E       assert 'needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]' in '  build-installer:\n    needs: [resolve-release, publish-candidate, build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]\n    strategy:\n      fail-fast: false\n      matrix:\n        profile: [oneclick-python, oneclick-rust]\n        payload: [online, offline]\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@v4\n\n      # 显式 setup-python（WP06）：不依赖 runner 的默认 Python——runner 镜像\n      # 升级换掉默认版本时，staging 脚本会在用户机器之外先炸一次。\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \'3.12\'\n\n      # dashboard 产物必须在「准备 OneClick 内嵌程序资源」之前到位：\n      # staging 的 webui/dist 兜底读 desktop/dashboard-dist，晚于 staging 就\n      # 会打出面板整页缺失的安装包（v5.0.0 离线包实测，2026-09-25）。\n      - name: 下载 WebUI 前端产物（壳内资源 + Bot payload 各一份）\n        uses: actions/download-artifact@v7\n        with:\n          name: stella-dashboard-dist\n          path: desktop/dashboard-dist\n\n      - name: 拷入 Bot payload 的 webui/dist\n        shell: pwsh\n        run: |\n          New-Item -ItemType Directory -Force -Path webui/dist | Out-Null\n          Copy-Item desktop/dashboard-dist/* webui/dist/ -Recurse -Force\n\n      - name: 透传统一解析的发布版本\n.../nsis/*setup.exe\' -File)\n          if ($exes.Count -ne 1) { throw "必须恰好一个安装器，实际为 $($exes.Count)" }\n          if ([string]::IsNullOrWhiteSpace($env:CERT_THUMBPRINT)) {\n            if (\'${{ github.event_name }}\' -eq \'push\') {\n              throw "正式发布（tag push）必须配置 STELLA_CERT_THUMBPRINT；未签名产物不得发布"\n            }\n            Write-Host "::warning::未配置 STELLA_CERT_THUMBPRINT，产物保持未签名（仅非正式构建允许）"\n            exit 0\n          }\n          $ts = if ([string]::IsNullOrWhiteSpace($env:CERT_TIMESTAMP_URL)) { \'http://timestamp.digicert.com\' } else { $env:CERT_TIMESTAMP_URL }\n          signtool sign /fd SHA256 /td SHA256 /tr $ts /sha1 $env:CERT_THUMBPRINT $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "签名失败（退出码 $LASTEXITCODE）" }\n          signtool verify /pa /all $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "验签失败（退出码 $LASTEXITCODE）" }\n          Write-Host "已签名并验签：$($exes[0].Name)"\n\n      - name: 上传安装器\n        uses: actions/upload-artifact@v7\n        with:\n          name: stella-desktop-${{ matrix.profile }}-${{ matrix.payload }}\n          path: desktop/src-tauri/target/release/bundle/nsis/*setup.exe\n          if-no-files-found: error\n\n'

tests/test_release_layout.py:123: AssertionError
_________________ test_recover_stale_treats_pid_reuse_as_stale _________________
[gw2] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_recover_stale_treats_pid_0')

    def test_recover_stale_treats_pid_reuse_as_stale(tmp_path):
        """进程活着但创建身份与记录不符 = PID 被复用 → 陈旧，可恢复。"""
        import os
    
        lock_path = _write_lock_with_owner(tmp_path, os.getpid(), "win-creation-42")
>       assert UpgradeLock(tmp_path).recover_stale() is True
E       AssertionError: assert False is True
E        +  where False = recover_stale()
E        +    where recover_stale = <deploy.upgrade.UpgradeLock object at 0x7f2bb456a8a0>.recover_stale
E        +      where <deploy.upgrade.UpgradeLock object at 0x7f2bb456a8a0> = UpgradeLock(PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_recover_stale_treats_pid_0'))

tests/test_upgrade.py:137: AssertionError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.14-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_release_layout.py::test_oneclick_rust_downloads_wheel_before_tauri_build - assert 'needs: [build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]' in '  build-installer:\n    needs: [resolve-release, publish-candidate, build-rust-wheel, build-oneclick-catalog-backend, build-offline-payload, build-dashboard]\n    strategy:\n      fail-fast: false\n      matrix:\n        profile: [oneclick-python, oneclick-rust]\n        payload: [online, offline]\n    runs-on: windows-latest\n    steps:\n      - uses: actions/checkout@v4\n\n      # 显式 setup-python（WP06）：不依赖 runner 的默认 Python——runner 镜像\n      # 升级换掉默认版本时，staging 脚本会在用户机器之外先炸一次。\n      - uses: actions/setup-python@v5\n        with:\n          python-version: \'3.12\'\n\n      # dashboard 产物必须在「准备 OneClick 内嵌程序资源」之前到位：\n      # staging 的 webui/dist 兜底读 desktop/dashboard-dist，晚于 staging 就\n      # 会打出面板整页缺失的安装包（v5.0.0 离线包实测，2026-09-25）。\n      - name: 下载 WebUI 前端产物（壳内资源 + Bot payload 各一份）\n        uses: actions/download-artifact@v7\n        with:\n          name: stella-dashboard-dist\n          path: desktop/dashboard-dist\n\n      - name: 拷入 Bot payload 的 webui/dist\n        shell: pwsh\n        run: |\n          New-Item -ItemType Directory -Force -Path webui/dist | Out-Null\n          Copy-Item desktop/dashboard-dist/* webui/dist/ -Recurse -Force\n\n      - name: 透传统一解析的发布版本\n.../nsis/*setup.exe\' -File)\n          if ($exes.Count -ne 1) { throw "必须恰好一个安装器，实际为 $($exes.Count)" }\n          if ([string]::IsNullOrWhiteSpace($env:CERT_THUMBPRINT)) {\n            if (\'${{ github.event_name }}\' -eq \'push\') {\n              throw "正式发布（tag push）必须配置 STELLA_CERT_THUMBPRINT；未签名产物不得发布"\n            }\n            Write-Host "::warning::未配置 STELLA_CERT_THUMBPRINT，产物保持未签名（仅非正式构建允许）"\n            exit 0\n          }\n          $ts = if ([string]::IsNullOrWhiteSpace($env:CERT_TIMESTAMP_URL)) { \'http://timestamp.digicert.com\' } else { $env:CERT_TIMESTAMP_URL }\n          signtool sign /fd SHA256 /td SHA256 /tr $ts /sha1 $env:CERT_THUMBPRINT $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "签名失败（退出码 $LASTEXITCODE）" }\n          signtool verify /pa /all $exes[0].FullName\n          if ($LASTEXITCODE -ne 0) { throw "验签失败（退出码 $LASTEXITCODE）" }\n          Write-Host "已签名并验签：$($exes[0].Name)"\n\n      - name: 上传安装器\n        uses: actions/upload-artifact@v7\n        with:\n          name: stella-desktop-${{ matrix.profile }}-${{ matrix.payload }}\n          path: desktop/src-tauri/target/release/bundle/nsis/*setup.exe\n          if-no-files-found: error\n\n'
FAILED tests/test_upgrade.py::test_recover_stale_treats_pid_reuse_as_stale - AssertionError: assert False is True
 +  where False = recover_stale()
 +    where recover_stale = <deploy.upgrade.UpgradeLock object at 0x7f2bb456a8a0>.recover_stale
 +      where <deploy.upgrade.UpgradeLock object at 0x7f2bb456a8a0> = UpgradeLock(PosixPath('/tmp/pytest-of-runner/pytest-0/popen-gw2/test_recover_stale_treats_pid_0'))
============ 2 failed, 2862 passed, 21 skipped in 76.75s (0:01:16) =============
Error: Process completed with exit code 1.
1s
1s
