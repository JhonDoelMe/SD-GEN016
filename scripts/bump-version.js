// scripts/bump-version.js
// Single source of truth version synchronizer for SD-GEN016

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const VERSION_FILE = path.join(ROOT, 'version.json');

function parseArgs(argv) {
  const opts = { bump: 'patch', set: null, code: null, syncOnly: false };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--sync-only') {
      opts.syncOnly = true;
      opts.bump = 'none';
    } else if (arg === '--bump' && argv[i + 1]) {
      opts.bump = argv[++i];
    } else if (arg === '--set' && argv[i + 1]) {
      opts.set = argv[++i];
    } else if (arg === '--code' && argv[i + 1]) {
      opts.code = parseInt(argv[++i], 10);
    }
  }
  return opts;
}

function bumpSemver(versionName, kind) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(versionName.trim());
  if (!match) {
    throw new Error(`Unsupported versionName format: ${versionName}`);
  }
  let [, major, minor, patch] = match.map((x) => parseInt(x, 10));
  if (kind === 'major') {
    major += 1;
    minor = 0;
    patch = 0;
  } else if (kind === 'minor') {
    minor += 1;
    patch = 0;
  } else if (kind === 'patch') {
    patch += 1;
  } else if (kind !== 'none') {
    throw new Error(`Invalid bump type "${kind}". Use patch | minor | major | none.`);
  }
  return `${major}.${minor}.${patch}`;
}

function replaceFile(relPath, replacer) {
  const fullPath = path.join(ROOT, relPath);
  const raw = fs.readFileSync(fullPath, 'utf8');
  const next = replacer(raw);
  if (next !== raw) {
    fs.writeFileSync(fullPath, next, 'utf8');
  }
}

function main() {
  const opts = parseArgs(process.argv);
  const current = JSON.parse(fs.readFileSync(VERSION_FILE, 'utf8'));
  let nextName = current.versionName;
  let nextCode = Number(current.versionCode);

  if (opts.set) {
    if (!/^\d+\.\d+\.\d+$/.test(opts.set.trim())) {
      throw new Error(`Invalid --set version "${opts.set}". Expected X.Y.Z`);
    }
    nextName = opts.set.trim();
    nextCode = opts.code !== null ? opts.code : nextCode + 1;
  } else if (!opts.syncOnly && opts.bump !== 'none') {
    nextName = bumpSemver(current.versionName, opts.bump);
    nextCode = opts.code !== null ? opts.code : nextCode + 1;
  } else if (opts.code !== null) {
    nextCode = opts.code;
  }

  if (!Number.isInteger(nextCode) || nextCode < 1) {
    throw new Error(`Invalid versionCode: ${nextCode}`);
  }

  fs.writeFileSync(
    VERSION_FILE,
    JSON.stringify({ versionName: nextName, versionCode: nextCode }, null, 2) + '\n',
    'utf8'
  );

  replaceFile('package.json', (txt) => {
    const pkg = JSON.parse(txt);
    pkg.version = nextName;
    return JSON.stringify(pkg, null, 2) + '\n';
  });

  replaceFile('android/app/build.gradle', (txt) =>
    txt
      .replace(/versionCode\s+\d+/, `versionCode ${nextCode}`)
      .replace(/versionName\s+"[^"]+"/, `versionName "${nextName}"`)
  );

  replaceFile('frontend/index.html', (txt) =>
    txt.replace(/\?v=\d+\.\d+\.\d+/g, `?v=${nextName}`)
  );

  replaceFile('frontend/sw.js', (txt) =>
    txt
      .replace(/CACHE_NAME = 'sd-gen016-v[^']+'/, `CACHE_NAME = 'sd-gen016-v${nextName}'`)
      .replace(/\?v=\d+\.\d+\.\d+/g, `?v=${nextName}`)
  );

  replaceFile('backend/app/main.py', (txt) =>
    txt.replace(/(\bapp = FastAPI\([\s\S]*?\bversion=)"[^"]+"/, `$1"${nextName}"`)
  );

  console.log(JSON.stringify({ versionName: nextName, versionCode: nextCode }));
}

main();
