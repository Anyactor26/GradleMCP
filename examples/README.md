# Working examples

- `groovy`: Java project, Groovy build DSL, offline smoke-test harness bound to check,
  JAR, slow task and intentionalFailure task. `build` compiles and checks.
- `kotlin-dsl`: Java project configured with Kotlin build DSL, JAR. Not a Kotlin-language plugin demo.
- `multi`: root plus Java-library subproject; JAR under lib/build/libs.
- `failing`: deliberately failing build for diagnosis, no external dependencies.

Review archives before submission: never include `.git`, caches, private config or
keys. In a project directory `zip -r /tmp/project.zip . -x 'build/*' '.gradle/*'` is a
starting point, **not a secret scrubber**. Python client filters common local files
but cannot identify every secret.

```sh
export GRADLEMCP_TOKEN='INJECT_YOUR_TOKEN'
export GRADLEMCP_URL=http://127.0.0.1:8000
python examples/client.py examples/groovy
python examples/client.py examples/groovy --task build --task smokeTest
python examples/client.py examples/failing  # prints diagnostic, exits nonzero
node examples/client.ts /tmp/project.zip  # Node 22.18+, no npm install
sh examples/curl.sh /tmp/project.zip       # curl, jq, Python
```

Clients wait at most one hour/~45 minutes (curl) and do not automatically resubmit
failed jobs or publish. They use bounded log pagination; Python/TypeScript stream and
verify artifact downloads. Curl shows an explicit artifact download command; adjust
pagination when reading more than the first 64 KiB. Keep tokens in environment/secret
stores, not shell history or committed files. Generated files go to downloaded-artifacts
(gitignored). MCP configurations are in docs/MCP.md.

Python and TypeScript clients are tested against the actual FastAPI application over local HTTP for
authentication, upload, compatibility, submission, polling, diagnostics and artifact
downloads, using explicitly labeled terminal-state/output fixtures (not build results). That does not mean real Gradle execution was possible in this
sandbox; see docs/VERIFICATION.md for actual worker verification status.
