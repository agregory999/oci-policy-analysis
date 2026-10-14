FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md /app/
COPY src /app/src

FROM base AS web
RUN pip install ".[web]"
ARG IMAGE_TAG
ARG BUILD_DATE
LABEL org.opencontainers.image.created="${BUILD_DATE}" org.opencontainers.image.ref.name="${IMAGE_TAG}"
RUN python -c "import importlib.util,json,os,pathlib; pathlib.Path(importlib.util.find_spec('oci_policy_analysis').origin).with_name('_build_info.json').write_text(json.dumps({'image_tag':os.environ.get('IMAGE_TAG',''),'built_at':os.environ.get('BUILD_DATE','')}))"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=6 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('WEB_PORT','8000')+'/health', timeout=3)" || exit 1
ENV WEB_HOST=0.0.0.0 WEB_PORT=8000
CMD ["oci-policy-analysis-web"]

FROM base AS mcp
RUN pip install ".[mcp]"
COPY docker/mcp-entrypoint.sh /usr/local/bin/mcp-entrypoint.sh
RUN chmod +x /usr/local/bin/mcp-entrypoint.sh
ARG IMAGE_TAG
ARG BUILD_DATE
LABEL org.opencontainers.image.created="${BUILD_DATE}" org.opencontainers.image.ref.name="${IMAGE_TAG}"
RUN python -c "import importlib.util,json,os,pathlib; pathlib.Path(importlib.util.find_spec('oci_policy_analysis').origin).with_name('_build_info.json').write_text(json.dumps({'image_tag':os.environ.get('IMAGE_TAG',''),'built_at':os.environ.get('BUILD_DATE','')}))"
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=6 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('MCP_PORT','8765')+'/health', timeout=3)" || exit 1
ENTRYPOINT ["/usr/local/bin/mcp-entrypoint.sh"]
