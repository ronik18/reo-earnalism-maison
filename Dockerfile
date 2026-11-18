FROM node:24-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY client ./client
COPY tsconfig.json ./
COPY contracts/openapi.yaml ./contracts/openapi.yaml
COPY static/maison/offline-worker.js ./static/maison/offline-worker.js
RUN npm run check && npm run build

FROM python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gpg age \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl --fail --silent --show-error --location --max-time 30 https://www.postgresql.org/media/keys/ACCC4CF8.asc -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && gpg --show-keys --with-colons /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc | grep -q 'fpr:::::::::B97B0AFCAA1A47F044F244A07FCC7D46ACCC4CF8:' \
    && echo 'deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y --auto-remove curl gpg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
COPY --from=frontend /build/static/maison/dist ./static/maison/dist
RUN useradd --system --uid 10001 --create-home maison && mkdir -p /app/.local && chown maison:maison /app/.local
USER maison
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--worker-class", "gthread", "--threads", "2", "--timeout", "30", "--graceful-timeout", "30", "--max-requests", "2000", "--max-requests-jitter", "200", "--access-logfile", "-", "--access-logformat", "%(h)s %(m)s %(U)s %(s)s %(L)s"]
