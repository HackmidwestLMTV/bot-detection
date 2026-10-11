FROM python:3.12-slim
WORKDIR /srv
COPY engine/requirements*.txt engine/
RUN pip install --no-cache-dir -r engine/requirements.txt
COPY engine/ engine/
COPY contracts/fixtures/variant_v1.json contracts/fixtures/variant_v1.json
COPY contracts/*.py contracts/
CMD ["python", "-m", "engine.worker"]
