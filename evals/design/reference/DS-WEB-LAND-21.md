```html
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Thimble Tailoring</title>
<style>
:root{--ink:#1d1a16;--paper:#f3efe6;--stone:#ddd6c8;--accent:#1f4f5a;--muted:#5b554b}
body{margin:0;font-family:"Source Serif 4",Georgia,serif;background:var(--paper);color:var(--ink);line-height:1.55;font-size:18px}
header{display:flex;justify-content:space-between;align-items:baseline;padding:24px 32px}
header a{color:var(--ink);text-decoration:none;font-weight:600}
nav a{margin-left:24px;font-weight:400}
main{padding:0 32px 64px;max-width:1120px}
h1{font-size:clamp(40px,7vw,80px);line-height:1.02;font-weight:700;margin:48px 0 24px;max-width:16ch;letter-spacing:-0.02em}
h2{font-size:28px;margin:48px 0 16px;font-weight:600}
p{max-width:60ch;margin:0 0 16px}
.lead{font-size:24px;max-width:40ch;margin-bottom:32px}
.action{display:inline-block;background:var(--accent);color:#fff;padding:16px 24px;text-decoration:none;font-weight:600;transition:transform 140ms cubic-bezier(0.22,1,0.36,1)}
.action:active{transform:scale(0.97)}
.action:focus-visible,a:focus-visible,button:focus-visible,input:focus-visible{outline:3px solid var(--ink);outline-offset:4px}
.band{background:var(--stone);padding:48px 32px;margin:48px -32px 0}
ul{margin:0;padding:0;list-style:none;font-size:20px}
li{padding:8px 0}
footer{padding:32px;font-size:16px;color:var(--muted)}
@media (max-width:640px){header{padding:16px}main{padding:0 16px 48px}.band{margin:32px -16px 0;padding:32px 16px}.lead{font-size:20px}}
@media (prefers-reduced-motion:reduce){.action{transition:none}}
</style></head><body>
<header><a href="/">Thimble Tailoring</a><nav><a href="#alterations">Alterations</a></nav></header>
<main>
<h1>Trousers hemmed by Thursday.</h1><p class="lead">Alterations in three days, made-to-measure suits in six weeks, in a shop on Pike Street since 1987.</p><a class="action" href="#book">Book a fitting</a><div class="band" id="alterations"><h2>Alterations</h2><ul><li>Hem: 18 dollars</li><li>Take in a jacket: 60 dollars</li><li>Replace a zip: 25 dollars</li></ul></div></main>
<footer>Thimble Tailoring, a alterations and made-to-measure tailor.</footer>
</body></html>
```
