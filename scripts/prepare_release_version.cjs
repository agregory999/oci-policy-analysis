/** Synchronize repository package metadata with semantic-release's version. */
const fs = require('node:fs');

const raw = process.argv[2];
const match = /^(\d+\.\d+\.\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(raw || '');
if (!match) throw new Error(`Unsupported release version: ${raw}`);
let version = match[1];
if (match[2]) {
  const parts = /^(.*)\.(\d+)$/.exec(match[2]);
  const label = (parts ? parts[1] : match[2]).toLowerCase();
  const number = parts ? parts[2] : '0';
  const phase = {a: 'a', alpha: 'a', b: 'b', beta: 'b', rc: 'rc'}[label] || '.dev';
  version += `${phase}${number}`;
}

const projectPath = 'pyproject.toml';
const project = fs.readFileSync(projectPath, 'utf8');
if (!/^version\s*=\s*"[^"]+"/m.test(project)) throw new Error('Missing project version');
fs.writeFileSync(projectPath, project.replace(/^version\s*=\s*"[^"]+"/m, `version = "${version}"`));
if (fs.existsSync('uv.lock')) {
  const lock = fs.readFileSync('uv.lock', 'utf8');
  const root = /(\[\[package\]\]\nname = "oci-policy-analysis"\nversion = ")[^"]+("\n)/;
  if (!root.test(lock)) throw new Error('Missing project package in uv.lock');
  fs.writeFileSync('uv.lock', lock.replace(root, (_match, start, end) => `${start}${version}${end}`));
}
console.log(`Prepared ${raw} as Python version ${version}`);
