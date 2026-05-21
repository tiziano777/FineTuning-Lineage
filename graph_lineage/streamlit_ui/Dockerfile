FROM python:3.10-slim

WORKDIR /app

COPY graph_lineage/streamlit_ui/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Also install envelope for validation
COPY . .
 
# Install the package from the repository so `graph_lineage` is importable
# Using editable install helps development workflows inside container
RUN pip install --no-cache-dir -e .
EXPOSE 8501

CMD ["streamlit", "run", "graph_lineage/streamlit_ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
