
FROM apache/airflow:2.7.3

# Install dependencies
RUN pip install --no-cache-dir \
    psycopg2-binary==2.9.10 \
    pandas==2.0.3 \
    sqlalchemy==1.4.52
