# Imagen de DESARROLLO del frontend (issue #14): dev server de Vite con hot
# reload. El código (src/ y configs) se monta por volumen desde docker-compose.yml
# y node_modules queda solo en la imagen (el host no necesita npm install para
# Docker). Cambiar package.json sí requiere rebuild: docker compose build web.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

EXPOSE 5173

# --host 0.0.0.0: el dev server debe escuchar desde fuera del contenedor.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
