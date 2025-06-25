# --- 建構階段 ---
FROM node:18-alpine AS build

# 設定工作目錄
WORKDIR /app

# 複製 package.json 和 lock 檔案
COPY package.json package-lock.json ./

# 安裝依賴
RUN npm install

# 複製前端所有原始碼
COPY . .

# 執行生產環境打包
RUN npm run build

# --- 服務階段 ---
FROM nginx:alpine

# 複製 Nginx 設定檔
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 從建構階段複製打包好的靜態檔案到 Nginx 的服務目錄
COPY --from=build /app/dist /usr/share/nginx/html

# Nginx 預設監聽 80 port
EXPOSE 80

# 啟動 Nginx
CMD ["nginx", "-g", "daemon off;"]