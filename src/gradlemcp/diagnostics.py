import re


def redact(text, secrets=()):
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", text)
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    return text


def diagnose(text, code):
    cases = [
        (
            "disk_full",
            r"No space left on device",
            "Increase the workspace limit or free server storage.",
        ),
        (
            "jdk_incompatible",
            r"Unsupported class file|requires Java|invalid source release|No matching toolchains",
            "Select a compatible JDK worker profile.",
        ),
        (
            "android_sdk_missing",
            r"SDK location not found|ANDROID_HOME",
            "Configure an approved image containing the required Android SDK.",
        ),
        (
            "repository_auth",
            r"401 Unauthorized|403 Forbidden|status code 401|status code 403",
            "Configure scoped repository credentials; do not place secrets in source.",
        ),
        (
            "dependency_resolution",
            r"Could not resolve|Could not GET|UnknownHostException",
            "Check repositories, worker egress policy, and offline dependency caches.",
        ),
        (
            "out_of_memory",
            r"OutOfMemoryError|Java heap space|unable to create native thread",
            "Reduce Gradle parallelism or request a larger worker.",
        ),
        (
            "tests_failed",
            r"There were failing tests|tests completed, .*failed",
            "Download test reports and correct failing tests.",
        ),
        (
            "compilation_failed",
            r"Compilation failed|Compilation error|error:",
            "Review the compiler diagnostics in the build log.",
        ),
    ]
    for name, pattern, action in cases:
        if re.search(pattern, text, re.IGNORECASE):
            return {
                "code": name,
                "message": "Build failed: " + name.replace("_", " "),
                "remediation": action,
                "retryable": False,
                "permanent": True,
            }
    return {
        "code": "gradle_failed",
        "message": f"Gradle exited with code {code}",
        "remediation": "Read the logs; check tasks, plugins, operating system and required tools before retrying.",
        "retryable": False,
        "permanent": True,
    }
