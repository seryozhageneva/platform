FROM python:3.12-slim
COPY execute.py /opt/execute.py
USER 65534:65534
ENTRYPOINT ["python", "-IBu", "/opt/execute.py"]
