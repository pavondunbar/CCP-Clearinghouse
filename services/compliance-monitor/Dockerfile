FROM ccp-base:latest
COPY services/compliance-monitor/ /app/services/compliance-monitor/
RUN cd /app/services/compliance-monitor && uv pip install .
EXPOSE 8009
CMD ["uvicorn", "compliance_monitor.main:app", "--host", "0.0.0.0", "--port", "8009"]
