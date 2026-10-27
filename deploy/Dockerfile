# 预算管理平台 · 应用镜像（路径 B）。构建前先在 app/frontend 执行 npm run build，产物位于 app/backend/app/static
FROM python:3.14.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
WORKDIR /srv/budget
COPY app/backend/requirements.txt ./requirements.txt
ARG PIP_INDEX_URL
RUN pip install --no-cache-dir ${PIP_INDEX_URL:+-i $PIP_INDEX_URL} -r requirements.txt
COPY app/backend/ ./
RUN test -f app/static/index.html || (echo "缺少前端构建产物 app/backend/app/static，请先 npm run build" && exit 1)
COPY deploy/linux/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /srv/budget/data
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
