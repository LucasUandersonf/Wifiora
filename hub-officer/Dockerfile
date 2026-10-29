FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY plugins ./plugins

RUN useradd --create-home --uid 10001 office && chown -R office /app
USER office

# Railway injeta $PORT. OFFICE_ROLE decide o papel do processo:
#   all (padrão) = API + agentes | api = só HTTP | worker = só agentes
ENV PORT=8000 OFFICE_ROLE=all
EXPOSE 8000

CMD ["sh", "-c", "if [ \"$OFFICE_ROLE\" = \"worker\" ]; then exec python -m app.worker; else exec python -m app.serve; fi"]
