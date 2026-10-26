FROM node:24-bookworm-slim
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY --chown=node:node . .
RUN chown node:node /app
USER node
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
