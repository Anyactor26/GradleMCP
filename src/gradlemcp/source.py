import io
import re
import stat
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from .errors import ServiceError


def extract_zip(data: bytes, destination: Path, config):
    if len(data) > config.upload_mb * 1024**2:
        raise ServiceError("upload_limit", "Archive exceeds upload limit", 413)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = archive.infolist()
            if len(files) > config.max_files:
                raise ServiceError("archive_limit", "Too many archive entries")
            total = 0
            seen = set()
            for item in files:
                name = item.filename
                path = PurePosixPath(name)
                mode = item.external_attr >> 16
                if (
                    not name
                    or "\\" in name
                    or "\x00" in name
                    or path.is_absolute()
                    or ".." in path.parts
                    or ":" in name
                    or path in seen
                    or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))
                ):
                    raise ServiceError("unsafe_archive", "Unsafe or duplicate archive path")
                seen.add(path)
                total += item.file_size
                if total > config.workspace_mb * 1024**2 // 2:
                    raise ServiceError(
                        "archive_limit", "Expanded source exceeds half the worker workspace"
                    )
                if item.flag_bits & 1:
                    raise ServiceError("invalid_archive", "Encrypted archives are unsupported")
            destination.mkdir(parents=True, mode=0o700)
            for item in files:
                target = destination / item.filename
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # ZipFile checks actual expanded lengths and CRC while reading.
                    with archive.open(item) as src, target.open("xb") as out:
                        while chunk := src.read(65536):
                            out.write(chunk)
    except (
        zipfile.BadZipFile,
        OSError,
        RuntimeError,
        ValueError,
        EOFError,
        NotImplementedError,
        zlib.error,
    ) as exc:
        raise ServiceError("invalid_archive", "Malformed ZIP archive") from exc


def inspect_project(root: Path, config):
    paths = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    build_files = [p for p in paths if p.endswith(("build.gradle", "build.gradle.kts"))]
    settings = [p for p in paths if p.endswith(("settings.gradle", "settings.gradle.kts"))]
    texts = []
    inspected_bytes = 0
    for name in paths:
        if name.endswith((".gradle", ".gradle.kts", ".properties", ".toml")):
            p = root / name
            size = p.stat().st_size
            if size <= 512000 and inspected_bytes + size <= 8 * 1024**2:
                texts.append(p.read_text(errors="replace"))
                inspected_bytes += size
    text = "\n".join(texts)
    versions = sorted(
        {
            int(v)
            for v in re.findall(
                r"(?:JavaLanguageVersion\.of\s*\(|jvmToolchain\s*\(|JavaVersion\.VERSION_|sourceCompatibility\s*=\s*['\"]?)(\d+)",
                text,
            )
        }
    )
    wrapper: dict[str, Any] = {
        "present": "gradle/wrapper/gradle-wrapper.properties" in paths,
        "valid": False,
    }
    if wrapper["present"]:
        props = (root / "gradle/wrapper/gradle-wrapper.properties").read_text(errors="replace")
        values = dict(re.findall(r"(?m)^\s*([\w]+)\s*=\s*(.*?)\s*$", props))
        url = values.get("distributionUrl", "").replace("\\:", ":")
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            parsed = urlparse("")
            port = -1
        checksum = values.get("distributionSha256Sum", "")
        valid = (
            parsed.scheme == "https"
            and parsed.hostname in config.wrapper_hosts
            and port in (None, 443)
            and not parsed.username
            and not parsed.password
            and not parsed.query
            and not parsed.fragment
            and bool(re.fullmatch(r"/distributions/gradle-[\d.]+-(bin|all)\.zip", parsed.path))
            and bool(re.fullmatch(r"[a-fA-F0-9]{64}", checksum))
            and all(p in paths for p in ["gradlew", "gradle/wrapper/gradle-wrapper.jar"])
        )
        version_match = re.search(r"gradle-([\d.]+)-", url)
        wrapper.update(
            valid=bool(valid),
            distribution=url,
            checksum=checksum,
            gradle_version=version_match.group(1) if version_match else None,
        )
    android = bool(re.search(r"com\.android\.|android\s*\{", text))
    native = bool(re.search(r"cpp-|swift-|cpp\s*\{", text))
    return {
        "build_files": build_files,
        "settings_files": settings,
        "wrapper": wrapper,
        "java_hints": versions,
        "android": android,
        "native": native,
        "multi_project": bool(re.search(r"include\s*[( '\"]", text)),
        "composite": "includeBuild" in text,
        "version_catalogs": [p for p in paths if p.endswith(".versions.toml")],
        "warnings": [
            "Static inspection is heuristic; Gradle scripts are not executed.",
            "Choose the archive root or subdirectory containing the intended build.",
        ],
    }
