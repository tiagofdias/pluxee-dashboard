"""Build a demo-only Pages artifact from an explicit public asset allowlist."""
import argparse
import html
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit("Demo output must be empty; refusing to include stale files.")
    output.mkdir(parents=True, exist_ok=True)
    source = ROOT / "static"
    private_url = os.getenv("PRIVATE_APP_URL", "").rstrip("/")
    if private_url and not private_url.startswith("https://"):
        raise SystemExit("PRIVATE_APP_URL must use HTTPS")
    page = (source / "index.html").read_text(encoding="utf-8")
    page = page.replace('<body class="auth-pending">', '<body class="auth-pending" data-demo="true" data-login-url="' + html.escape(private_url + '/login' if private_url else './login.html', quote=True) + '">')
    (output / "index.html").write_text(page, encoding="utf-8")
    (output / "demo.html").write_text(page, encoding="utf-8")
    for filename in ("style.css", "login.css", "app.js", "auth.js", "demo-data.js", "login.js", "manifest.json"):
        shutil.copy2(source / filename, output / filename)
    login = (source / "login.html").read_text(encoding="utf-8").replace('href="./demo"', 'href="./index.html"')
    (output / "login.html").write_text(login, encoding="utf-8")
    shutil.copytree(source / "icons", output / "icons", dirs_exist_ok=True)
    (output / ".nojekyll").touch()
    print("Demo artifact ready. No financial snapshots, runtime data or credentials included.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="_site")
    build(parser.parse_args().output)
