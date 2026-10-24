FROM python:3.11-slim
WORKDIR /app
COPY requirements/modern.txt /app/requirements/modern.txt
RUN pip install --no-cache-dir -r requirements/modern.txt
COPY . /app
RUN pybabel compile -d qpanel/translations && useradd --system --uid 10001 sanequeue && mkdir -p /var/lib/sanequeue && chown sanequeue /var/lib/sanequeue
USER sanequeue
EXPOSE 5000
ENV SANEQUEUE_RUNTIME=server SANEQUEUE_STATE_DIR=/var/lib/sanequeue
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:5000", "--timeout", "45", "qpanel.wsgi:app"]
