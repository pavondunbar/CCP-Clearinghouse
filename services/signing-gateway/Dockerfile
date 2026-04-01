FROM ccp-base:latest
COPY services/signing-gateway/ /app/services/signing-gateway/
RUN cd /app/services/signing-gateway && uv pip install .
EXPOSE 8010
CMD ["uvicorn", "signing_gateway.main:app", "--host", "0.0.0.0", "--port", "8010"]
