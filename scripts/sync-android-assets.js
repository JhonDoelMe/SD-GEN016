// scripts/sync-android-assets.js
// Ensures /frontend/ path compatibility inside Android WebView
const fs = require('fs');
const path = require('path');

const publicDir = path.resolve(__dirname, '../android/app/src/main/assets/public');
const targetFrontendDir = path.join(publicDir, 'frontend');

if (fs.existsSync(publicDir)) {
  if (!fs.existsSync(targetFrontendDir)) {
    fs.mkdirSync(targetFrontendDir, { recursive: true });
  }

  const items = ['icons', 'js', 'styles.css', 'favicon.ico'];
  for (const item of items) {
    const src = path.join(publicDir, item);
    const dest = path.join(targetFrontendDir, item);
    if (fs.existsSync(src)) {
      if (fs.lstatSync(src).isDirectory()) {
        fs.cpSync(src, dest, { recursive: true });
      } else {
        fs.copyFileSync(src, dest);
      }
    }
  }
  console.log('✅ Android web assets synchronized with /frontend compatibility layer.');
}
