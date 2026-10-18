# Gradle / Java compatibility and provisioning

## Project formats

Source is not rearranged or constrained to `src/main/java`: arbitrary Groovy/Kotlin
DSL, settings, multi-project/composite builds, included builds, convention plugins,
version catalogs, nonstandard sources, custom tasks/plugins/repositories work to
the extent the chosen Gradle/JDK/image/dependencies support them. Gradle itself
interprets projects; inspection never executes scripts. A ZIP can contain a top-level
directory; select `subdirectory` to point at its actual build root.

Java hints recognize common JavaLanguageVersion.of, jvmToolchain, sourceCompatibility
and JavaVersion constants. Dynamic variables and complex scripts are not evaluated.
Explicit `java` or `toolchain` can select an environment when hints are incomplete.
The highest static hint is used by default; multi-JDK builds should use custom images
containing all required JDKs and reviewed Gradle toolchain configuration. Java 1.8
legacy notation and target-bytecode versus runtime distinctions are heuristic; set
an explicit Java version rather than relying on sourceCompatibility as proof.

## Managed Gradle (default)

Approved images contain an installed Gradle and one/more JDKs. The example image is
Java 17 / Gradle 8.14.3. Build another image, then register it:
```sh
docker build -f deploy/worker.Dockerfile \
  --build-arg BASE_IMAGE=gradle:8.14.3-jdk21 --build-arg RUNTIME_IMAGE=eclipse-temurin:21-jdk-jammy -t gradlemcp-worker:21 .
```
Map `java21` to `{image:"gradlemcp-worker:21",java:21,gradle:"8.14.3"}`. To support older
Gradle releases, add compatible JDK+Gradle image profiles rather than forcing all
projects to one version. Check the upstream Gradle compatibility matrix, especially
Gradle 9's Java runtime requirements. Metadata declares operator-tested installations;
GradleMCP does not attest arbitrary image labels. `doctor` is not a toolchain test.

Optional `auto_pull=true` provisions selected JDK/Gradle environments by pulling an
operator-approved **digest-pinned** image. Docker validates content-addressed layers;
trust the publisher and registry, review image provenance/SBOM/signatures externally.
No project can choose an arbitrary image or executable download URL. Local image
builds work offline once their base/tooling is present. Gradle distribution binaries
are reused from immutable Docker image layers. Mutable per-build dependency/wrapper
caches are intentionally isolated, not persisted across tenants.

## Wrapper (opt-in)

A complete wrapper requires gradlew, wrapper JAR and properties; gradlew.bat is
recognized as source but Linux workers use gradlew. Validation requires an approved
HTTPS host, port 443/default, no userinfo/query/fragment, standard distribution path
and distributionSha256Sum. Wrapper validity describes configuration, **not trust**
in the wrapper script/JAR: both are arbitrary executable project code and run only
in the same sandbox. When `wrapper_enabled` is true, omitting `use_wrapper` automatically prefers a
complete validated wrapper. Explicit `use_wrapper:false` selects managed Gradle;
`use_wrapper:true` requires a valid allowed wrapper. Enable this policy only
when network policy permits distribution retrieval. Managed Gradle ignores wrapper
scripts entirely and is preferable for stricter deployments.

Approved hosts alone do not enforce redirect/DNS/IP security: Gradle downloads run
inside the worker and must obey the operator's egress firewall/proxy (or default
network none). A malicious wrapper can ignore its properties; do not relax isolation
because validation succeeded. The controller never fetches wrapper URLs.

## Android, Kotlin, Groovy, Scala, native

Java language samples are included for Groovy and Kotlin **build DSLs**; the Kotlin
DSL sample does not claim to compile Kotlin language sources. Kotlin/Groovy/Scala
plugins/dependencies require approved compatible toolchains and dependency access.
Android detection yields toolchain_unavailable unless a profile declares android=true;
provide a legally installed SDK, accepted licenses, platform/build tools and matching
JDK. Native detection similarly requires native=true and compiler/system libraries.
These SDKs are not automatically available in the base worker. OS-specific Apple
builds cannot run on this Linux implementation. Custom images can include SDKs and
approved offline caches; their root remains read-only, so redirect writable SDK/build
state into the workspace. Toolchain repositories controlled by projects are executable
download surfaces and remain inside network/isolation policy.

Errors identify missing profiles with available options; runtime diagnosis differentiates
repository resolution/authentication, Android SDK, incompatible JDK, tests, compilation,
disk and OOM symptoms. Heuristic classification can be imperfect: logs remain the
source of truth. Do not label every failure retryable.
