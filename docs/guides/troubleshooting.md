# Troubleshooting

This document provides solutions to common issues, error patterns, and operational problems encountered when working with the Agents Blueprint.

## 🎯 Quick Reference

### Common HTTP Status Codes
- **400 Bad Request**: Invalid input data or malformed requests
- **401 Unauthorized**: Missing or invalid API key
- **404 Not Found**: Resource doesn't exist or gateway unavailable
- **500 Internal Server Error**: Unexpected server-side error
- **502 Bad Gateway**: External service (gateway) unavailable
- **503 Service Unavailable**: Service temporarily unavailable

## 🚀 Startup Issues

### Application Won't Start
**Symptoms**: Server fails to start, port binding errors, or immediate crashes.

**Solutions**:
1. **Check port availability**
   ```bash
   netstat -tlnp | grep :8000
   lsof -i :8000
   ```

2. **Verify environment variables**
   ```bash
   python -c "from src.config import validate_configuration; validate_configuration()"
   ```

3. **Check Python version**
   ```bash
   python --version  # Should be 3.11+
   ```

4. **Validate dependencies**
   ```bash
   pip check
   ```

### Docker Issues
**Symptoms**: Container fails to start or services aren't accessible.

**Solutions**:
1. **Check Docker daemon**
   ```bash
   docker info
   systemctl status docker
   ```

2. **Clean up containers**
   ```bash
   docker-compose down
   docker system prune -f
   ```

3. **Rebuild images**
   ```bash
   docker-compose build --no-cache
   docker-compose up --force-recreate
   ```

### Database/Messaging Issues
**Symptoms**: RabbitMQ connection failures, message processing errors.

**Solutions**:
1. **Check RabbitMQ status**
   ```bash
   docker-compose logs rabbitmq
   curl http://localhost:15672/api/aliveness-test/%2F
   ```

2. **Verify connection string**
   ```bash
   # Test AMQP connection
   python -c "
   import pika
   try:
       connection = pika.BlockingConnection('amqp://guest:guest@localhost:5672/')
       print('RabbitMQ connection successful')
       connection.close()
   except Exception as e:
       print(f'RabbitMQ connection failed: {e}')
   "
   ```

## 🔍 Runtime Issues

### Event Processing Failures
**Symptoms**: Events not being processed, high error rates, dead letter queue filling up.

**Debug Steps**:
1. **Check event format**
   ```bash
   # Validate JSON format
   cat event.json | python -m json.tool
   ```

2. **Examine application logs**
   ```bash
   docker-compose logs -f asset-backup-checker
   ```

3. **Check message broker**
   ```bash
   # RabbitMQ management UI: http://localhost:15672
   # Check queue depths, consumer status
   ```

4. **Verify data gateway**
   ```bash
   curl http://localhost:8001/health
   ```

### Performance Issues
**Symptoms**: Slow response times, high CPU/memory usage, queue backlogs.

**Debug Steps**:
1. **Check system resources**
   ```bash
   docker stats
   top -p $(pgrep python)
   ```

2. **Examine processing metrics**
   ```bash
   curl http://localhost:8000/actuators/metrics
   ```

3. **Profile slow operations**
   ```python
   import cProfile
   cProfile.run('your_slow_function()')
   ```

### Memory Leaks
**Symptoms**: Gradually increasing memory usage, out of memory errors.

**Debug Steps**:
1. **Monitor memory usage**
   ```bash
   docker stats asset-backup-checker
   ```

2. **Check for object accumulation**
   ```python
   import gc
   import objgraph
   objgraph.show_most_common_types()
   ```

3. **Profile memory usage**
   ```python
   from memory_profiler import profile
   @profile
   def memory_intensive_function():
       # Your function here
   ```

## 🔧 Configuration Issues

### Environment Variable Problems
**Symptoms**: Missing configuration, wrong values, services not connecting.

**Debug Steps**:
1. **List all environment variables**
   ```bash
   docker-compose exec asset-backup-checker env | grep -E "(APP_|DATA_|RABBIT_|AI_)"
   ```

2. **Check configuration validation**
   ```bash
   docker-compose exec asset-backup-checker python -c "
   from src.config import settings
   print('Configuration loaded successfully')
   print(f'App port: {settings.app_port}')
   print(f'Data gateway URL: {settings.data_gateway_base_url}')
   "
   ```

### Secret Management Issues
**Symptoms**: Authentication failures, API key errors.

