// Bundles each piece folder into a self-contained CommonJS package and packs it as the
// ARCHIVE tarball that `POST /api/v1/pieces` accepts. Mirrors the official Activepieces CLI
// bundler (packages/cli/src/lib/utils/bundle-piece-utils.ts): esbuild, cjs, node20, minified
// with keepNames (the engine finds the piece by `constructor.name === 'Piece'`), with every
// @activepieces/* workspace package resolved from the read-only checkout's sources and all
// third-party code inlined so the published package has no runtime dependencies.
import { build } from 'esbuild'
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { builtinModules } from 'node:module'
import { dirname, join, resolve } from 'node:path'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const apRoot = resolve(process.env.ACTIVEPIECES_SRC ?? join(here, '..', '..', '..', 'ActivateDev', 'activepieces-main'))
const distRoot = join(here, 'dist')
const FAIL_BYTES = 5 * 1024 * 1024

function assertCheckout() {
  const marker = join(apRoot, 'packages', 'pieces', 'framework', 'src', 'index.ts')
  if (!existsSync(marker)) {
    throw new Error(`Activepieces sources not found at ${apRoot} (set ACTIVEPIECES_SRC). Expected ${marker}`)
  }
}

function aliases() {
  const p = (...parts) => resolve(apRoot, 'packages', ...parts)
  return {
    'mime-db': p('pieces', 'framework', 'src', 'mime-db-min.cjs'),
    '@activepieces/shared': p('core', 'shared', 'src'),
    '@activepieces/pieces-framework': p('pieces', 'framework', 'src'),
    '@activepieces/pieces-common': p('pieces', 'common', 'src'),
    '@activepieces/core-utils': p('core', 'utils', 'src'),
    '@activepieces/core-piece-types': p('core', 'piece-types', 'src'),
    '@activepieces/core-formula': p('core', 'formula', 'src'),
  }
}

const NODE_BUILTINS = new Set(builtinModules.flatMap((m) => [m, `node:${m}`]))

function externalizeBuiltins() {
  return {
    name: 'externalize-node-builtins',
    setup(b) {
      b.onResolve({ filter: /.*/ }, (args) => {
        if (args.kind === 'entry-point') return null
        if (args.path.startsWith('node:') || NODE_BUILTINS.has(args.path)) return { path: args.path, external: true }
        return null
      })
    },
  }
}

function pieceFolders() {
  return readdirSync(here).filter((name) => {
    const dir = join(here, name)
    return statSync(dir).isDirectory() && existsSync(join(dir, 'package.json')) && existsSync(join(dir, 'src', 'index.ts'))
  })
}

async function bundleOne(folder) {
  const pieceDir = join(here, folder)
  const manifest = JSON.parse(readFileSync(join(pieceDir, 'package.json'), 'utf8'))
  const outDir = join(distRoot, folder)
  rmSync(outDir, { recursive: true, force: true })
  mkdirSync(join(outDir, 'src'), { recursive: true })
  const outfile = join(outDir, 'src', 'index.js')

  const result = await build({
    entryPoints: [join(pieceDir, 'src', 'index.ts')],
    bundle: true,
    platform: 'node',
    target: 'node20',
    format: 'cjs',
    outfile,
    minify: true,
    keepNames: true,
    treeShaking: true,
    metafile: true,
    logLevel: 'warning',
    alias: aliases(),
    nodePaths: [join(here, 'node_modules')],
    plugins: [externalizeBuiltins()],
    loader: { '.node': 'file' },
  })

  const inlined = new Set()
  for (const input of Object.keys(result.metafile.inputs)) {
    const marker = 'node_modules/'
    const idx = input.lastIndexOf(marker)
    if (idx === -1) continue
    const rest = input.slice(idx + marker.length)
    inlined.add(rest.startsWith('@') ? rest.split('/').slice(0, 2).join('/') : rest.split('/')[0])
  }
  const bytes = statSync(outfile).size
  if (bytes > FAIL_BYTES) throw new Error(`${folder}: bundle is ${(bytes / 1024 / 1024).toFixed(2)} MB, over the 5 MB cap`)

  const published = {
    name: manifest.name,
    version: manifest.version,
    description: manifest.description,
    main: './src/index.js',
    dependencies: {},
    files: ['src/index.js', 'package.json'],
    license: manifest.license ?? 'UNLICENSED',
  }
  writeFileSync(join(outDir, 'package.json'), JSON.stringify(published, null, 2) + '\n')

  const packed = JSON.parse(execSync('npm pack --json --silent', { cwd: outDir, encoding: 'utf8' }))
  const tarball = join(outDir, packed[0].filename)
  const finalName = join(distRoot, packed[0].filename)
  rmSync(finalName, { force: true })
  execSync(`mv "${tarball}" "${finalName}"`)
  console.log(`[pieces] ${manifest.name}@${manifest.version} -> ${finalName} (${(bytes / 1024).toFixed(0)} KB bundle, inlined: ${[...inlined].sort().join(', ') || 'none'})`)
  return finalName
}

assertCheckout()
mkdirSync(distRoot, { recursive: true })
const folders = pieceFolders()
if (folders.length === 0) throw new Error('no piece folders found')
for (const folder of folders) await bundleOne(folder)
