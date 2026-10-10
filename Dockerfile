FROM python:3.12-slim
WORKDIR /srv
COPY web/requirements.txt p.txt
RUN pip install --no-cache-dir -r p.txt
COPY . .
# engine/ only exists after deploy-time integration (deploy.sh copies it from p2-engine)
RUN if [ -f engine/requirements.txt ]; then pip install --no-cache-dir -r engine/requirements.txt; fi
