import builtins

from jira_test.cli import main, parser


def test_gui_parser_preserves_cli_and_accepts_workspace():
    args = parser().parse_args(["gui", "--workspace", "/tmp/studio"])
    assert str(args.workspace) == "/tmp/studio"
    assert parser().parse_args(["validate", "--suite", "cases"]).command == "validate"


def test_missing_tk_returns_actionable_error(monkeypatch, capsys):
    original = builtins.__import__

    def no_tk(name, *args, **kwargs):
        if name == "tkinter":
            raise ImportError("No _tkinter")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_tk)
    assert main(["gui"]) == 2
    assert "Tk" in capsys.readouterr().out
