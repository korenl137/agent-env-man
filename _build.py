"""Copy canonical user documentation into wheels without changing source files."""

from pathlib import Path
import shutil

from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def documentation_mapping(self):
        """Map installed resources to the same sources used by checkout readers."""
        root = Path(__file__).resolve().parent
        sources = [root / "README.md", root / "LICENSE.txt"]
        sources.extend(sorted((root / "docs").glob("*.md")))
        sources.extend(sorted((root / "examples").glob("*.toml")))
        destination = Path(self.build_lib) / "agent_env_man" / "_documentation"
        return {str(destination / path.relative_to(root)): str(path.relative_to(root))
                for path in sources}

    def run(self):
        super().run()
        # Editable installs read canonical sources through the runtime locator.
        # Clean only our generated tree so removed documents cannot leak into a
        # later wheel through a reused build directory.
        if not self.editable_mode:
            destination = Path(self.build_lib) / "agent_env_man" / "_documentation"
            if destination.exists():
                shutil.rmtree(destination)
            for target, source in self.documentation_mapping().items():
                self.mkpath(str(Path(target).parent))
                self.copy_file(source, target)

    def get_source_files(self):
        return super().get_source_files() + list(self.documentation_mapping().values())

    def get_outputs(self, include_bytecode=1):
        return super().get_outputs(include_bytecode) + list(self.documentation_mapping())

    def get_output_mapping(self):
        return {**super().get_output_mapping(), **self.documentation_mapping()}
