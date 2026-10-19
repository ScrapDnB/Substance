"""The QML debug service must stay opt-in and unavailable in release packages."""
import sys

import pytest

from substance import app as entry


def test_debugger_argument_cannot_enable_preview_implicitly(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['Substance', '-qmljsdebugger=port:3768'])
    with pytest.raises(SystemExit) as result:
        entry.main()
    assert result.value.code == 2
    assert 'requires --qml-preview' in capsys.readouterr().err


def test_preview_is_disabled_in_packaged_application(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['Substance', '--qml-preview'])
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    with pytest.raises(SystemExit) as result:
        entry.main()
    assert result.value.code == 2
    assert 'only when running from source' in capsys.readouterr().err
