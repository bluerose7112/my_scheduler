"""Version string: `tag`, `tag(+N)` (N commits after tag), trailing `+` = dirty."""
import re
import subprocess
from pathlib import Path

try:
    from ._version import VERSION as _BAKED
except ImportError:
    _BAKED = None


def format_describe(desc: str) -> str:
    """Convert `git describe --tags --long --dirty` output to display form."""
    dirty = desc.endswith("-dirty")
    if dirty:
        desc = desc[: -len("-dirty")]
    m = re.match(r"^(.*)-(\d+)-g[0-9a-f]+$", desc)
    if m:
        tag, n = m.group(1), int(m.group(2))
        out = tag if n == 0 else f"{tag}(+{n})"
    else:  # no tags: bare commit hash
        out = f"untagged-{desc}"
    return out + ("+" if dirty else "")


def git_version(cwd: Path | None = None) -> str | None:
    try:
        r = subprocess.run(
            ["git", "describe", "--tags", "--long", "--dirty", "--always"],
            cwd=cwd, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return format_describe(r.stdout.strip())


def get_version() -> str:
    if _BAKED:
        return _BAKED
    return git_version(Path(__file__).resolve().parent) or "dev"
