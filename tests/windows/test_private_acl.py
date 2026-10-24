from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native ACL matrix")


def test_private_acl_accepts_current_user_sid(tmp_path):
    from stella_bootstrap.config import (
        _check_windows_private_acl,
        _set_windows_private_acl,
    )

    path = tmp_path / "revision.json"
    path.write_text("{}", encoding="utf-8")
    _set_windows_private_acl(path, is_directory=False)

    _check_windows_private_acl(path)


def test_private_acl_rejects_a_second_account(tmp_path):
    import ntsecuritycon
    import win32security

    from stella_bootstrap.config import (
        ConfigRevisionError,
        _check_windows_private_acl,
        _set_windows_private_acl,
    )

    path = tmp_path / "revision.json"
    path.write_text("{}", encoding="utf-8")
    _set_windows_private_acl(path, is_directory=False)

    descriptor = win32security.GetFileSecurity(
        str(path), win32security.DACL_SECURITY_INFORMATION
    )
    dacl = descriptor.GetSecurityDescriptorDacl()
    everyone = win32security.ConvertStringSidToSid("S-1-1-0")
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION, ntsecuritycon.FILE_READ_DATA, everyone
    )
    descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
    win32security.SetFileSecurity(
        str(path), win32security.DACL_SECURITY_INFORMATION, descriptor
    )

    with pytest.raises(ConfigRevisionError, match="another account"):
        _check_windows_private_acl(path)
