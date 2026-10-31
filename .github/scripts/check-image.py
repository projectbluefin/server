#!/usr/bin/env python3
"""Check an exported image set (dist/diskless/) for broken references.

Pruning /usr or the initrd must not break anything that ships. For the /usr
image, the initrd inside the disk UKI, and every sysext merged over /usr, this
fails when:

* an ELF file's DT_NEEDED library is missing,
* a .note.dlopen entry marked "required" names a missing library, or
* a unit's Exec*= or a udev rule's RUN/PROGRAM/IMPORT{program} names a
  program that is missing.

With --baseline-usr (a previous release's *.usr.raw) it also prints which
/usr paths were added and removed, to $GITHUB_STEP_SUMMARY when set.

Needs readelf, zstd, cpio and fsck.erofs (erofs-utils) on PATH.
"""


import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

USR_MERGE = {"bin": "usr/bin", "sbin": "usr/bin", "lib": "usr/lib", "lib64": "usr/lib"}
UNIT_DIRS = (
    "usr/lib/systemd/system",
    "usr/lib/systemd/user",
    "usr/share/factory/etc/systemd/system",
    "etc/systemd/system",
)
RULE_DIRS = ("usr/lib/udev/rules.d", "usr/share/factory/etc/udev/rules.d", "etc/udev/rules.d")
EXEC_RE = re.compile(r"^\s*Exec[A-Za-z]*\s*=\s*(.*)$")
CONDITION_RE = re.compile(r"^\s*Condition(?:PathExists|PathIsExecutable|FileIsExecutable)\s*=\s*(/\S+)", re.M)
UDEV_RE = re.compile(r'\b(?:RUN|PROGRAM|IMPORT\{program\})(?:\{program\})?\s*[+:]?==?\s*"([^"]*)"')
DLOPEN_RE = re.compile(rb'\[\{"[^\x00]*?\}\]')
DLOPEN_FAIL_PRIORITIES = {"required"}
MAX_LISTED = 200

# Pre-existing FSDK leftovers, matched in any tree. Shrink-only: an entry that
# no longer matches fails the check, so delete it when its cause is fixed.
KNOWN_BROKEN = {
    # PAM's Berkeley-DB module; no PAM stack here uses pam_userdb.
    "/usr/lib/*-linux-gnu/security/pam_userdb.so needs missing libgdbm.so.6",
    # Pulled in by the systemd-quotacheck generator only for quota mounts.
    "/usr/lib/systemd/system/quotaon-root.service runs missing /usr/bin/quotaon",
    # Only started when swtpm is installed (systemd-tpm2-swtpm finds none).
    "/usr/lib/systemd/system/systemd-tpm2-swtpm.service runs missing swtpm_ioctl",
    # tpm2-tools' tpm2_id is not in FSDK; the rule only adds udev properties.
    "/usr/lib/udev/rules.d/60-tpm2-id.rules runs missing tpm2_id",
    # Only for TI am65-cpsw-nuss switchdev NICs (iproute2 has no devlink here).
    "/usr/lib/udev/rules.d/81-net-bridge.rules runs missing /usr/sbin/devlink",
    # NVIDIA's GLX and EGL-GBM display libraries; the headless image has no
    # X11, libdrm or gbm, and CUDA/container compute never loads them.
    "/usr/lib/*-linux-gnu/libGLX_nvidia.so.* needs missing libX11.so.6",
    "/usr/lib/*-linux-gnu/libGLX_nvidia.so.* needs missing libXext.so.6",
    "/usr/lib/*-linux-gnu/libnvidia-egl-gbm.so.* needs missing libdrm.so.2",
    "/usr/lib/*-linux-gnu/libnvidia-egl-gbm.so.* needs missing libgbm.so.1",
}


def apply_waivers(errors: list[str]) -> list[str]:
    """Drop errors KNOWN_BROKEN waives; report waivers nothing matched."""
    seen: set[str] = set()
    remaining: list[str] = []
    for error in dict.fromkeys(errors):
        detail = re.sub(r"/usr/lib/[^/]+-linux-gnu/", "/usr/lib/*-linux-gnu/", error.split(": ", 1)[-1])
        detail = re.sub(r"(\.so\.)\d[\d.]* needs", r"\1* needs", detail)
        if detail in KNOWN_BROKEN:
            seen.add(detail)
        else:
            remaining.append(error)
    remaining += [f"stale KNOWN_BROKEN entry, delete it: {w}" for w in sorted(KNOWN_BROKEN - seen)]
    return remaining


