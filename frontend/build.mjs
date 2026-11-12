import { cp, mkdir, rm, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

process.chdir(fileURLToPath(new URL('.', import.meta.url)));

if (process.env.VERCEL === '1') {
  const backend = new URL(process.env.UNIMATCH_API_ORIGIN || '');
  const config = JSON.parse(await readFile('vercel.json', 'utf8'));
  if (backend.protocol !== 'https:' || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash ||
      !config.rewrites?.some(route => route.source === '/api/:path*' && route.destination === `${backend.origin}/api/:path*`)) {
    throw new Error('Set UNIMATCH_API_ORIGIN and align vercel.json with the verified production backend before deploying.');
  }
}

await rm("dist", { recursive: true, force: true });
await mkdir("dist", { recursive: true });
const files = [
  "index.html", "landing.html", "login.html", "dashboard.html", "rebuild.html",
  "portal.css", "portal.js", "campus-scene.js", "nested-research.js",
  "rebuild-app.js", "student-cohorts.js", "assets",
];
await Promise.all(files.map((file) => cp(file, `dist/${file}`, { recursive: true })));
await mkdir("dist/vendor", { recursive: true });
await cp("node_modules/three/build", "dist/vendor/three", { recursive: true });
await cp("node_modules/three/LICENSE", "dist/vendor/three/LICENSE.txt");
console.log("Built frontend/dist with portal pages, 3D scene and self-hosted fonts");
