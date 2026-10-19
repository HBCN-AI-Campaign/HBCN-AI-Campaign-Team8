FROM oven/bun:1.4.3-alpine AS build
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile --ignore-scripts
COPY tsconfig.json ./
COPY src ./src
COPY .opencode ./.opencode
RUN bun run typecheck && bun run build

FROM oven/bun:1.4.3-alpine
WORKDIR /app
ENV ASSISTANT_RUNTIME_HOST=0.0.0.0
COPY --from=build /app/dist ./dist
COPY --from=build /app/.opencode ./.opencode
USER bun
EXPOSE 8090
CMD ["bun", "run", "dist/index.js"]
