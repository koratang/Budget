# 预算管理平台 · 应用镜像（路径 B）。构建前先在 app/frontend 执行 npm run build，产物位于 app/backend/app/static
FROM python:3.14.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
WORKDIR /srv/budget
COPY app/backend/requirements.txt ./requirements.txt
# 离线安装：wheel 由 build-images.sh 在构建机预先下载到 deploy/wheels/linux（DEC-018，不在镜像构建中联网）
COPY deploy/wheels/linux /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links /tmp/wheels -r requirements.txt && rm -rf /tmp/wheels
COPY app/backend/ ./
RUN test -f app/static/index.html || (echo "缺少前端构建产物 app/backend/app/static，请先 npm run build" && exit 1)
COPY deploy/linux/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /srv/budget/data
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
