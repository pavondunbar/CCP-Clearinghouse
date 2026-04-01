FROM ccp-base:latest
COPY services/collateral-manager/ /app/services/collateral-manager/
RUN cd /app/services/collateral-manager && uv pip install .
EXPOSE 8005
CMD ["uvicorn", "collateral_manager.main:app", "--host", "0.0.0.0", "--port", "8005"]
