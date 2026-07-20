import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" makes the build work on any static host (Netlify, Vercel, GH Pages, local file)
export default defineConfig({
  plugins: [react()],
  base: "./",
});
