"""Command line entry point: `floatnote <command>`."""

import argparse
import sys

from . import __version__, client

# Commands forwarded to the running daemon. name -> help text
DAEMON_COMMANDS = {
    "toggle-bug": "start/stop recording a bug (session) note",
    "toggle-idea": "start/stop recording an idea note",
    "copy-all": "copy bug notes to the clipboard for Claude, then clear the list",
    "undo": "restore the last archived batch of notes",
    "clear": "archive session notes without copying them",
    "show": "show/hide the FloatNote window",
    "home": "show the window on the Ideas tab",
    "status": "show what the daemon is doing",
    "quit": "stop the daemon",
    "next-project": "switch to the next project",
}
# These start the daemon first if it isn't running (so a hotkey always works).
NO_AUTOSTART = {"status", "quit"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="floatnote",
        description="Hotkey voice notes for Linux, ready to paste into Claude Code.",
    )
    p.add_argument("--version", action="version", version=f"floatnote {__version__}")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    for name, help_text in DAEMON_COMMANDS.items():
        aliases = ["paste-all"] if name == "copy-all" else []  # old name still works
        sub.add_parser(name, help=help_text, aliases=aliases)

    fp = sub.add_parser("fix", help="always correct a misheard word, e.g. fix \"white tail\" Wagtail")
    fp.add_argument("wrong", nargs="?", help="what Whisper writes")
    fp.add_argument("right", nargs="?", help="what you actually said")
    fp.add_argument("--remove", metavar="WRONG", help="stop correcting this word")

    mp = sub.add_parser("model", help="show or change the speech model")
    mp.add_argument("name", nargs="?", help="model to switch to (e.g. small.en, base.en)")
    mp.add_argument("--beam", type=int, choices=[1, 5], help="beam size: 1 = faster, 5 = more accurate")

    lp = sub.add_parser("list", help="print a project's bugs (for Claude Code); works without the daemon")
    lp.add_argument("--project", metavar="NAME", help="which project (default: the one linked to this "
                    "folder, else the active one)")
    lp.add_argument("--take", action="store_true", help="also clear them, like Copy all (undo restores)")
    lp.add_argument("--ideas", action="store_true", help="list open ideas instead")
    lp.add_argument("--json", action="store_true", help="print JSON")

    sub.add_parser("projects", help="list projects")
    pp = sub.add_parser("project", help="show or switch the active project")
    pp.add_argument("name", nargs="?", help="project to switch to")

    dp = sub.add_parser("daemon", help="run the background daemon (used by autostart)")
    dp.add_argument("--login", action="store_true", help="started at login: show open ideas")
    dp.add_argument("--headless", action="store_true", help="no windows, hotkeys and clipboard only")

    sp = sub.add_parser("setup-shortcuts", help="add FloatNote keyboard shortcuts to GNOME")
    sp.add_argument("--remove", action="store_true", help="remove them instead")
    sp.add_argument("--launcher", help="command the shortcuts run (default: this floatnote)")
    sub.add_parser("doctor", help="check this machine has what FloatNote needs")

    bp = sub.add_parser("bench", help="compare speech models on your own voice")
    bsub = bp.add_subparsers(dest="bench_command", metavar="<step>", required=True)
    br = bsub.add_parser("record", help="read sample bug notes aloud and save them")
    br.add_argument("-n", type=int, default=5, choices=range(1, 6), metavar="N",
                    help="number of clips (1-5, default 5)")
    brun = bsub.add_parser("run", help="time each model on the recorded clips")
    brun.add_argument("files", nargs="*", help="audio files (default: recorded clips)")
    return p


def _open_store():
    from . import paths
    from .store import Store

    return Store(paths.db_file(), export_path=paths.ideas_export_file())


def _resolve_project(store, name: str | None):
    """--project NAME, else the project linked to this folder, else the active one."""
    import os

    if name:
        project = store.project_by_name(name)
        if project is None:
            names = ", ".join(p.name for p in store.projects())
            raise SystemExit(f"floatnote: no project called {name!r} (projects: {names})")
        return project
    return store.project_for_folder(os.getcwd()) or store.project(store.active_project_id())


