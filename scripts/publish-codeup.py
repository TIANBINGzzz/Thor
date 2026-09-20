"""Build a filtered Codeup snapshot; pass --push to publish it."""

import argparse
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RELEASE_REF = "refs/heads/codex/codeup-release"


def git(*args, env=None, input=None):
    return subprocess.run(
        ["git", *args], cwd=ROOT, env=env, input=input,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    ).stdout


def excluded(name):
    path = PurePosixPath(name)
    if path.parts[0].lower() in {"doc", "docs"}:
        return True
    if path.name.lower() in {"agent.md", "agents.md", "claude.md"}:
        return True
    if path.name.lower() == "readme.md":
        return True
    return path.suffix.lower() in {".md", ".mdx", ".rst"} and not name.startswith(".claude/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--version", default="V1.0.0")
    parser.add_argument("--product-version", default="v1.0.0")
    parser.add_argument("--changes", default="sdk调用测试")
    args = parser.parse_args()
    # 发布说明保持三行；版本和更新内容可由每次发布传入。
    for value in (args.version, args.product_version, args.changes):
        if not value.strip() or any(c in value for c in "\r\n"):
            parser.error("Release fields must be nonempty single-line values.")
    message = f"版本编号:[{args.version}]\n产品版本:[{args.product_version}]\n更新内容：{args.changes}"
    if git("status", "--porcelain").strip():
        raise SystemExit("Commit local changes before building the Codeup snapshot.")
    source = git("rev-parse", "HEAD").decode().strip()
    if git("symbolic-ref", "HEAD").decode().strip() == RELEASE_REF:
        raise SystemExit("Run this script from the complete source branch.")
    git("fetch", "codeup", "refs/heads/main")
    parent = git("rev-parse", "FETCH_HEAD").decode().strip()
    paths = git("ls-tree", "-r", "--name-only", "-z", source).decode().split("\0")
    removed = [name for name in paths if name and excluded(name)]
    # A separate index leaves the source checkout and its staging area intact.
    with tempfile.TemporaryDirectory(prefix="codeup-publish-") as directory:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(directory) / "index")}
        git("read-tree", source, env=env)
        if removed:
            git("update-index", "--force-remove", "-z", "--stdin", env=env,
                input=("\0".join(removed) + "\0").encode())
        tree = git("write-tree", env=env).decode().strip()
    remaining = git("ls-tree", "-r", "--name-only", "-z", tree).decode().split("\0")
    if any(excluded(name) for name in remaining if name):
        raise SystemExit("Filtered snapshot validation failed.")
    if (tree == git("rev-parse", f"{parent}^{{tree}}").decode().strip()
            and git("show", "-s", "--format=%B", parent).decode("utf-8").strip() == message):
        commit = parent
    else:
        commit = git("commit-tree", tree, "-p", parent, "-F", "-",
                     input=message.encode("utf-8")).decode().strip()
    git("update-ref", RELEASE_REF, commit)
    print(f"Source: {source}\nRelease: {commit}\nExcluded: {len(removed)} files")
    for name in removed:
        print(f"  {name}")
    if args.push:
        # A normal fast-forward push rejects concurrent remote changes.
        git("push", "codeup", f"{RELEASE_REF}:refs/heads/main")
        remote = git("ls-remote", "codeup", "refs/heads/main").decode().split()[0]
        if remote != commit:
            raise SystemExit("Remote verification failed.")
        print("Published and verified Codeup main.")
    else:
        print("Local release prepared. Use --push to publish.")


if __name__ == "__main__":
    main()
