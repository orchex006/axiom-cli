# Unpublished K-011 integration candidate. Build context is assembled from
# reviewed CLI source and exact K-006/MCP/skills inputs by the candidate harness.
# This is not the publish-container.yml image or a released artifact.
FROM rust:1.85-slim-bookworm@sha256:9f841bbe9e7d8e37ceb96ed907265a3a0df7f44e3737d0b100e7907a679acb36 AS cli-builder

WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked --offline --bin axiom-cli

FROM python:3.13.15-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26 AS runtime

ARG AXIOM_REVISION=unknown
ARG AXIOM_CREATED=1970-01-01T00:00:00Z
LABEL org.opencontainers.image.title="axiom-cli K-011 candidate" \
      org.opencontainers.image.source="https://github.com/orchex006/axiom-cli" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.revision="${AXIOM_REVISION}" \
      org.opencontainers.image.created="${AXIOM_CREATED}" \
      org.opencontainers.image.licenses="UNLICENSED" \
      io.orchex006.axiom.channel="container-linux-x64" \
      io.orchex006.axiom.candidate="true" \
      io.orchex006.axiom.native-evidence="false"

RUN groupadd --gid 10001 axiom \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /home/axiom --shell /usr/sbin/nologin axiom \
 && install -d -o 10001 -g 10001 -m 0755 /home/axiom

COPY --chown=0:0 candidate/release /opt/axiom/release
COPY --chown=0:0 candidate/wheels /opt/axiom/wheels
COPY --chown=0:0 candidate/mcp-requirements.lock /opt/axiom/mcp-requirements.lock
COPY --from=cli-builder --chown=0:0 --chmod=0755 /src/target/release/axiom-cli /opt/axiom/release/axiom-cli

RUN printf '%s  %s\n' \
      '0f3bf17bcf3962103d153f758ed570a6a3ab272f630544e6ebea372fc427737c' '/opt/axiom/release/axiom' \
      'ce684f0066d547fae54312a5aeaeb0f9782fe9f509b1754592cc80b7b652f33b' '/opt/axiom/release/axiom-graphd' \
      '365d4d2baa3b155b1c2cb661fdfd8439db1f628ba9ea524e0b0ee49d14c22705' '/opt/axiom/release/axiom_mcp-0.1.0-py3-none-any.whl' \
      '5cf467f4d856044458d29124fa866632fdf64f398dd3fd227f6b6d3501ed99c9' '/opt/axiom/mcp-requirements.lock' \
    | sha256sum --check --strict \
 && python -m venv --copies /opt/axiom/mcp-venv \
 && /opt/axiom/mcp-venv/bin/python -m pip install --disable-pip-version-check --no-index \
      --find-links /opt/axiom/wheels --require-hashes -r /opt/axiom/mcp-requirements.lock \
 && /opt/axiom/mcp-venv/bin/python -m pip install --disable-pip-version-check --no-index \
      --no-deps /opt/axiom/release/axiom_mcp-0.1.0-py3-none-any.whl \
 && /opt/axiom/mcp-venv/bin/python -m pip check \
 && /opt/axiom/mcp-venv/bin/python -m axiom_mcp.cli version --json

USER 10001:10001
WORKDIR /home/axiom
ENTRYPOINT ["/opt/axiom/release/axiom-cli"]
CMD ["--help"]
