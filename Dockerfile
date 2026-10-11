FROM python:3.12-slim
WORKDIR /srv
COPY web/requirements.txt p.txt
RUN pip install --no-cache-dir -r p.txt
COPY . .
# engine/ is supplied by the reviewed p2 branch or the merged platform.
RUN if [ -f engine/requirements.txt ]; then pip install --no-cache-dir -r engine/requirements.txt; fi
