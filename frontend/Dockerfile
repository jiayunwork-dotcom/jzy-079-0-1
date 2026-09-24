# 前端：node:20-alpine 构建静态资源，nginx:alpine 提供页面
FROM node:20-alpine AS build

WORKDIR /build

# 先装依赖（利用 Docker 层缓存）
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install --no-audit --no-fund; fi

COPY . .
RUN npm run build

FROM nginx:alpine AS serve

# 静态资源
COPY --from=build /build/dist /usr/share/nginx/html
# nginx 配置（含 /api 反代与 /ws WebSocket 升级）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null 2>&1 || exit 1

CMD ["nginx", "-g", "daemon off;"]
