"""One command: increment version, validate, build, commit, tag and push."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def run(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", required=True, help="Release notes and commit message")
    parser.add_argument("--bump", choices=("patch", "minor", "major"), default="patch")
    parser.add_argument("--current", action="store_true", help="Publish current version without bumping")
    args = parser.parse_args()
    if not args.message.strip():
        parser.error("message must not be empty")
    remote = run("git", "remote", "get-url", "origin", capture=True).strip()
    if not re.fullmatch(r"(?:https://github\.com/|git@github\.com:)[\w.-]+/[\w.-]+(?:\.git)?", remote):
        raise RuntimeError("origin must point to the intended GitHub repository")
    version_file = ROOT / "version.py"
    current = re.fullmatch(r'VERSION = "(\d+\.\d+\.\d+)"\s*', version_file.read_text()).group(1)
    parts = list(map(int, current.split(".")))
    if not args.current:
        index = {"major": 0, "minor": 1, "patch": 2}[args.bump]
        parts[index] += 1
        for i in range(index + 1, 3):
            parts[i] = 0
    version = ".".join(map(str, parts))
    tag = f"v{version}"
    if run("git", "tag", "--list", tag, capture=True).strip():
        raise RuntimeError(f"Tag {tag} already exists")
    # Verify remote access and prevent reusing an existing release tag before edits.
    if run("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}", capture=True).strip():
        raise RuntimeError(f"Remote tag {tag} already exists")
    if not args.current:
        version_file.write_text(f'VERSION = "{version}"\n', encoding="utf-8")
        changelog = ROOT / "CHANGELOG.md"
        original = changelog.read_text(encoding="utf-8")
        date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        heading, body = original.split("\n", 1)
        changelog.write_text(f"{heading}\n\n## {version} — {date}\n\n- {args.message.strip()}\n{body}", encoding="utf-8")
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v")
    run(sys.executable, "tests/smoke_gui.py")
    run(sys.executable, "build.py")
    run("git", "add", "--all")
    run("git", "commit", "-m", f"Release {tag}: {args.message.strip()}")
    run("git", "tag", "-a", tag, "-m", args.message.strip())
    run("git", "push", "--atomic", "--set-upstream", "origin", "HEAD", f"refs/tags/{tag}")
    print(f"Synced {tag}. Check GitHub Actions / Releases for the EXE publication status.")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Release stopped: {exc}. Local changes and build artifacts are preserved.", file=sys.stderr)
        sys.exit(1)
