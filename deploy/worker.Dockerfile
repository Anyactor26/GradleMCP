# Pin both reviewed base images to digests for production.
ARG BASE_IMAGE=gradle:8.14.3-jdk17
ARG RUNTIME_IMAGE=eclipse-temurin:17-jdk-jammy
FROM ${BASE_IMAGE} AS distribution
FROM ${RUNTIME_IMAGE}
# Do not inherit Gradle image VOLUME declarations (unbounded anonymous host storage).
COPY --from=distribution /opt/gradle /opt/gradle
ENV GRADLE_HOME=/opt/gradle PATH="/opt/gradle/bin:${PATH}"
USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["gradle"]
