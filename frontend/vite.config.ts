/// <reference types="vitest/config" />
import { readdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The website's brain map shows how many skill packs STAR has: counted from star/skill_packs at build time, so a
// pull request that adds a pack does not have to edit the site (site-v1.test.tsx checks the number).
const skillPacks = readdirSync(fileURLToPath(new URL('../star/skill_packs', import.meta.url)), { withFileTypes: true })
  .filter(entry => entry.isDirectory() && !entry.name.startsWith('_')).length
// Same for the lesson file: the number of lessons in star/skill_packs/lessons_bundled.json (all are candidates until
// the paired gate promotes them).
const lessons = JSON.parse(readFileSync(fileURLToPath(new URL('../star/skill_packs/lessons_bundled.json', import.meta.url)), 'utf8')).lessons.length

export default defineConfig({
  plugins: [react()],
  define: { __STAR_SKILL_PACKS__: JSON.stringify(String(skillPacks)), __STAR_LESSONS__: JSON.stringify(String(lessons)) },
  base: './',
  // Keep Vite 7's browser floor when adopting Vite 8's Rolldown/Oxc pipeline.
  build: { target: ['chrome107', 'edge107', 'firefox104', 'safari16'], outDir: 'dist', emptyOutDir: true, sourcemap: false, cssCodeSplit: false },
  server: { strictPort: true },
  // The tests that mount the whole Desktop take 1 to 3 seconds each alone and pass the default 5 second limit when
  // every test file runs at once on a busy PC. The limit only decides when a test counts as hung.
  test: { testTimeout: 20000 },
})
