FROM ccp-base:latest
COPY services/api-gateway/ /app/services/api-gateway/
RUN cd /app/services/api-gateway && uv pip install .
EXPOSE 8000
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