def lookup(layers: list[Path], path: str, depth: int = 0) -> Path | None:
    """Resolve an absolute in-image path over overlay layers (first wins).

    Symlink targets resolve inside the image, never on the host.
    """
    if depth > 40:
        return None
    parts = [p for p in path.split("/") if p and p != "."]
    if parts and parts[0] in USR_MERGE:
        parts = USR_MERGE[parts[0]].split("/") + parts[1:]
    current: list[str] = []
    host: Path | None = None
    for index, part in enumerate(parts):
        if part == "..":
            current = current[:-1]
            continue
        rel = "/".join(current + [part])
        host = next((root / rel for root in layers if os.path.lexists(root / rel)), None)
        if host is None:
            return None
        if host.is_symlink():
            target = os.readlink(host)
            base = target if target.startswith("/") else "/".join(["", *current, target])
            rest = "/".join(parts[index + 1 :])
            return lookup(layers, f"{base}/{rest}" if rest else base, depth + 1)
        current.append(part)
    return host if host is not None else (layers[0] if layers else None)


def iter_files(root: Path) -> Iterator[Path]:
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            yield Path(dirpath) / name


def is_elf(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def available_sonames(layers: list[Path]) -> set[str]:
    names: set[str] = set()
    for root in layers:
        for libdir in ("usr/lib", "usr/lib64"):
            base = root / libdir
            if base.is_dir():
                names.update(p.name for p in iter_files(base))
    return names


def elf_needed(paths: list[Path]) -> tuple[dict[Path, list[str]], dict[Path, list[str]]]:
    """DT_NEEDED sonames and DT_RUNPATH/DT_RPATH directories per ELF file."""
    needed: dict[Path, list[str]] = {}
    runpaths: dict[Path, list[str]] = {}
    for start in range(0, len(paths), 200):
        batch = paths[start : start + 200]
        out = subprocess.run(
            ["readelf", "-dW", *map(str, batch)], capture_output=True, text=True
        ).stdout
        # readelf prints "File:" headers only when given several files.
        current: Path | None = batch[0] if len(batch) == 1 else None
        for line in out.splitlines():
            if line.startswith("File: "):
                current = Path(line[6:].strip())
            elif "(NEEDED)" in line and current is not None:
                match = re.search(r"\[(.+?)\]", line)
                if match:
                    needed.setdefault(current, []).append(match.group(1))
            elif ("(RUNPATH)" in line or "(RPATH)" in line) and current is not None:
                match = re.search(r"\[(.+?)\]", line)
                if match:
                    runpaths.setdefault(current, []).extend(match.group(1).split(":"))
    return needed, runpaths


def dlopen_required(path: Path) -> list[list[str]]:
    """Soname alternatives of each "required" .note.dlopen entry (JSON in the note)."""
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b'"soname"' not in data:
        return []
    required: list[list[str]] = []
    for blob in DLOPEN_RE.findall(data):
        try:
            entries = json.loads(blob.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and entry.get("priority") in DLOPEN_FAIL_PRIORITIES:
                required.append(list(entry.get("soname", [])))
    return required


def check_libraries(name: str, layers: list[Path], own: Path) -> list[str]:
    errors: list[str] = []
    sonames = available_sonames(layers)
    elves = [
        p
        for p in iter_files(own)
        if "/lib/modules/" not in str(p) and is_elf(p)
    ]
    needed, runpaths = elf_needed(elves)
    for path, libs in sorted(needed.items()):
        origin = "/" + str(path.parent.relative_to(own))
        dirs = [d.replace("$ORIGIN", origin) for d in runpaths.get(path, [])]
        for lib in libs:
            if lib not in sonames and not any(lookup(layers, f"{d}/{lib}") for d in dirs):
                errors.append(f"{name}: /{path.relative_to(own)} needs missing {lib}")
    for path in elves:
        for alternatives in dlopen_required(path):
            if not any(alt in sonames for alt in alternatives):
                errors.append(
                    f"{name}: /{path.relative_to(own)} requires dlopen of missing {' or '.join(alternatives)}"
                )
    return errors


def first_program(command: str) -> str | None:
    stripped = command.lstrip("@-:+!|")
    if "-" in command[: len(command) - len(stripped)]:
        return None
    command = stripped
    token = command.split(None, 1)[0] if command.strip() else ""
    if not token or "$" in token or "%" in token:
        return None
    return token


def program_exists(layers: list[Path], program: str, search: tuple[str, ...]) -> bool:
    if program.startswith("/"):
        return lookup(layers, program) is not None
    return any(lookup(layers, f"{d}/{program}") is not None for d in search)


def check_programs(name: str, layers: list[Path], own: Path) -> list[str]:
    errors: list[str] = []
    for unit_dir in UNIT_DIRS:
        base = own / unit_dir
        if not base.is_dir():
            continue
        for path in sorted(iter_files(base)):
            if path.is_symlink():
                continue
            text = path.read_text(errors="replace")
            guarded = set(CONDITION_RE.findall(text))
            for line in text.splitlines():
                match = EXEC_RE.match(line)
                program = first_program(match.group(1)) if match else None
                if program in guarded:
                    continue
                if program and not program_exists(layers, program, ("/usr/bin",)):
                    errors.append(f"{name}: /{path.relative_to(own)} runs missing {program}")
    for rule_dir in RULE_DIRS:
        base = own / rule_dir
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.rules")):
            for command in UDEV_RE.findall(path.read_text(errors="replace")):
                program = first_program(command)
                if program and not program_exists(layers, program, ("/usr/lib/udev", "/usr/bin")):
                    errors.append(f"{name}: /{path.relative_to(own)} runs missing {program}")
    return errors


def manifest(root: Path) -> set[str]:
    paths: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        for entry in dirnames + filenames:
            paths.add("/" + str((Path(dirpath) / entry).relative_to(root)))
    return paths


def diff_report(old: set[str], new: set[str]) -> str:
    removed = sorted(old - new)
    added = sorted(new - old)
    lines = [f"### /usr changes vs baseline: {len(removed)} removed, {len(added)} added", ""]
    for title, items in (("Removed", removed), ("Added", added)):
        if not items:
            continue
        lines += [f"<details><summary>{title} ({len(items)})</summary>", "", "```"]
        lines += items[:MAX_LISTED]
        if len(items) > MAX_LISTED:
            lines.append(f"... {len(items) - MAX_LISTED} more")
        lines += ["```", "</details>", ""]
    return "\n".join(lines)


def du(root: Path) -> int:
    return sum(p.lstat().st_size for p in iter_files(root))


def run(*cmd: str, cwd: Path | None = None, input: bytes | None = None, quiet: bool = False) -> None:
    stdout = subprocess.DEVNULL if quiet else None
    subprocess.run(cmd, check=True, cwd=cwd, input=input, stdout=stdout)


def extract_erofs(image: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    run("fsck.erofs", f"--extract={dest}", "--no-preserve", str(image), quiet=True)


def pe_section(path: Path, wanted: str) -> bytes:
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    optional = struct.unpack_from("<H", data, pe + 20)[0]
    table = pe + 24 + optional
    for i in range(count):
        entry = table + 40 * i
        name = data[entry : entry + 8].rstrip(b"\x00").decode()
        size, _, _, offset = struct.unpack_from("<IIII", data, entry + 8)
        if name == wanted:
            return data[offset : offset + size]
    raise SystemExit(f"{path.name}: no {wanted} section")


def extract_initrd(uki: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    cpio = subprocess.run(
        ["zstd", "-dc"], input=pe_section(uki, ".initrd"), capture_output=True, check=True
    ).stdout
    run("cpio", "-id", "--quiet", "--no-absolute-filenames", input=cpio, cwd=dest)


def single(dist: Path, pattern: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"expected one {pattern} in {dist}, found {[m.name for m in matches]}")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dist", type=Path, help="exported image set, e.g. dist/diskless")
    parser.add_argument("--baseline-usr", type=Path, help="previous release's *.usr.raw")
    args = parser.parse_args(argv)
    installer = single(args.dist, "bluefin-server-installer_*.raw")
    if installer.stat().st_size >= 4 * 2**30:
        raise SystemExit(f"installer image {installer.name} must be smaller than 4 GiB")

    for tool in ("readelf", "zstd", "cpio", "fsck.erofs"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found on PATH")

    with tempfile.TemporaryDirectory(prefix="check-image-") as tmp:
        work = Path(tmp)
        usr_root = work / "usr-root"
        extract_erofs(single(args.dist, "bluefin-server_*_*.usr.raw"), usr_root / "usr")
        initrd_root = work / "initrd"
        disk_uki = single(args.dist, "bluefin-server-[0-9]*.efi")
        extract_initrd(disk_uki, initrd_root)

        report = [
            f"/usr unpacked: {du(usr_root) / 2**20:.0f} MiB",
            f"initrd unpacked: {du(initrd_root) / 2**20:.0f} MiB",
            f"{disk_uki.name}: {disk_uki.stat().st_size / 2**20:.0f} MiB",
        ]

        errors = check_libraries("usr", [usr_root], usr_root)
        errors += check_programs("usr", [usr_root], usr_root)
        errors += check_libraries("initrd", [initrd_root], initrd_root)
        errors += check_programs("initrd", [initrd_root], initrd_root)

        for sysext in sorted(args.dist.glob("*.raw.zst")):
            raw = work / sysext.name.removesuffix(".zst")
            run("zstd", "-dqf", str(sysext), "-o", str(raw))
            root = work / f"sysext-{raw.stem}"
            extract_erofs(raw, root)
            raw.unlink()
            name = sysext.name.removesuffix(".raw.zst")
            # A machine is self-contained, not a sysext layered over host /usr.
            machine = sysext.name.startswith("homebrew_")
            layers = [root] if machine else [root, usr_root]
            errors += check_libraries(name, layers, root)
            errors += check_programs(name, layers, root)
            relation = "standalone machine" if machine else "checked over /usr"
            report.append(f"{sysext.name}: {du(root) / 2**20:.0f} MiB unpacked, {relation}")

        if args.baseline_usr:
            base_root = work / "baseline"
            extract_erofs(args.baseline_usr, base_root)
            report.append(diff_report(manifest(base_root), manifest(usr_root / "usr")))

    summary = "\n\n".join(report)
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    errors = apply_waivers(errors)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