def _list(ideas: bool, as_json: bool, project_name: str | None = None, take: bool = False) -> int:
    """Print notes straight from the database (no daemon needed)."""
    import json

    store = _open_store()
    try:
        if ideas:
            notes = store.ideas()
            if as_json:
                print(json.dumps([n.to_dict() for n in notes], indent=2))
            elif not notes:
                print("No open ideas.")
            else:
                for i, n in enumerate(notes, 1):
                    print(f"{i}. {n.text} ({n.created_at[:10]})")
            return 0

        project = _resolve_project(store, project_name)
        if take:
            try:  # through the app, so its window and icon update too
                reply = client.send("take", project_id=project.id)
            except client.DaemonNotRunning:
                reply = None
            except (OSError, ValueError) as e:  # timeout, broken reply
                print(f"floatnote: no answer from FloatNote ({e}). If the bugs left the list, "
                      "Undo in FloatNote brings them back.", file=sys.stderr)
                return 1
            if reply is not None and not reply.get("ok"):
                print(f"floatnote: {reply.get('error', 'take failed')}", file=sys.stderr)
                return 1
            if reply is not None:
                texts = reply["notes"]
            else:
                notes = store.session_notes(project.id)
                if notes:
                    store.archive_session([n.id for n in notes])
                texts = [n.text for n in notes]
        else:
            texts = [n.text for n in store.session_notes(project.id)]
    finally:
        store.close()

    if as_json:
        print(json.dumps({"project": project.name, "bugs": texts}, indent=2))
    elif not texts:
        print(f"Project: {project.name}\nNo bugs waiting.")
    else:
        print(f"Project: {project.name}")
        for i, text in enumerate(texts, 1):
            print(f"{i}. {text}")
    return 0


def _projects() -> int:
    store = _open_store()
    try:
        active = store.active_project_id()
        counts = store.bug_counts()
        for p in store.projects():
            mark = "*" if p.id == active else " "
            folder = f"   {p.folder}" if p.folder else ""
            print(f" {mark} {p.name:<24} {counts.get(p.id, 0):>3} bug(s){folder}")
    finally:
        store.close()
    return 0


def _project(name: str | None) -> int:
    if name is None:
        store = _open_store()
        try:
            print(store.project(store.active_project_id()).name)
        finally:
            store.close()
        return 0
    try:
        reply = client.send("set-project", name=name)
    except client.DaemonNotRunning:
        store = _open_store()
        try:
            project = store.project_by_name(name)
            if project is None:
                reply = {"ok": False, "error": f"no project called {name!r}"}
            else:
                store.set_active_project(project.id)
                reply = {"ok": True, "message": f"project: {project.name}"}
        finally:
            store.close()
    if not reply.get("ok"):
        print(f"floatnote: {reply.get('error')}", file=sys.stderr)
        return 1
    print(reply["message"])
    return 0


def _setup_shortcuts(remove: bool, launcher: str | None) -> int:
    import os
    import shutil
    import subprocess

    from . import shortcuts
    from .env import clean_snap_env

    clean_snap_env()  # gsettings breaks with the VS Code snap's schema dir
    try:
        if remove:
            print(f"Removed {shortcuts.remove()} FloatNote shortcut(s).")
            return 0
        import shlex

        launcher = shlex.quote(launcher or os.path.abspath(shutil.which(sys.argv[0]) or sys.argv[0]))
        print("Keyboard shortcuts (change them in Settings > Keyboard > Custom Shortcuts):")
        from . import config

        cfg = config.load()
        for line in shortcuts.install(launcher, cfg.toggle_keys, cfg.next_project_keys):
            print("  " + line)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"floatnote: could not change GNOME shortcuts: {e}", file=sys.stderr)
        return 1
    return 0


def _reexec_with_input_group(argv: list[str]) -> None:
    """If the user joined the 'input' group but this login session doesn't have
    it yet (Ubuntu keeps the old groups until a reboot), restart under `sg input`
    so hold-to-record works right away."""
    import grp
    import os
    import pwd
    import shlex
    import shutil

    if os.environ.get("FLOATNOTE_SG"):
        return
    try:
        group = grp.getgrnam("input")
        user = pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return
    if group.gr_gid in os.getgroups() or user not in group.gr_mem or not shutil.which("sg"):
        return
    os.environ["FLOATNOTE_SG"] = "1"
    cmd = shlex.join([sys.executable, "-m", "floatnote", *argv])
    os.execvp("sg", ["sg", "input", "-c", cmd])


