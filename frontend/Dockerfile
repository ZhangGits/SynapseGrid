# SynapseGrid 前端 Dockerfile
# 构建阶段：使用 Node.js 编译 TypeScript 和 React
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install --ignore-scripts
COPY . .
# Use /tmp as outDir to avoid dist/ permissions issues
RUN npx vite build --outDir /tmp/dist --emptyOutDir

# 运行阶段：使用 Nginx 提供静态文件
FROM nginx:alpine
COPY --from=build /tmp/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
