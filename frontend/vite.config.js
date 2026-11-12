import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API_PORT lets a second backend (e.g. DEMO=1 on 8001) run beside the real one.
const proxy = { "/api": `http://localhost:${process.env.API_PORT || 8000}` };

export default defineConfig({
  plugins: [react()],
  // dev: npm run dev (hot reload). preview: what start.bat launches — serves the
  // production build, which needs the same proxy since it has no dev server.
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
});