def _fix(wrong: str | None, right: str | None, remove: str | None) -> int:
    from . import config

    cfg = config.load()
    fixes = dict(cfg.replacements)
    if remove:
        if fixes.pop(remove.lower(), None) is None:
            print(f"floatnote: no fix for {remove!r}", file=sys.stderr)
            return 1
        config.set_values({"replacements": fixes})
        print(f"Removed fix for {remove!r}.")
    elif wrong and right:
        fixes[wrong.lower()] = right
        vocab = cfg.vocabulary if right in cfg.vocabulary else [*cfg.vocabulary, right]
        config.set_values({"replacements": fixes, "vocabulary": vocab})
        print(f'Will now write "{right}" whenever it hears "{wrong}".')
    elif wrong or right:
        print('floatnote: give both words, e.g.  floatnote fix "white tail" Wagtail', file=sys.stderr)
        return 1
    if not fixes:
        print('No word fixes yet. Add one:  floatnote fix "white tail" Wagtail')
    elif not (wrong and right) and not remove:
        print("Word fixes (heard -> written):")
        for w, r in fixes.items():
            print(f"  {w!r:<24} -> {r}")
    if (wrong and right) or remove:
        _restart_if_running()
    return 0


def _restart_if_running() -> None:
    import time

    if client.is_running():
        client.send("quit")
        time.sleep(1)
        client.start_daemon()
        print("FloatNote restarted to apply it.")


def _model(name: str | None, beam: int | None) -> int:
    from . import config

    cfg = config.load()
    if name is None and beam is None:
        print(f"Current model: {cfg.model} (beam {cfg.beam_size})\n")
        for model, about in config.MODELS.items():
            mark = "*" if model == cfg.model else " "
            print(f" {mark} {model:<16} {about}")
        print("\nSwitch with: floatnote model <name>      Compare on your voice: floatnote bench run")
        return 0
    if name is not None and name not in config.MODELS:
        print(f"floatnote: unknown model {name!r}. Choose from: {', '.join(config.MODELS)}", file=sys.stderr)
        return 1
    name = name or cfg.model
    print(f"Getting {name} (downloads once, can take a few minutes)...")
    from faster_whisper.utils import download_model

    download_model(name)
    config.set_values({"model": name, **({"beam_size": beam} if beam else {})})
    print(f"Model set to {name}" + (f", beam {beam}" if beam else ""))
    _restart_if_running()
    return 0


def main(argv: list[str] | None = None) -> int:
    import os

    os.umask(0o077)  # anything FloatNote writes is readable by you only
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "doctor":
        from . import doctor

        return doctor.run()

    if args.command == "daemon":
        from .env import clean_snap_env

        clean_snap_env()  # before anything imports GTK
        _reexec_with_input_group(sys.argv[1:] if argv is None else argv)
        from . import config, daemon

        return daemon.run(config.load(), login=args.login, headless=args.headless)

    if args.command == "setup-shortcuts":
        return _setup_shortcuts(args.remove, args.launcher)

    if args.command == "bench":
        from . import bench

        if args.bench_command == "record":
            return bench.record(args.n)
        return bench.run(args.files)

    if args.command == "fix":
        return _fix(args.wrong, args.right, args.remove)

    if args.command == "model":
        return _model(args.name, args.beam)

    if args.command == "list":
        return _list(ideas=args.ideas, as_json=args.json, project_name=args.project, take=args.take)

    if args.command == "projects":
        return _projects()

    if args.command == "project":
        return _project(args.name)

    try:
        reply = client.send(args.command)
    except client.DaemonNotRunning:
        if args.command in NO_AUTOSTART or not client.start_daemon():
            print("floatnote: daemon is not running (start it with: floatnote daemon)", file=sys.stderr)
            return 1
        reply = client.send(args.command)
    if not reply.get("ok", False):
        print(f"floatnote: {reply.get('error', 'command failed')}", file=sys.stderr)
        return 1
    if reply.get("message"):
        print(reply["message"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
