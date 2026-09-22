# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip setuptools wheel && pip install ".[service,ortools]"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"
RUN groupadd --system --gid 10001 quantroute && useradd --system --uid 10001 --gid quantroute --home /nonexistent --shell /usr/sbin/nologin quantroute
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["quantroute-api"]