**Solutions**:
1. **Verify secret references**
   ```yaml
   # Check if secrets are properly mounted
   docker-compose exec asset-backup-checker ls -la /run/secrets/
   ```

2. **Test API connectivity**
   ```bash
   curl -H "Authorization: Bearer $API_KEY" $DATA_GATEWAY_BASE_URL/health
   ```

## 🧪 Testing Issues

### Test Failures
**Symptoms**: Unit tests failing, integration tests timing out.

**Solutions**:
1. **Run tests in isolation**
   ```bash
   pytest tests/unit/test_specific_file.py -v
   ```

2. **Check test environment**
   ```bash
   # Ensure test dependencies are installed
   pip install -e ".[dev]"
   ```

3. **Mock external dependencies**
   ```python
   # Verify mocks are properly configured
   with patch('module.function') as mock_func:
       mock_func.return_value = expected_value
       # Test code here
   ```

### Coverage Issues
**Symptoms**: Low test coverage, missing lines in reports.

**Solutions**:
1. **Run coverage analysis**
   ```bash
   pytest --cov=src --cov-report=term-missing --cov-report=html
   ```

2. **Check coverage exclusions**
   ```python
   # Ensure important code isn't accidentally excluded
   # Review .coveragerc and pyproject.toml
   ```

## 📊 Monitoring and Alerting

### Log Analysis
**Symptoms**: Errors in logs, unexpected behavior.

**Debug Steps**:
1. **Check structured logs**
   ```bash
   docker-compose logs asset-backup-checker | jq .
   ```

2. **Filter by correlation ID**
   ```bash
   docker-compose logs asset-backup-checker | grep "correlation_id"
   ```

3. **Look for error patterns**
   ```bash
   docker-compose logs asset-backup-checker | grep -i error
   ```

### Metric Analysis
**Symptoms**: Performance degradation, resource exhaustion.

**Debug Steps**:
1. **Check application metrics**
   ```bash
   curl http://localhost:8000/actuators/metrics
   ```

2. **Monitor system resources**
   ```bash
   docker stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"
   ```

## 🔄 Recovery Procedures

### Service Restart
```bash
# Graceful restart
docker-compose restart asset-backup-checker

# Force restart
docker-compose kill asset-backup-checker
docker-compose up -d asset-backup-checker
```

### Database Reset (Development Only)
```bash
# Reset RabbitMQ
docker-compose down
docker volume rm agents_blueprint_rabbitmq_data
docker-compose up -d rabbitmq

# Wait for RabbitMQ to start
sleep 30

# Restart application
docker-compose up -d asset-backup-checker
```

### Configuration Reload
```bash
# For configuration changes
docker-compose exec asset-backup-checker python -c "
from src.config import settings
settings.reload()
print('Configuration reloaded')
"
```

## 🛠️ Advanced Debugging

### Remote Debugging
```python
# Enable remote debugging in code
import debugpy
debugpy.listen(('0.0.0.0', 5678))
debugpy.wait_for_client()

# Connect with debugger
python -m debugpy --listen 5678 --wait-for-client your_script.py
```

### Memory Analysis
```bash
# Install analysis tools
pip install memory-profiler objgraph

# Analyze memory usage
python -c "
import objgraph
objgraph.show_most_common_types(limit=20)
objgraph.show_growth()
"
```

### Thread Analysis
```python
# Check thread status
import threading
import faulthandler

faulthandler.dump_traceback_later(30)  # Dump if hangs for 30s

for thread in threading.enumerate():
    print(f'Thread: {thread.name}, Daemon: {thread.daemon}, Alive: {thread.is_alive()}')
```

## 📞 Getting Help

### Support Channels
1. **Documentation**: Check relevant guides in `/docs`
2. **Issues**: Search existing GitHub issues
3. **Team**: Contact the development team
4. **Community**: Ask in project discussions

### Reporting Issues
When reporting issues, please include:
- **Environment**: OS, Python version, Docker version
- **Configuration**: Relevant environment variables
- **Logs**: Application and container logs
- **Steps to reproduce**: Exact sequence that causes the issue
- **Expected vs actual behavior**: What should happen vs what does happen

### Emergency Contacts
For production-critical issues:
- **On-call engineer**: [Contact information]
- **Emergency procedures**: [Runbook link]
- **Status page**: [Monitoring dashboard]

---

*This troubleshooting guide is maintained by the operations team. For updates or additions, please refer to the [Development Guide](development-guide.md).*
