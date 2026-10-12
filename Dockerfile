# Fallback hosting (any server or cloud VM):  docker build -t evolve-planner . && docker run -p 8501:8501 evolve-planner
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends glpk-utils && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
