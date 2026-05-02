FROM apache/airflow:2.10.5-python3.11

USER airflow

COPY team_Pearson/coursework_one/docker/airflow/requirements.txt /requirements-cw1.txt

RUN pip install --no-cache-dir \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.10.5/constraints-3.11.txt" \
    -r /requirements-cw1.txt
