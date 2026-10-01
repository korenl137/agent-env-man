#!/usr/bin/env python3
"""Verify an installed wheel without development dependencies or live integrations."""

import argparse
from importlib import metadata, util
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify():
    """Check runtime isolation and local operations in the target interpreter.

    All operation paths and user-profile locations are temporary.
    This checks wheel behavior, not native platform readiness or remote delivery.
    """
    for module in ("coverage", "setuptools"):
        require(util.find_spec(module) is None, f"Runtime environment contains development dependency: {module}")
    import agent_env_man
    package = Path(agent_env_man.__file__).resolve()
    require(Path(sys.prefix).resolve() in package.parents, "AEM must be installed inside the target environment")
    distribution = metadata.distribution("agent-env-man")
    origin = json.loads(distribution.read_text("direct_url.json") or "{}")
    require(not origin.get("dir_info", {}).get("editable"), "Use an installed wheel, not an editable checkout")

    with tempfile.TemporaryDirectory(prefix="aem-runtime-") as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        markers = {home / ".bashrc": b"preserve bash\n", home / ".zshrc": b"preserve zsh\n"}
        for path, content in markers.items():
            path.write_bytes(content)
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update(HOME=str(home), USERPROFILE=str(home),
                           XDG_CONFIG_HOME=str(home / ".config"), CODEX_HOME=str(home / ".codex"),
                           APPDATA=str(home / "AppData/Roaming"), LOCALAPPDATA=str(home / "AppData/Local"),
                           GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_ALLOW_PROTOCOL="file", GIT_TEMPLATE_DIR="")
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        environment["PYTHONNOUSERSITE"] = "1"
        config = root / "machine.toml"

        def cli(*arguments, code=0, selected_config=config):
            # -I ignores ambient PYTHONPATH and user-site packages; cwd is
            # outside the checkout so imports must come from the wheel.
            result = subprocess.run([sys.executable, "-I", "-m", "agent_env_man", "--json",
                                     "--config", str(selected_config), *map(str, arguments)],
                                    cwd=root, env=environment, capture_output=True, text=True, timeout=30)
            require(result.returncode == code,
                    f"{arguments}: expected exit {code}, got {result.returncode}\n{result.stdout}\n{result.stderr}")
            return result.stdout

        invalid = root / "invalid.toml"
        invalid.write_text("invalid TOML [", encoding="utf-8")
        executable = Path(sysconfig.get_path("scripts")) / ("aem.exe" if os.name == "nt" else "aem")
        require(executable.is_file(), "Installed aem console entrypoint is missing")
        help_result = subprocess.run([str(executable), "--config", str(invalid), "--help"],
                                     cwd=root, env=environment, capture_output=True, text=True, timeout=30)
        require(help_result.returncode == 0 and "Usage:" in help_result.stdout,
                f"Installed console help failed: {help_result.stderr}")
        require("Usage:" in cli("--help", selected_config=invalid), "CLI help is unavailable")
        docs = json.loads(cli("docs", selected_config=invalid))
        docs_root = Path(docs["root"])
        require(package.parent in docs_root.parents, "Documentation must come from the installed wheel")
        for resource in ("README.md", "LICENSE.txt", "docs/commands.md", "examples/skills.toml"):
            require((docs_root / resource).is_file(), f"Missing installed resource: {resource}")
        require(not Path(str(invalid) + ".state").exists(), "Help/docs touched invalid configuration state")

        source = root / "repository"
        source.mkdir()
        skill = b"---\nname: smoke\ndescription: Local runtime verification\n---\n\nTest content.\n"
        (source / "SKILL.md").write_bytes(skill)
        for arguments in (("init", "-b", "main"), ("add", "SKILL.md"),
                          ("-c", "user.name=AEM runtime check", "-c", "user.email=runtime@example.invalid",
                           "commit", "-m", "Local fixture")):
            subprocess.run(["git", "-C", str(source), "-c", f"core.hooksPath={os.devnull}", *arguments],
                           cwd=root, env=environment, check=True, capture_output=True, text=True, timeout=30)
        catalog = root / "catalog.toml"
        catalog.write_text('version = 2\n[sources.fixture]\ntype = "git"\n'
                           f'repository = {json.dumps(str(source), ensure_ascii=False)}\n'
                           '[skills.smoke]\nsource = "fixture"\n[skills.smoke.install]\nmode = "copy"\n',
                           encoding="utf-8")
        destination = root / "skills"
        cli("bootstrap", catalog, "--checkout-root", root / "checkouts",
            "--root", f"skills={destination}", "--root", f"agent={home / '.codex'}")
        target = destination / "smoke"
        require(not target.exists(), "Bootstrap installed content before apply")
        cli("apply")
        require((target / "SKILL.md").read_bytes() == skill, "Apply did not install the selected payload")
        json.loads(cli("status"))
        (target / "local.txt").write_bytes(b"preserve local edit")
        cli("apply", code=1)
        require((target / "local.txt").read_bytes() == b"preserve local edit", "Apply lost local edits")
        cli("detach", "smoke")
        require((target / "local.txt").read_bytes() == b"preserve local edit", "Detach lost local edits")
        state = json.loads((Path(str(config) + ".state") / "state.json").read_text(encoding="utf-8"))
        require(state["items"]["smoke"].get("detached"), "Detach did not release ownership")
        for path, content in markers.items():
            require(path.read_bytes() == content, "Runtime verification changed a shell profile")
        require(not (home / ".codex/hooks.json").exists(), "Runtime verification registered agent hooks")
    print(f"Verified agent-env-man {distribution.version}: installed runtime without development dependencies")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True, help="Python in a clean environment with the wheel installed")
    options = parser.parse_args(argv)
    try:
        # Venv Python may be a symlink to the base interpreter: resolving it
        # would discard the environment whose installation we need to check.
        interpreter = options.python.expanduser().absolute()
        require(interpreter.is_file(), f"Runtime Python is missing: {interpreter}")
        # Keep the verification body in this file so the target only needs
        # the installed runtime and the standard library, not test helpers.
        command = [str(interpreter), "-I", "-c",
                   "import runpy; runpy.run_path(__import__('sys').argv[1])['verify']()", str(Path(__file__).resolve())]
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if result.stdout:
            print(result.stdout, end="")
        if result.returncode:
            print(result.stderr, file=sys.stderr, end="")
        return result.returncode
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Runtime verification: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
