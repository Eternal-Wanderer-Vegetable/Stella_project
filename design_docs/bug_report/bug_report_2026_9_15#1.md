# test 3.10
=================================== FAILURES ===================================
____________ test_oneclick_rust_downloads_wheel_before_tauri_build _____________
[gw2] linux -- Python 3.10.21 /opt/hostedtoolcache/Python/3.10.21/x64/bin/python

    def test_oneclick_rust_downloads_wheel_before_tauri_build():
        """The slow installer build must consume an explicitly downloaded wheel."""
        text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        installer = text[
            text.index("  build-installer:") : text.index("  build-rust-wheel:")
        ]
        assert "needs: [build-rust-wheel, build-oneclick-catalog-backend]" in installer
>       download = installer.index("uses: actions/download-artifact@v4")
E       ValueError: substring not found

tests/test_release_layout.py:112: ValueError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.10.21-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_release_layout.py::test_oneclick_rust_downloads_wheel_before_tauri_build - ValueError: substring not found
================= 1 failed, 1978 passed, 17 skipped in 54.82s ==================
Error: Process completed with exit code 1.
# test 3.11
=================================== FAILURES ===================================
____________ test_oneclick_rust_downloads_wheel_before_tauri_build _____________
[gw1] linux -- Python 3.11.16 /opt/hostedtoolcache/Python/3.11.16/x64/bin/python

    def test_oneclick_rust_downloads_wheel_before_tauri_build():
        """The slow installer build must consume an explicitly downloaded wheel."""
        text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        installer = text[
            text.index("  build-installer:") : text.index("  build-rust-wheel:")
        ]
        assert "needs: [build-rust-wheel, build-oneclick-catalog-backend]" in installer
>       download = installer.index("uses: actions/download-artifact@v4")
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       ValueError: substring not found

tests/test_release_layout.py:112: ValueError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.11.16-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_release_layout.py::test_oneclick_rust_downloads_wheel_before_tauri_build - ValueError: substring not found
================= 1 failed, 1978 passed, 17 skipped in 57.83s ==================
Error: Process completed with exit code 1.
# test 3.12
=================================== FAILURES ===================================
____________ test_oneclick_rust_downloads_wheel_before_tauri_build _____________
[gw3] linux -- Python 3.12.14 /opt/hostedtoolcache/Python/3.12.14/x64/bin/python

    def test_oneclick_rust_downloads_wheel_before_tauri_build():
        """The slow installer build must consume an explicitly downloaded wheel."""
        text = (PROJECT_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        installer = text[
            text.index("  build-installer:") : text.index("  build-rust-wheel:")
        ]
        assert "needs: [build-rust-wheel, build-oneclick-catalog-backend]" in installer
>       download = installer.index("uses: actions/download-artifact@v4")
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       ValueError: substring not found

tests/test_release_layout.py:112: ValueError
================================ tests coverage ================================
_______________ coverage: platform linux, python 3.12.14-final-0 _______________

Coverage XML written to file coverage.xml
=========================== short test summary info ============================
FAILED tests/test_release_layout.py::test_oneclick_rust_downloads_wheel_before_tauri_build - ValueError: substring not found
============ 1 failed, 1978 passed, 17 skipped in 60.10s (0:01:00) =============
Error: Process completed with exit code 1.
