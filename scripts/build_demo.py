"""Build a demo-only Pages artifact from an explicit public asset allowlist."""
import argparse
import html
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Demo output must be empty; refusing to include stale files.")
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "static"
    config = json.loads((ROOT / "public-site.json").read_text(encoding="utf-8-sig"))
    private_url = (os.getenv("PRIVATE_APP_URL", "").strip() or config.get("private_app_url", "")).rstrip("/")
    origin = urlsplit(private_url)
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path or origin.query or origin.fragment):
        raise SystemExit("Configure PRIVATE_APP_URL as an HTTPS origin, without a path or credentials")
    page = (source / "index.html").read_text(encoding="utf-8")
    page = page.replace('<body class="auth-pending">', '<body class="auth-pending" data-demo="true" data-login-url="' + html.escape(private_url + '/login' if private_url else './login.html', quote=True) + '">')
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "demo.html").write_text(page, encoding="utf-8")
    for filename in ("style.css", "login.css", "app.js", "auth.js", "demo-data.js", "login-redirect.js", "manifest.json"):
        shutil.copy2(source / filename, output / filename)
    target = html.escape(private_url + '/login', quote=True)
    # A static deployment must never present a password form or call /api/auth.
    login = f'''<!doctype html>
<html lang="pt-PT"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Pluxee · Abrir área privada</title>
<link rel="stylesheet" href="./login.css?v=20261029-4"><script src="./login-redirect.js?v=20261029-4" defer></script></head>
<body class="login-page" data-private-login-url="{target}">
<header class="login-header"><a class="brand" href="./index.html">pluxee<span class="brand-period">.</span></a><a class="top-demo" href="./index.html">Ver demonstração ↗</a></header>
<main class="login-main"><section class="login-card"><p class="eyebrow">ACESSO SEGURO</p>
<h1>A tua área<br><span>privada.</span></h1><p class="login-intro">Vamos abrir a página onde podes iniciar sessão e consultar o teu cartão.</p>
<a id="private-login-link" class="login-submit" href="{target}"><span>Continuar para o login</span><span>↗</span></a>
<p class="independent-note">A demonstração usa apenas dados fictícios.</p></section></main></body></html>'''
    (output / "login.html").write_text(login, encoding="utf-8")
    shutil.copytree(source / "icons", output / "icons", dirs_exist_ok=True)
    (output / ".nojekyll").touch()
    print("Demo artifact ready. No financial snapshots, runtime data or credentials included.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="_site")
    build(parser.parse_args().output)
