const { chromium } = require('playwright-core');
const fs = require('fs');
const sizes = [
  { name: '375x812', width: 375, height: 812 },
  { name: '390x844', width: 390, height: 844 },
  { name: '430x932', width: 430, height: 932 },
];
(async () => {
  const out = [];
  const browser = await chromium.launch();
  for (const s of sizes) {
    const page = await browser.newPage({ viewport: { width: s.width, height: s.height }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    await page.goto('http://localhost:3000/login', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('header', { timeout: 8000 }).catch(() => {});
    await page.waitForTimeout(400);
    const r = await page.evaluate(() => {
      const hdr = document.querySelector('header');
      const main = document.querySelector('main');
      const cs = (el) => el ? getComputedStyle(el) : null;
      return {
        headerH: hdr ? Math.round(hdr.getBoundingClientRect().height) : null,
        headerPT: hdr ? cs(hdr).paddingTop : null,
        headerPB: hdr ? cs(hdr).paddingBottom : null,
        mainPT: main ? cs(main).paddingTop : null,
        mainPB: main ? cs(main).paddingBottom : null,
        mainPL: main ? cs(main).paddingLeft : null,
        vh: window.innerHeight,
      };
    });
    out.push({ size: s.name, ...r });
    await page.close();
  }
  await browser.close();
  fs.writeFileSync('/tmp/hdr.json', JSON.stringify(out, null, 2));
})().catch((e) => { fs.writeFileSync('/tmp/hdr.json', 'ERR ' + e.stack); });
